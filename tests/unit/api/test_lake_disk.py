"""The API's hold on the lake: places, markers, paths inside the lake, locks and readiness."""

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
    LakeDisk,
)
from huron.core.lake.organizations.declarations import Declarations, DeclaredOrganization
from huron.core.lake.uploads.models import Upload, UploadState
from huron.core.storage import (
    MARKER_FILE,
    SHARE_GROUP_PENDING,
    UPLOAD_DIR,
    LakeUnavailable,
    Marker,
    OpenFile,
    OrganizationPlace,
    OutsideLake,
    ShareWarning,
    render_marker,
)
from huron.core.storage.memory import MemoryStorage
from huron.pkg.clock import FrozenClock
from tests.support.api import INSTANCE_ID, ROOT_MARKER
from tests.support.clock import LoopClock, frozen
from tests.support.disk import (
    LAKE,
    SERVICE_GID,
    SIGNAL_TIMEOUT,
    StalledStorage,
    lake_disk,
    memory_lake,
)
from tests.support.lake import CONTRIBUTOR, World, make_world, seed, settled_collection

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
    opened = lake_disk(storage, clock)
    yield opened
    opened.close()


@pytest.fixture
async def declared_disk(storage: MemoryStorage, clock: FrozenClock) -> AsyncIterator[LakeDisk]:
    """The disk of a service that declares helio (rooted in the lake), space and geo."""
    opened = lake_disk(storage, clock, declarations=DECLARED)
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
    disk = lake_disk(storage, clock, mount_prefix=Path("/projects/huron"))
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
    disk = lake_disk(storage, clock, lake_path=missing, mount_prefix=missing)
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


class LinkPausingStorage(MemoryStorage):
    """The in-memory lake, whose links wait until :attr:`release` is set."""

    def __init__(self) -> None:
        super().__init__(LAKE, uid=SERVICE_GID, gid=SERVICE_GID)
        self.write_bytes(LAKE / MARKER_FILE, ROOT_MARKER)
        self.linking = threading.Event()
        self.release = threading.Event()
        self.order: list[str] = []

    def link(
        self, source: Path, destination: Path, part_name: str, backup_name: str
    ) -> Path | None:
        """Wait for :attr:`release`, then link."""
        self.linking.set()
        assert self.release.wait(SIGNAL_TIMEOUT)
        linked = super().link(source, destination, part_name, backup_name)
        self.order.append("linked")
        return linked


async def received(world: World, storage: MemoryStorage, data: bytes) -> Upload:
    """A pending upload of ``data`` to ``c.bin`` of collection run7, received by tusd."""
    collection = await settled_collection(world.lake)
    storage.add_root(LAKE / "helio" / "heliophysics" / "solar-wind" / "run7")
    storage.make_directory(LAKE / UPLOAD_DIR, 0o700)
    upload = await world.lake.uploads.begin(CONTRIBUTOR, collection, "c.bin", len(data))
    storage.write_bytes(LAKE / UPLOAD_DIR / str(upload.id), data, 0o600)
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
    inode = storage.inode(LAKE / UPLOAD_DIR / str(upload.id))
    destination = await world.lake.uploads.placement(CONTRIBUTOR, upload.id)
    placed = await disk.place(world.lake.uploads, CONTRIBUTOR, upload, destination)
    assert (placed.state, placed.size, placed.inode) == (UploadState.PLACED, 5, inode)
    assert placed.sha256 == hashlib.sha256(b"bytes").hexdigest()
    assert storage.inode(LAKE / destination.path) == inode


async def test_a_cancelled_placement_records_its_receipt_before_it_frees_the_path(
    world: World, clock: FrozenClock, loop_errors: list[dict[str, object]]
) -> None:
    storage = LinkPausingStorage()
    disk = lake_disk(storage, clock)
    try:
        upload = await received(world, storage, b"bytes")
        destination = await world.lake.uploads.placement(CONTRIBUTOR, upload.id)
        placing = asyncio.create_task(
            disk.place(world.lake.uploads, CONTRIBUTOR, upload, destination)
        )
        assert await asyncio.to_thread(storage.linking.wait, SIGNAL_TIMEOUT)
        path = LAKE / destination.path
        after = asyncio.create_task(disk.run(path, lambda: storage.order.append("after")))
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
        self.write_bytes(LAKE / MARKER_FILE, ROOT_MARKER)
        self.full = threading.Event()
        self.release = threading.Event()
        self.waiting = 0
        self.counting = threading.Lock()

    def open_file(self, path: Path) -> OpenFile | None:
        """Open ``path``; its hash waits for :attr:`release`."""
        opened = super().open_file(path)
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
        storage.write_bytes(LAKE / UPLOAD_DIR / str(upload.id), b"bytes", 0o600)
        uploads.append(upload)
    placing = []
    for upload in uploads:
        destination = await world.lake.uploads.placement(CONTRIBUTOR, upload.id)
        placing.append(
            asyncio.create_task(disk.place(world.lake.uploads, CONTRIBUTOR, upload, destination))
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
        note = LAKE / "helio" / "note"
        await asyncio.wait_for(
            disk.run(note, lambda: storage.write_bytes(note, b"written")), SIGNAL_TIMEOUT
        )
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
    monkeypatch.setattr("huron.applications.api.disk.ThreadPoolExecutor", RecordingExecutor)
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
            await disk.run(LAKE / "helio", lambda: None)
        late = await world.lake.uploads.begin(CONTRIBUTOR, collection_id, "late", 5)
        destination = await world.lake.uploads.placement(CONTRIBUTOR, late.id)
        with pytest.raises(RuntimeError, match="after shutdown"):
            await disk.place(world.lake.uploads, CONTRIBUTOR, late, destination)
    finally:
        storage.release.set()
        disk.close()
