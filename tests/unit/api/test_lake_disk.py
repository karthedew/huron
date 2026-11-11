"""The API's hold on the lake: places, markers, the gate, locks, readiness, directories and
placements.
"""

import asyncio
import gc
import hashlib
import threading
import uuid
from collections.abc import AsyncIterator, Callable
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from typing import ClassVar

import pytest
import structlog

from huron.applications.api.disk import (
    DISK_WORKERS,
    HASH_WORKERS,
    PROBE_TIMEOUT,
    PROBE_TTL,
    LakeDirectories,
    LakeDisk,
    Located,
    NoLake,
    Placements,
    Render,
    Run,
)
from huron.core.lake.uploads.models import Failure, Upload, UploadState
from huron.core.storage import (
    MARKER_FILE,
    SHARE_GROUP_PENDING,
    UPLOAD_DIR_MODE,
    UPLOADS,
    DirectoryWriter,
    LakePath,
    LakeUnavailable,
    Marker,
    OpenFile,
    OrganizationPlace,
    Placer,
    ShareWarning,
    Storage,
    StorageError,
    render_marker,
)
from huron.core.storage.memory import MemoryStorage
from huron.core.storage.posix import PosixStorage
from huron.pkg.clock import FrozenClock
from huron.pkg.errors import HuronError
from tests.support.api import INSTANCE_ID, ROOT_MARKER
from tests.support.clock import LoopClock, frozen
from tests.support.disk import (
    LAKE,
    SERVICE_GID,
    SIGNAL_TIMEOUT,
    StalledStorage,
    lake_disk,
    memory_lake,
    plant_symlink,
)
from tests.support.lake import CONTRIBUTOR, World, make_world, seed, settled_collection

ROOTS = LakePath.of("roots")
RUN7 = LakePath.of("helio", "heliophysics", "solar-wind", "run7")
PLACES = {
    "helio": OrganizationPlace("helio", ROOTS, own_marker=True),
    "space": OrganizationPlace("space", LakePath(), own_marker=True),
}


@pytest.fixture
def storage() -> MemoryStorage:
    return memory_lake()


@pytest.fixture
def clock() -> FrozenClock:
    return frozen()


@pytest.fixture
async def disk(storage: MemoryStorage, clock: FrozenClock) -> AsyncIterator[LakeDisk]:
    """The disk of an unmanaged service over the in-memory lake."""
    opened = lake_disk(storage, clock)
    yield opened
    opened.close()


@pytest.fixture
async def declared_disk(storage: MemoryStorage, clock: FrozenClock) -> AsyncIterator[LakeDisk]:
    """The disk of a service that declares helio (rooted in the lake) and space."""
    opened = lake_disk(storage, clock, places=PLACES)
    yield opened
    opened.close()


def mark(storage: MemoryStorage, directory: LakePath, organization: str | None) -> None:
    storage.add_directory(directory)
    marker = Marker(1, "http://huron.test", str(INSTANCE_ID), organization)
    storage.write_bytes(directory.joinpath(MARKER_FILE), render_marker(marker), 0o644)


def test_locate_follows_the_declared_places(declared_disk: LakeDisk) -> None:
    assert declared_disk.locate("other/heliophysics") == Located(
        OrganizationPlace("other", LakePath(), own_marker=False),
        LakePath.of("other", "heliophysics"),
    )
    assert declared_disk.locate("helio/heliophysics/a") == Located(
        PLACES["helio"], LakePath.of("roots", "helio", "heliophysics", "a")
    )
    assert declared_disk.locate("space/x").location == LakePath.of("space", "x")
    located = declared_disk.locate("helio/heliophysics")
    assert located.joinpath("a", "b") == Located(
        PLACES["helio"], LakePath.of("roots", "helio", "heliophysics", "a", "b")
    )


@pytest.mark.parametrize("api_path", ["other/../geo", "other//x", "", "/other", "other/."])
def test_locate_refuses_a_name_that_is_not_a_lake_name(
    declared_disk: LakeDisk, storage: MemoryStorage, api_path: str
) -> None:
    before = list(storage.calls)
    with pytest.raises(HuronError) as raised:
        declared_disk.locate(api_path)
    assert (raised.value.code, raised.value.status) == ("NAME_INVALID", 422)
    assert storage.calls == before


async def test_a_lake_root_that_does_not_open_is_unavailable(
    tmp_path: Path, clock: FrozenClock
) -> None:
    disk = lake_disk(PosixStorage(tmp_path / "unmounted"), clock)
    try:
        with pytest.raises(LakeUnavailable) as raised:
            await disk.work(disk.locate("helio/heliophysics"), lambda: None)
        assert (raised.value.code, raised.value.status) == ("LAKE_UNAVAILABLE", 503)
        with pytest.raises(LakeUnavailable, match="does not open"):
            await disk.open()
    finally:
        disk.close()


async def test_the_shared_marker_guards_unrooted_organizations(
    disk: LakeDisk, storage: MemoryStorage
) -> None:
    located = disk.locate("helio")
    assert await disk.work(located, lambda: "done") == "done"
    mark(storage, LakePath(), "helio")
    with pytest.raises(LakeUnavailable, match="names organization helio, not the lake path"):
        await disk.work(located, lambda: None)
    storage.remove_file(LakePath.of(MARKER_FILE))
    with pytest.raises(LakeUnavailable, match=r"no \.huron marker") as raised:
        await disk.work(located, lambda: None)
    assert raised.value.context["state"] == "no marker"


async def test_a_declared_organization_has_its_own_marker(
    declared_disk: LakeDisk, storage: MemoryStorage
) -> None:
    located = declared_disk.locate("helio/heliophysics")
    with pytest.raises(LakeUnavailable, match="roots/helio is not mounted"):
        await declared_disk.work(located, lambda: None)
    mark(storage, ROOTS.joinpath("helio"), "helio")
    await declared_disk.work(located, lambda: None)
    other = render_marker(Marker(1, "http://other", "other"))
    storage.write_bytes(ROOTS.joinpath("helio", MARKER_FILE), other, 0o644)
    with pytest.raises(LakeUnavailable, match="another Huron service"):
        await declared_disk.work(located, lambda: None)


async def test_a_link_on_the_way_to_the_marker_is_refused_as_a_link(
    declared_disk: LakeDisk, storage: MemoryStorage
) -> None:
    plant_symlink(storage, ROOTS)
    ran: list[str] = []
    with pytest.raises(StorageError) as raised:
        await declared_disk.work(declared_disk.locate("helio/x"), lambda: ran.append("ran"))
    assert (raised.value.code, raised.value.context["path"]) == ("SYMLINK_IN_LAKE", "roots")
    assert ran == []


async def test_hold_verifies_the_marker_before_each_run(
    disk: LakeDisk, storage: MemoryStorage
) -> None:
    ran: list[str] = []

    async def unit(run: Run) -> None:
        await run(lambda: ran.append("first"))
        storage.remove_file(LakePath.of(MARKER_FILE))
        await run(lambda: ran.append("second"))

    with pytest.raises(LakeUnavailable, match="marker"):
        await disk.hold(disk.locate("helio/x"), unit)
    assert ran == ["first"]


async def test_measure_holds_no_lock_and_checks_no_marker(
    disk: LakeDisk, storage: MemoryStorage
) -> None:
    started, release = threading.Event(), threading.Event()
    located = disk.locate("helio/x")

    def slow() -> None:
        started.set()
        release.wait(SIGNAL_TIMEOUT)

    holding = asyncio.create_task(disk.work(located, slow))
    await asyncio.wait_for(asyncio.to_thread(started.wait), SIGNAL_TIMEOUT)
    storage.remove_file(LakePath.of(MARKER_FILE))
    assert await asyncio.wait_for(disk.measure(lambda: "measured"), SIGNAL_TIMEOUT) == "measured"
    release.set()
    await holding


async def test_a_lake_the_api_cannot_write_is_unavailable(
    disk: LakeDisk, storage: MemoryStorage
) -> None:
    storage.denied.add(LakePath())
    with pytest.raises(LakeUnavailable, match="cannot write the lake") as raised:
        await disk.open()
    assert raised.value.context["path"] == ".tus-uploads"


async def test_a_link_at_the_upload_directory_is_refused_as_a_link(
    tmp_path: Path, clock: FrozenClock
) -> None:
    (tmp_path / "lake").mkdir()
    (tmp_path / "outside").mkdir()
    (tmp_path / "lake" / ".tus-uploads").symlink_to(tmp_path / "outside")
    disk = lake_disk(PosixStorage(tmp_path / "lake"), clock)
    try:
        with pytest.raises(StorageError) as raised:
            await disk.open()
    finally:
        disk.close()
    assert (raised.value.code, raised.value.status) == ("SYMLINK_IN_LAKE", 409)
    assert raised.value.context["path"] == ".tus-uploads"
    assert list((tmp_path / "outside").iterdir()) == []


async def test_open_makes_the_upload_directory_once(disk: LakeDisk, storage: MemoryStorage) -> None:
    await disk.open()
    found = storage.stat(UPLOADS)
    assert found is not None and found.mode == UPLOAD_DIR_MODE
    storage.set_mode(UPLOADS, 0o750)
    await disk.open()
    found = storage.stat(UPLOADS)
    assert found is not None and found.mode == 0o750


async def test_the_lake_is_ready_when_the_upload_directory_is_writable(
    disk: LakeDisk, storage: MemoryStorage, clock: FrozenClock
) -> None:
    assert await disk.ready() is False
    await disk.open()
    assert await disk.ready() is False  # the answer is kept
    clock.advance(PROBE_TTL)
    assert await disk.ready() is True
    assert storage.is_empty(UPLOADS)


async def test_the_answer_is_kept_for_ten_seconds(
    disk: LakeDisk, storage: MemoryStorage, clock: FrozenClock
) -> None:
    await disk.open()
    assert await disk.ready() is True
    storage.denied.add(UPLOADS)
    clock.advance(PROBE_TTL - timedelta(microseconds=1))
    assert await disk.ready() is True
    clock.advance(timedelta(microseconds=1))
    assert await disk.ready() is False


async def test_a_probe_that_does_not_answer_in_time_is_not_ready(
    clock: FrozenClock, loop_clock: LoopClock
) -> None:
    stalled = StalledStorage()
    disk = lake_disk(stalled, clock)

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


async def test_work_holds_the_lock_of_its_place(disk: LakeDisk) -> None:
    order: list[str] = []
    started = threading.Event()
    release = threading.Event()
    target = disk.locate("helio")

    def slow() -> str:
        started.set()
        release.wait(5)
        order.append("first")
        return "done"

    first = asyncio.create_task(disk.work(target, slow))
    await asyncio.wait_for(asyncio.to_thread(started.wait), 5)
    second = asyncio.create_task(disk.work(target, lambda: order.append("second")))
    other = await asyncio.wait_for(disk.work(disk.locate("geo"), lambda: len(order)), 5)
    assert other == 0
    release.set()
    assert await first == "done"
    await second
    assert order == ["first", "second"]


@pytest.mark.parametrize("fails", [False, True], ids=["returns", "raises"])
@pytest.mark.parametrize("cancellations", [1, 2])
async def test_a_cancelled_work_holds_the_lock_until_its_action_returns(
    disk: LakeDisk, loop_errors: list[dict[str, object]], cancellations: int, fails: bool
) -> None:
    order: list[str] = []
    started = threading.Event()
    release = threading.Event()
    target = disk.locate("helio")

    def slow() -> None:
        started.set()
        release.wait(5)
        order.append("first")
        if fails:
            raise RuntimeError("the lake is gone")

    with structlog.testing.capture_logs() as logged:
        first = asyncio.create_task(disk.work(target, slow))
        await asyncio.wait_for(asyncio.to_thread(started.wait), 5)
        second = asyncio.create_task(disk.work(target, lambda: order.append("second")))
        for _ in range(cancellations):
            first.cancel()
            await asyncio.wait_for(disk.work(disk.locate("geo"), lambda: None), 5)
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
        "path": "helio",
        "error": repr(RuntimeError("the lake is gone")),
    }
    assert logged == ([failure] if fails else [])


async def test_a_cancelled_work_whose_action_never_started_ends_quietly(
    disk: LakeDisk, loop_errors: list[dict[str, object]]
) -> None:
    busy = threading.Barrier(DISK_WORKERS + 1)
    release = threading.Event()

    def block() -> None:
        busy.wait(5)
        release.wait(5)

    blockers = [
        asyncio.create_task(disk.work(disk.locate(f"busy-{n}"), block)) for n in range(DISK_WORKERS)
    ]
    await asyncio.wait_for(asyncio.to_thread(busy.wait, 5), 5)
    with structlog.testing.capture_logs() as logged:
        queued = asyncio.create_task(disk.work(disk.locate("queued"), lambda: None))
        await asyncio.sleep(0)  # the work hands its action to the full pool and waits
        queued.cancel()
        disk.close()
        with pytest.raises(asyncio.CancelledError):
            await queued
    release.set()
    await asyncio.wait_for(asyncio.gather(*blockers), 5)
    gc.collect()
    assert (logged, loop_errors) == ([], [])


async def test_work_passes_errors_through(disk: LakeDisk) -> None:
    def fail() -> None:
        raise LakeUnavailable("the lake is gone", {})

    with pytest.raises(LakeUnavailable, match="the lake is gone"):
        await disk.work(disk.locate("helio"), fail)


CATALOG = LakePath.of("helio", "heliophysics")
COLLECTION = CATALOG.joinpath("solar-wind", "run7")


@pytest.fixture
def directories(disk: LakeDisk, storage: MemoryStorage) -> LakeDirectories:
    """The directory verbs over the helio catalog directory; helio-readers is known."""
    storage.groups.update({"helio-readers": 2001, "geo-readers": 2002})
    storage.member_of.add(2001)
    storage.make_directory(LakePath.of("helio"), 0o2751)
    storage.make_directory(CATALOG, 0o2750)
    return LakeDirectories(disk, DirectoryWriter(storage, SERVICE_GID))


def gid(storage: Storage, location: LakePath) -> int:
    found = storage.stat(location)
    assert found is not None
    return found.gid


def rendered(body: bytes | None, reads: list[str] | None = None) -> Render:
    """A render that answers ``body`` and notes each read in ``reads``."""

    async def render() -> bytes | None:
        if reads is not None:
            reads.append("read")
        return body

    return render


async def test_a_share_group_that_can_be_set_gives_no_warning(
    directories: LakeDirectories, storage: MemoryStorage
) -> None:
    assert await directories.set_group("helio/heliophysics", "helio-readers") is None
    assert gid(storage, CATALOG) == 2001
    assert await directories.set_group("helio/heliophysics", "helio-readers") is None


async def test_a_cleared_share_group_gives_the_directory_the_service_group(
    directories: LakeDirectories, storage: MemoryStorage
) -> None:
    await directories.set_group("helio/heliophysics", "helio-readers")
    assert await directories.set_group("helio/heliophysics", None) is None
    assert gid(storage, CATALOG) == SERVICE_GID
    assert await directories.set_group("helio/heliophysics", None) is None


@pytest.mark.parametrize(
    ("api_path", "group", "named", "detail"),
    [
        (
            "helio/heliophysics",
            "geo-readers",
            "geo-readers",
            "helio/heliophysics: Operation not permitted",
        ),
        (
            "helio/heliophysics",
            "nobody-knows",
            "nobody-knows",
            "this machine does not know the group nobody-knows",
        ),
        ("helio/aurora", "helio-readers", "helio-readers", "helio/aurora does not exist"),
        ("helio/aurora", None, str(SERVICE_GID), "helio/aurora does not exist"),
    ],
)
async def test_a_share_group_that_cannot_be_set_is_pending(
    directories: LakeDirectories, api_path: str, group: str | None, named: str, detail: str
) -> None:
    warning = await directories.set_group(api_path, group)
    assert warning == ShareWarning(SHARE_GROUP_PENDING, named, detail)


async def test_a_directory_the_service_does_not_own_keeps_its_group_when_cleared(
    directories: LakeDirectories, storage: MemoryStorage
) -> None:
    storage.nodes[CATALOG].uid, storage.nodes[CATALOG].gid = 0, 2001
    warning = await directories.set_group("helio/heliophysics", None)
    assert warning == ShareWarning(
        SHARE_GROUP_PENDING, str(SERVICE_GID), "helio/heliophysics: Operation not permitted"
    )
    assert gid(storage, CATALOG) == 2001


async def test_a_share_group_needs_the_marker_and_no_link_on_the_way(
    directories: LakeDirectories, storage: MemoryStorage
) -> None:
    storage.make_directory(LakePath.of("geo"), 0o2751)
    plant_symlink(storage, LakePath.of("geo", "catalog"))
    with pytest.raises(StorageError) as linked:
        await directories.set_group("geo/catalog", "helio-readers")
    assert linked.value.code == "SYMLINK_IN_LAKE"
    storage.remove_file(LakePath.of(MARKER_FILE))
    with pytest.raises(LakeUnavailable):
        await directories.set_group("helio/heliophysics", "helio-readers")
    assert gid(storage, CATALOG) != 2001


async def test_make_gives_each_directory_its_mode(
    directories: LakeDirectories, storage: MemoryStorage
) -> None:
    await directories.make("geo")
    await directories.make("helio/heliophysics/solar-wind")
    geo, namespace = storage.stat(LakePath.of("geo")), storage.stat(COLLECTION.parent)
    assert geo is not None and namespace is not None
    assert (geo.mode, namespace.mode) == (0o2751, 0o2750)
    assert namespace.gid == gid(storage, CATALOG)


async def test_a_verb_refuses_a_path_that_breaks_the_naming_rules(
    directories: LakeDirectories, storage: MemoryStorage
) -> None:
    storage.calls.clear()
    with pytest.raises(HuronError) as refused:
        await directories.make("helio/..")
    assert (refused.value.code, refused.value.status) == ("NAME_INVALID", 422)
    assert storage.calls == []


async def test_metadata_is_rendered_under_the_lock_and_written_when_it_differs(
    directories: LakeDirectories, disk: LakeDisk, storage: MemoryStorage
) -> None:
    storage.make_directory(COLLECTION.parent, 0o2750)
    storage.make_directory(COLLECTION, 0o2750)
    holding, release, reads = asyncio.Event(), asyncio.Event(), []

    async def held(run: Run) -> None:
        holding.set()
        await release.wait()

    holder = asyncio.create_task(disk.hold(disk.locate(str(COLLECTION)), held))
    await holding.wait()
    writing = asyncio.create_task(
        directories.write_metadata(str(COLLECTION), rendered(b"{}\n", reads))
    )
    await asyncio.sleep(0.01)
    assert reads == []
    release.set()
    await asyncio.gather(holder, writing)
    metadata = COLLECTION.joinpath("metadata.json")
    assert (reads, storage.read_bytes(metadata)) == (["read"], b"{}\n")
    storage.calls.clear()
    await directories.write_metadata(str(COLLECTION), rendered(b"{}\n"))
    await directories.write_metadata(str(COLLECTION), rendered(None))
    assert storage.calls == []


async def test_a_removal_that_keeps_the_directory_goes_to_the_log(
    directories: LakeDirectories, storage: MemoryStorage
) -> None:
    storage.make_directory(COLLECTION.parent, 0o2750)
    storage.make_directory(COLLECTION, 0o2750)
    storage.write_bytes(COLLECTION.joinpath("stray.bin"), b"x", 0o644)
    with structlog.testing.capture_logs() as logged:
        await directories.remove_collection(str(COLLECTION))
        await directories.remove(str(COLLECTION.parent))
    assert [(e["event"], e["path"]) for e in logged] == [
        ("disk.directory_kept", str(COLLECTION)),
        ("disk.directory_kept", str(COLLECTION.parent)),
    ]
    storage.remove_file(COLLECTION.joinpath("stray.bin"))
    with structlog.testing.capture_logs() as logged:
        await directories.remove_collection(str(COLLECTION))
        await directories.remove(str(COLLECTION.parent))
        await directories.remove(str(COLLECTION.parent))
    assert logged == []
    assert storage.stat(COLLECTION.parent) is None


async def test_without_a_lake_every_verb_returns_at_once() -> None:
    reads: list[str] = []
    no_lake = NoLake()
    await no_lake.make("helio/..")
    assert await no_lake.set_group("helio/heliophysics", "helio-readers") is None
    await no_lake.write_metadata("helio/heliophysics/solar-wind/run7", rendered(b"{}", reads))
    await no_lake.remove("helio")
    await no_lake.remove_collection("helio/heliophysics/solar-wind/run7")
    assert reads == []


class LinkPausingStorage(MemoryStorage):
    """The in-memory lake, whose links wait until :attr:`release` is set."""

    def __init__(self) -> None:
        super().__init__(LAKE, uid=SERVICE_GID, gid=SERVICE_GID)
        self.write_bytes(LakePath.of(MARKER_FILE), ROOT_MARKER, 0o644)
        self.linking = threading.Event()
        self.release = threading.Event()
        self.order: list[str] = []

    def link(
        self,
        source: LakePath,
        destination: LakePath,
        *,
        inode: int,
        part_name: str,
        backup_name: str,
    ) -> LakePath | None:
        """Wait for :attr:`release`, then link."""
        self.linking.set()
        assert self.release.wait(SIGNAL_TIMEOUT)
        linked = super().link(
            source, destination, inode=inode, part_name=part_name, backup_name=backup_name
        )
        self.order.append("linked")
        return linked


async def received(
    world: World, storage: MemoryStorage, data: bytes, rel_path: str = "c.bin"
) -> Upload:
    """A pending upload of ``data`` to ``rel_path`` of collection run7, received by tusd."""
    collection = await settled_collection(world.lake)
    storage.add_directory(RUN7)
    storage.make_directory(UPLOADS, 0o700)
    upload = await world.lake.uploads.begin(CONTRIBUTOR, collection, rel_path, len(data))
    storage.write_bytes(UPLOADS.joinpath(str(upload.id)), data, 0o600)
    return upload


@pytest.fixture
async def world() -> World:
    """The seeded lake domain over the in-memory store."""
    created = await make_world()
    await seed(created)
    return created


async def test_place_links_the_upload_and_records_its_receipt(
    world: World, disk: LakeDisk, storage: MemoryStorage
) -> None:
    upload = await received(world, storage, b"bytes")
    inode = inode_of(storage, UPLOADS.joinpath(str(upload.id)))
    destination = await world.lake.uploads.placement(CONTRIBUTOR, upload.id)
    placed = await placements(disk, storage).place(
        world.lake.uploads, CONTRIBUTOR, upload, destination
    )
    assert (placed.state, placed.size, placed.inode) == (UploadState.PLACED, 5, inode)
    assert placed.sha256 == hashlib.sha256(b"bytes").hexdigest()
    assert inode_of(storage, RUN7.joinpath("c.bin")) == inode


async def test_place_puts_the_names_of_the_path_below_the_collection_directory(
    world: World, disk: LakeDisk, storage: MemoryStorage
) -> None:
    upload = await received(world, storage, b"bytes", "day1/solar/c.bin")
    storage.nodes[RUN7].mode = 0o2750
    inode = inode_of(storage, UPLOADS.joinpath(str(upload.id)))
    destination = await world.lake.uploads.placement(CONTRIBUTOR, upload.id)
    await placements(disk, storage).place(world.lake.uploads, CONTRIBUTOR, upload, destination)
    assert inode_of(storage, RUN7.joinpath("day1", "solar", "c.bin")) == inode


async def test_a_link_at_the_collection_directory_fails_the_upload(
    world: World, disk: LakeDisk, storage: MemoryStorage
) -> None:
    upload = await received(world, storage, b"bytes")
    del storage.nodes[RUN7]
    plant_symlink(storage, RUN7)
    destination = await world.lake.uploads.placement(CONTRIBUTOR, upload.id)
    with pytest.raises(StorageError) as raised:
        await placements(disk, storage).place(world.lake.uploads, CONTRIBUTOR, upload, destination)
    assert (raised.value.code, raised.value.status) == ("SYMLINK_IN_LAKE", 409)
    assert raised.value.context["path"] == str(RUN7)
    failed = await world.lake.uploads.get(CONTRIBUTOR, upload.id)
    assert failed.state is UploadState.FAILED
    assert failed.failure == Failure("SYMLINK_IN_LAKE", raised.value.message)
    assert storage.stat(UPLOADS.joinpath(str(upload.id))) is not None


async def test_a_link_at_the_upload_file_fails_the_upload(
    world: World, disk: LakeDisk, storage: MemoryStorage
) -> None:
    upload = await received(world, storage, b"bytes")
    source = UPLOADS.joinpath(str(upload.id))
    del storage.nodes[source]
    plant_symlink(storage, source)
    destination = await world.lake.uploads.placement(CONTRIBUTOR, upload.id)
    with pytest.raises(StorageError) as raised:
        await placements(disk, storage).place(world.lake.uploads, CONTRIBUTOR, upload, destination)
    assert raised.value.code == "SYMLINK_IN_LAKE"
    failed = await world.lake.uploads.get(CONTRIBUTOR, upload.id)
    assert failed.failure == Failure("SYMLINK_IN_LAKE", raised.value.message)


async def test_a_cancelled_placement_records_its_receipt_before_it_frees_the_path(
    world: World, clock: FrozenClock, loop_errors: list[dict[str, object]]
) -> None:
    storage = LinkPausingStorage()
    disk = lake_disk(storage, clock)
    try:
        upload = await received(world, storage, b"bytes")
        destination = await world.lake.uploads.placement(CONTRIBUTOR, upload.id)
        placing = asyncio.create_task(
            placements(disk, storage).place(world.lake.uploads, CONTRIBUTOR, upload, destination)
        )
        assert await asyncio.to_thread(storage.linking.wait, SIGNAL_TIMEOUT)
        target = disk.locate(str(RUN7.joinpath("c.bin")))
        after = asyncio.create_task(disk.work(target, lambda: storage.order.append("after")))
        placing.cancel()
        storage.release.set()
        with pytest.raises(asyncio.CancelledError):
            await placing
        assert (await world.lake.uploads.get(CONTRIBUTOR, upload.id)).state is UploadState.PLACED
        await asyncio.wait_for(after, SIGNAL_TIMEOUT)
        assert storage.order == ["linked", "after"]
    finally:
        storage.release.set()
        disk.close()
    assert loop_errors == []


class HashBlockingStorage(MemoryStorage):
    """The in-memory lake, whose hashes wait until :attr:`release` is set.

    :attr:`full` is set once :data:`HASH_WORKERS` hashes wait at the same time.
    """

    def __init__(self) -> None:
        super().__init__(LAKE, uid=SERVICE_GID, gid=SERVICE_GID)
        self.write_bytes(LakePath.of(MARKER_FILE), ROOT_MARKER, 0o644)
        self.full = threading.Event()
        self.release = threading.Event()
        self.waiting = 0
        self.counting = threading.Lock()

    def open_file(self, location: LakePath) -> OpenFile | None:
        """Open ``location``; its hash waits for :attr:`release`."""
        opened = super().open_file(location)
        return None if opened is None else BlockedHash(opened, self)


class BlockedHash:
    """A file of a :class:`HashBlockingStorage`, whose hash waits for the storage's release."""

    def __init__(self, opened: OpenFile, storage: HashBlockingStorage) -> None:
        self._opened = opened
        self._storage = storage
        self.size = opened.size
        self.inode = opened.inode

    def sha256(self) -> str:
        storage = self._storage
        with storage.counting:
            storage.waiting += 1
            if storage.waiting == HASH_WORKERS:
                storage.full.set()
        if not storage.release.wait(SIGNAL_TIMEOUT):
            raise TimeoutError("the test never released the blocked hashes")
        return self._opened.sha256()

    def set_mode(self, mode: int) -> None:
        self._opened.set_mode(mode)

    def close(self) -> None:
        self._opened.close()


async def start_placements(
    world: World, disk: LakeDisk, storage: MemoryStorage, count: int
) -> tuple[uuid.UUID, list[asyncio.Task[Upload]]]:
    """Start ``count`` placements of received five-byte uploads; returns run7's id and them."""
    first = await received(world, storage, b"bytes")
    uploads = [first]
    for n in range(count - 1):
        upload = await world.lake.uploads.begin(CONTRIBUTOR, first.collection_id, f"{n}", 5)
        storage.write_bytes(UPLOADS.joinpath(str(upload.id)), b"bytes", 0o600)
        uploads.append(upload)
    placing = []
    for upload in uploads:
        destination = await world.lake.uploads.placement(CONTRIBUTOR, upload.id)
        placing.append(
            asyncio.create_task(
                placements(disk, storage).place(
                    world.lake.uploads, CONTRIBUTOR, upload, destination
                )
            )
        )
    return first.collection_id, placing


async def test_blocked_hash_workers_delay_neither_readiness_nor_other_disk_calls(
    world: World, clock: FrozenClock
) -> None:
    storage = HashBlockingStorage()
    disk = lake_disk(storage, clock)
    try:
        await disk.open()
        # More placements than the disk pool has workers: one pool for both would be full.
        _, placing = await start_placements(world, disk, storage, DISK_WORKERS + 1)
        assert await asyncio.to_thread(storage.full.wait, SIGNAL_TIMEOUT)
        assert await asyncio.wait_for(disk.ready(), SIGNAL_TIMEOUT) is True
        note = LakePath.of("helio", "note")

        def write() -> None:
            storage.write_bytes(note, b"written", 0o644)

        await asyncio.wait_for(disk.work(disk.locate("helio/note"), write), SIGNAL_TIMEOUT)
        assert storage.read_bytes(note) == b"written"
        assert storage.waiting == HASH_WORKERS
        storage.release.set()
        placed = await asyncio.wait_for(asyncio.gather(*placing), SIGNAL_TIMEOUT)
        assert {upload.state for upload in placed} == {UploadState.PLACED}
    finally:
        storage.release.set()
        disk.close()


class RecordingExecutor(ThreadPoolExecutor):
    """A thread pool that records the name prefix of its threads at every submission."""

    submitted: ClassVar[list[str]] = []

    def __init__(self, max_workers: int, thread_name_prefix: str = "") -> None:
        super().__init__(max_workers, thread_name_prefix=thread_name_prefix)
        self.prefix = thread_name_prefix

    def submit[**P, T](self, fn: Callable[P, T], /, *args: P.args, **kwargs: P.kwargs) -> Future[T]:
        """Submit ``fn`` and record the submission."""
        future = super().submit(fn, *args, **kwargs)
        self.submitted.append(self.prefix)
        return future


async def test_close_drops_a_queued_hash_and_refuses_later_disk_work(
    world: World, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("huron.applications.api.disk.lake.ThreadPoolExecutor", RecordingExecutor)
    monkeypatch.setattr(RecordingExecutor, "submitted", [])
    storage = HashBlockingStorage()
    disk = lake_disk(storage, clock)
    try:
        await disk.open()
        collection_id, placing = await start_placements(world, disk, storage, HASH_WORKERS + 1)

        async def queued() -> None:
            while RecordingExecutor.submitted.count("huron-hash") <= HASH_WORKERS:
                await asyncio.sleep(0)

        await asyncio.wait_for(queued(), SIGNAL_TIMEOUT)
        assert await asyncio.to_thread(storage.full.wait, SIGNAL_TIMEOUT)
        disk.close()
        storage.release.set()
        ended = await asyncio.wait_for(
            asyncio.gather(*placing, return_exceptions=True), SIGNAL_TIMEOUT
        )
        assert sorted(type(outcome).__name__ for outcome in ended) == [
            "CancelledError",
            *["RuntimeError"] * HASH_WORKERS,
        ]
        assert storage.waiting == HASH_WORKERS
        with pytest.raises(RuntimeError, match="after shutdown"):
            await disk.work(disk.locate("helio"), lambda: None)
        late = await world.lake.uploads.begin(CONTRIBUTOR, collection_id, "late", 5)
        destination = await world.lake.uploads.placement(CONTRIBUTOR, late.id)
        with pytest.raises(RuntimeError, match="after shutdown"):
            await placements(disk, storage).place(
                world.lake.uploads, CONTRIBUTOR, late, destination
            )
    finally:
        storage.release.set()
        disk.close()


def placements(disk: LakeDisk, storage: Storage) -> Placements:
    return Placements(disk, Placer(storage))


def inode_of(storage: Storage, location: LakePath) -> int:
    found = storage.stat(location)
    assert found is not None
    return found.inode


class Reader:
    """A writer whose lock another process holds."""

    writable = False


async def test_the_upload_directory_is_guarded_by_the_marker_at_the_root(
    disk: LakeDisk, storage: MemoryStorage
) -> None:
    located = disk.in_uploads("x")
    place = OrganizationPlace(".tus-uploads", LakePath(), own_marker=False)
    assert located == Located(place, UPLOADS.joinpath("x"))
    assert disk.in_uploads().location == UPLOADS
    assert await disk.work(located, lambda: "done") == "done"
    storage.remove_file(LakePath.of(MARKER_FILE))
    with pytest.raises(LakeUnavailable, match=r"no \.huron marker"):
        await disk.work(located, lambda: None)


async def test_readiness_links_from_the_object_area_into_each_declared_organization(
    declared_disk: LakeDisk, storage: MemoryStorage, clock: FrozenClock
) -> None:
    await declared_disk.open()
    assert await declared_disk.ready() is False  # no organization directory is mounted
    for place in PLACES.values():
        mark(storage, place.directory, place.name)
    clock.advance(PROBE_TTL)
    assert await declared_disk.ready() is True
    for place in PLACES.values():
        area = storage.stat(place.objects)
        assert area is not None and area.mode == 0o700
        assert storage.is_empty(place.objects)
        assert [name for name in storage.nodes if name.parent == place.directory] == [
            place.directory.joinpath(MARKER_FILE),
            place.objects,
        ]
    storage.mounts.add(PLACES["space"].objects)
    clock.advance(PROBE_TTL)
    assert await declared_disk.ready() is False


async def test_a_reader_writes_nothing_and_its_gate_refuses_every_step(
    storage: MemoryStorage, clock: FrozenClock
) -> None:
    disk = lake_disk(storage, clock, places=PLACES, writer=Reader())
    try:
        assert await disk.ready() is False
        storage.make_directory(UPLOADS, UPLOAD_DIR_MODE)
        calls = list(storage.calls)
        clock.advance(PROBE_TTL)
        assert await disk.ready() is True
        assert storage.calls == calls
        with pytest.raises(LakeUnavailable) as refused:
            await disk.work(disk.locate("helio"), lambda: None)
        assert refused.value.context == {"reason": "writer_lock"}
        storage.unreadable.add(LakePath())
        clock.advance(PROBE_TTL)
        assert await disk.ready() is False
    finally:
        disk.close()
