"""The API's hold on the lake: places, markers, paths inside the lake, locks and readiness."""

import asyncio
import gc
import threading
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import pytest
import structlog

from huron.applications.api.disk import DISK_WORKERS, PROBE_TIMEOUT, PROBE_TTL, LakeDisk
from huron.core.lake.organizations.declarations import Declarations, DeclaredOrganization
from huron.core.storage import (
    MARKER_FILE,
    SHARE_GROUP_PENDING,
    UPLOAD_DIR,
    LakeUnavailable,
    Marker,
    OrganizationPlace,
    OutsideLake,
    ShareWarning,
    render_marker,
)
from huron.core.storage.memory import MemoryStorage
from huron.pkg.clock import FrozenClock
from tests.support.api import INSTANCE_ID
from tests.support.clock import LoopClock, frozen
from tests.support.disk import LAKE, SERVICE_GID, StalledStorage, memory_disk, memory_lake

ROOTS = LAKE / "roots"
DECLARED = Declarations.of(
    [
        DeclaredOrganization("helio", root=str(ROOTS)),
        DeclaredOrganization("space"),
        DeclaredOrganization("geo", root="/data2/huron", export="nfs2:/export/geo"),
    ]
)


@pytest.fixture
def storage() -> MemoryStorage:
    return memory_lake()


@pytest.fixture
def clock() -> FrozenClock:
    return frozen()


@pytest.fixture
async def disk(storage: MemoryStorage, clock: FrozenClock) -> AsyncIterator[LakeDisk]:
    """The disk of an unmanaged service over the in-memory lake."""
    opened = memory_disk(storage, clock)
    yield opened
    opened.close()


@pytest.fixture
async def declared_disk(storage: MemoryStorage, clock: FrozenClock) -> AsyncIterator[LakeDisk]:
    """The disk of a service that declares helio (rooted in the lake), space and geo."""
    opened = memory_disk(storage, clock, declarations=DECLARED)
    yield opened
    opened.close()


def mark(storage: MemoryStorage, directory: Path, organization: str | None) -> None:
    storage.add_root(directory)
    marker = Marker(1, "http://huron.test", str(INSTANCE_ID), organization)
    storage.write_bytes(directory / MARKER_FILE, render_marker(marker))


def test_places_follow_the_declarations(declared_disk: LakeDisk) -> None:
    assert declared_disk.place_of("helio") == OrganizationPlace(
        "helio", ROOTS, rooted=True, declared=True
    )
    assert declared_disk.place_of("space") == OrganizationPlace(
        "space", LAKE, rooted=False, declared=True
    )
    assert declared_disk.place_of("geo").export == "nfs2:/export/geo"
    assert declared_disk.place_of("other") == OrganizationPlace("other", LAKE, rooted=False)


async def test_a_path_resolves_inside_the_lake(declared_disk: LakeDisk) -> None:
    assert await declared_disk.resolve("other/heliophysics") == LAKE / "other" / "heliophysics"
    assert await declared_disk.resolve("helio/heliophysics/a") == ROOTS / "helio/heliophysics/a"


@pytest.mark.parametrize("relative", ["geo/catalog", "other/../geo", "other//x", ""])
async def test_a_path_outside_the_lake_is_refused(declared_disk: LakeDisk, relative: str) -> None:
    with pytest.raises(OutsideLake) as raised:
        await declared_disk.resolve(relative)
    assert (raised.value.code, raised.value.status) == ("OUTSIDE_LAKE", 422)


async def test_a_mount_prefix_outside_the_lake_puts_unrooted_organizations_outside(
    storage: MemoryStorage, clock: FrozenClock
) -> None:
    disk = memory_disk(storage, clock, mount_prefix=Path("/projects/huron"))
    try:
        with pytest.raises(OutsideLake, match="outside the lake /lake"):
            await disk.resolve("helio/heliophysics")
    finally:
        disk.close()


@pytest.mark.parametrize(
    ("mounted", "relative"),
    [
        (LAKE / "helio", "helio/heliophysics/solar-wind"),
        (LAKE / "helio" / "heliophysics", "helio/heliophysics"),
    ],
)
async def test_a_path_on_another_filesystem_is_refused(
    disk: LakeDisk, storage: MemoryStorage, mounted: Path, relative: str
) -> None:
    storage.mount(mounted, 7)
    with pytest.raises(OutsideLake, match="different filesystem") as raised:
        await disk.resolve(relative)
    assert raised.value.context == {"path": relative, "lake_path": str(LAKE)}
    assert await disk.resolve("geo/catalog") == LAKE / "geo" / "catalog"


async def test_a_lake_path_that_is_not_a_directory_is_unavailable(
    storage: MemoryStorage, clock: FrozenClock
) -> None:
    missing = Path("/unmounted")
    disk = memory_disk(storage, clock, lake_path=missing, mount_prefix=missing)
    try:
        with pytest.raises(LakeUnavailable) as raised:
            await disk.resolve("helio/heliophysics")
        assert (raised.value.code, raised.value.status) == ("LAKE_UNAVAILABLE", 503)
        with pytest.raises(LakeUnavailable, match="not a directory"):
            await disk.open()
    finally:
        disk.close()


async def test_the_shared_marker_guards_unrooted_organizations(
    disk: LakeDisk, storage: MemoryStorage
) -> None:
    place = disk.place_of("helio")
    await disk.check_marker(place)
    mark(storage, LAKE, "helio")
    with pytest.raises(LakeUnavailable, match="names organization helio, not the share root"):
        await disk.check_marker(place)
    storage.remove_file(LAKE / MARKER_FILE)
    with pytest.raises(LakeUnavailable, match=r"no \.huron marker") as raised:
        await disk.check_marker(place)
    assert raised.value.context["state"] == "no marker"


async def test_a_declared_organization_has_its_own_marker(
    declared_disk: LakeDisk, storage: MemoryStorage
) -> None:
    place = declared_disk.place_of("helio")
    with pytest.raises(LakeUnavailable, match="not mounted"):
        await declared_disk.check_marker(place)
    mark(storage, ROOTS / "helio", "helio")
    await declared_disk.check_marker(place)
    storage.write_bytes(
        ROOTS / "helio" / MARKER_FILE, render_marker(Marker(1, "http://other", "other"))
    )
    with pytest.raises(LakeUnavailable, match="another Huron service"):
        await declared_disk.check_marker(place)


async def test_a_lake_the_api_cannot_write_is_unavailable(
    disk: LakeDisk, storage: MemoryStorage
) -> None:
    storage.denied.add(LAKE)
    with pytest.raises(LakeUnavailable, match="cannot write the lake /lake") as raised:
        await disk.open()
    assert raised.value.context == {"lake_path": str(LAKE), "path": str(LAKE)}


async def test_open_makes_the_upload_directory_once(disk: LakeDisk, storage: MemoryStorage) -> None:
    await disk.open()
    assert disk.upload_dir == LAKE / UPLOAD_DIR
    assert storage.owner(disk.upload_dir).mode == 0o700
    storage.set_mode(disk.upload_dir, 0o750)
    await disk.open()
    assert storage.owner(disk.upload_dir).mode == 0o750


async def test_the_lake_is_ready_when_the_upload_directory_is_writable(
    disk: LakeDisk, storage: MemoryStorage, clock: FrozenClock
) -> None:
    assert await disk.ready() is False
    await disk.open()
    assert await disk.ready() is False  # the answer is kept
    clock.advance(PROBE_TTL)
    assert await disk.ready() is True
    assert [p for p in storage.nodes if p.parent == disk.upload_dir] == []


async def test_the_answer_is_kept_for_ten_seconds(
    disk: LakeDisk, storage: MemoryStorage, clock: FrozenClock
) -> None:
    await disk.open()
    assert await disk.ready() is True
    storage.denied.add(disk.upload_dir)
    clock.advance(PROBE_TTL - timedelta(microseconds=1))
    assert await disk.ready() is True
    clock.advance(timedelta(microseconds=1))
    assert await disk.ready() is False


async def test_a_probe_that_does_not_answer_in_time_is_not_ready(
    clock: FrozenClock, loop_clock: LoopClock
) -> None:
    stalled = StalledStorage()
    disk = memory_disk(stalled, clock)

    async def ready_after_the_timeout() -> bool:
        probing = asyncio.create_task(disk.ready())
        assert await asyncio.to_thread(stalled.waiting.wait, 5)
        loop_clock.advance(PROBE_TIMEOUT)
        return await probing

    try:
        await disk.open()
        assert await ready_after_the_timeout() is False
        clock.advance(PROBE_TTL)
        assert await ready_after_the_timeout() is False
        assert stalled.writes == 1  # the hung probe is awaited again, not started twice
        stalled.release.set()
        clock.advance(PROBE_TTL)
        assert await disk.ready() is True
    finally:
        stalled.release.set()
        disk.close()


async def test_run_holds_the_lock_of_its_path(disk: LakeDisk) -> None:
    order: list[str] = []
    started = threading.Event()
    release = threading.Event()
    target = LAKE / "helio"

    def slow() -> str:
        started.set()
        release.wait(5)
        order.append("first")
        return "done"

    first = asyncio.create_task(disk.run(target, slow))
    await asyncio.wait_for(asyncio.to_thread(started.wait), 5)
    second = asyncio.create_task(disk.run(target, lambda: order.append("second")))
    other = await asyncio.wait_for(disk.run(LAKE / "geo", lambda: len(order)), 5)
    assert other == 0
    release.set()
    assert await first == "done"
    await second
    assert order == ["first", "second"]


@pytest.mark.parametrize("fails", [False, True], ids=["returns", "raises"])
@pytest.mark.parametrize("cancellations", [1, 2])
async def test_a_cancelled_run_holds_the_lock_until_its_action_returns(
    disk: LakeDisk, loop_errors: list[dict[str, object]], cancellations: int, fails: bool
) -> None:
    order: list[str] = []
    started = threading.Event()
    release = threading.Event()
    target = LAKE / "helio"

    def slow() -> None:
        started.set()
        release.wait(5)
        order.append("first")
        if fails:
            raise RuntimeError("the lake is gone")

    with structlog.testing.capture_logs() as logged:
        first = asyncio.create_task(disk.run(target, slow))
        await asyncio.wait_for(asyncio.to_thread(started.wait), 5)
        second = asyncio.create_task(disk.run(target, lambda: order.append("second")))
        for _ in range(cancellations):
            first.cancel()
            await asyncio.wait_for(disk.run(LAKE / "geo", lambda: None), 5)
        assert (first.done(), second.done(), order) == (False, False, [])
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await first
        await asyncio.wait_for(second, 5)
    assert order == ["first", "second"]
    gc.collect()
    assert loop_errors == []
    failure = {
        "event": "disk.cancelled_action_failed",
        "log_level": "error",
        "path": str(target),
        "error": repr(RuntimeError("the lake is gone")),
    }
    assert logged == ([failure] if fails else [])


async def test_a_cancelled_run_whose_action_never_started_ends_quietly(
    disk: LakeDisk, loop_errors: list[dict[str, object]]
) -> None:
    busy = threading.Barrier(DISK_WORKERS + 1)
    release = threading.Event()

    def block() -> None:
        busy.wait(5)
        release.wait(5)

    blockers = [
        asyncio.create_task(disk.run(LAKE / f"busy-{n}", block)) for n in range(DISK_WORKERS)
    ]
    await asyncio.wait_for(asyncio.to_thread(busy.wait, 5), 5)
    with structlog.testing.capture_logs() as logged:
        queued = asyncio.create_task(disk.run(LAKE / "queued", lambda: None))
        await asyncio.sleep(0)  # the run hands its action to the full pool and waits
        queued.cancel()
        disk.close()
        with pytest.raises(asyncio.CancelledError):
            await queued
    release.set()
    await asyncio.wait_for(asyncio.gather(*blockers), 5)
    gc.collect()
    assert (logged, loop_errors) == ([], [])


async def test_run_passes_errors_through(disk: LakeDisk) -> None:
    def fail() -> None:
        raise LakeUnavailable("the lake is gone", {})

    with pytest.raises(LakeUnavailable, match="the lake is gone"):
        await disk.run(LAKE, fail)


@pytest.fixture
def catalog(storage: MemoryStorage) -> Path:
    """The helio organization and heliophysics catalog directories; helio-readers is known."""
    storage.groups.update({"helio-readers": 2001, "geo-readers": 2002})
    storage.member_of.add(2001)
    storage.make_directory(LAKE / "helio", 0o2751)
    storage.make_directory(LAKE / "helio" / "heliophysics", 0o2750)
    return LAKE / "helio" / "heliophysics"


async def test_a_share_group_that_can_be_set_gives_no_warning(
    disk: LakeDisk, storage: MemoryStorage, catalog: Path
) -> None:
    assert await disk.set_share_group("helio/heliophysics", "helio-readers") is None
    assert storage.owner(catalog).gid == 2001
    assert await disk.set_share_group("helio/heliophysics", "helio-readers") is None


async def test_a_cleared_share_group_gives_the_directory_the_service_group(
    disk: LakeDisk, storage: MemoryStorage, catalog: Path
) -> None:
    await disk.set_share_group("helio/heliophysics", "helio-readers")
    assert await disk.set_share_group("helio/heliophysics", None) is None
    assert storage.owner(catalog).gid == SERVICE_GID
    assert await disk.set_share_group("helio/heliophysics", None) is None


@pytest.mark.parametrize(
    ("relative", "group", "named", "detail"),
    [
        (
            "helio/heliophysics",
            "geo-readers",
            "geo-readers",
            "/lake/helio/heliophysics: Operation not permitted",
        ),
        (
            "helio/heliophysics",
            "nobody-knows",
            "nobody-knows",
            "this machine does not know the group nobody-knows",
        ),
        (
            "helio/aurora",
            "helio-readers",
            "helio-readers",
            "/lake/helio/aurora: No such file or directory",
        ),
        ("helio/aurora", None, str(SERVICE_GID), "/lake/helio/aurora: No such file or directory"),
    ],
)
async def test_a_share_group_that_cannot_be_set_is_pending(
    disk: LakeDisk, catalog: Path, relative: str, group: str | None, named: str, detail: str
) -> None:
    warning = await disk.set_share_group(relative, group)
    assert warning == ShareWarning(SHARE_GROUP_PENDING, named, detail)


async def test_a_directory_the_service_does_not_own_keeps_its_group_when_cleared(
    disk: LakeDisk, storage: MemoryStorage, catalog: Path
) -> None:
    storage.nodes[catalog].uid, storage.nodes[catalog].gid = 0, 2001
    warning = await disk.set_share_group("helio/heliophysics", None)
    assert warning == ShareWarning(
        SHARE_GROUP_PENDING, str(SERVICE_GID), f"{catalog}: Operation not permitted"
    )
    assert storage.owner(catalog).gid == 2001


async def test_a_share_group_needs_the_lake_and_its_marker(
    disk: LakeDisk, storage: MemoryStorage, catalog: Path
) -> None:
    storage.mount(LAKE / "geo", 7)
    with pytest.raises(OutsideLake):
        await disk.set_share_group("geo/catalog", "helio-readers")
    storage.remove_file(LAKE / MARKER_FILE)
    with pytest.raises(LakeUnavailable):
        await disk.set_share_group("helio/heliophysics", "helio-readers")
    assert storage.owner(catalog).gid != 2001
