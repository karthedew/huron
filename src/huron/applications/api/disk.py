"""The API's hold on the lake: where paths are, which marker guards them, and the disk work.

The lake is a ``hard`` NFS mount, so a disk call can block without end during an outage. All
disk work therefore runs in dedicated pools of worker threads, never in the event loop or the
default executor, and readiness waits for its probe only for a bounded time. The hashes of
uploads run in a pool of their own, so a burst of large uploads never delays the probe or the
short directory and metadata calls.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import timedelta
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

import structlog

from huron.core.lake.uploads.errors import UploadNotFound, UploadStateConflict
from huron.core.lake.uploads.models import UploadState
from huron.core.storage import (
    MARKER_FILE,
    SHARE_GROUP_PENDING,
    UPLOAD_DIR,
    UPLOAD_DIR_MODE,
    CollectionDirectoryMissing,
    GroupOutcome,
    GroupResult,
    LakeUnavailable,
    Measured,
    OrganizationPlace,
    OutsideLake,
    Placer,
    ShareWarning,
    SourceGone,
    StorageError,
    place_of,
    verify_marker,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from datetime import datetime
    from pathlib import Path

    from huron.core.lake.organizations.declarations import Declarations
    from huron.core.lake.uploads.models import Destination, Upload
    from huron.core.lake.uploads.operations import Uploads
    from huron.core.security.rbac import Actor
    from huron.core.storage import PathLocks, Storage
    from huron.pkg.clock import Clock

__all__ = ["DISK_WORKERS", "HASH_WORKERS", "PROBE_TIMEOUT", "PROBE_TTL", "LakeDisk"]

#: The worker threads of the disk pool, which runs every disk call but the hashes of uploads.
DISK_WORKERS = 8
#: The worker threads of the hash pool, which measures uploads.
HASH_WORKERS = 4
#: How long readiness waits for the lake probe, in seconds.
PROBE_TIMEOUT = 2.0
#: How long readiness keeps the probe's answer.
PROBE_TTL = timedelta(seconds=10)

_log = structlog.get_logger(__name__)


class LakeDisk:
    """The lake mounted read-write at ``lake_path``, which this process alone writes.

    Organizations without a root lie directly below ``lake_path``. Every path the lake hands out
    resolves at or below ``lake_path`` on the lake's own filesystem, because a placement links
    files and a hard link cannot cross filesystems. ``locks`` serialize the disk work of one
    path within this process. ``service_gid`` is the service group, the process's primary
    group, which a catalog without a share group carries.
    """

    def __init__(
        self,
        storage: Storage,
        lake_path: Path,
        instance_id: str,
        declarations: Declarations,
        locks: PathLocks,
        *,
        service_gid: int,
        clock: Clock,
        probe_timeout: float = PROBE_TIMEOUT,
    ) -> None:
        self._storage = storage
        self._lake_path = lake_path
        self._instance_id = instance_id
        self._declarations = declarations
        self._locks = locks
        self._service_gid = service_gid
        self._clock = clock
        self._probe_timeout = probe_timeout
        self._placer = Placer(storage, lake_path)
        self._pool = ThreadPoolExecutor(DISK_WORKERS, thread_name_prefix="huron-disk")
        self._hash_pool = ThreadPoolExecutor(HASH_WORKERS, thread_name_prefix="huron-hash")
        self._probe: asyncio.Future[bool] | None = None
        self._probed: tuple[datetime, bool] | None = None

    @property
    def upload_dir(self) -> Path:
        """tusd's filestore, ``<lake_path>/.tus-uploads``."""
        return self._lake_path / UPLOAD_DIR

    async def open(self) -> None:
        """Create the upload directory with mode ``0700`` when it is missing.

        Raises ``LAKE_UNAVAILABLE`` when ``lake_path`` is not a directory or this process
        cannot write it.
        """
        await self._call(self._open)

    def close(self) -> None:
        """Stop the disk pool and the hash pool; work that has not started is dropped."""
        self._pool.shutdown(wait=False, cancel_futures=True)
        self._hash_pool.shutdown(wait=False, cancel_futures=True)

    async def ready(self) -> bool:
        """Whether this process can write the upload directory.

        The answer is kept for :data:`PROBE_TTL`. A probe that does not answer within the
        timeout counts as ``False``; while it still runs, no second probe starts.
        """
        now = self._clock.now()
        if self._probed is not None and now - self._probed[0] < PROBE_TTL:
            return self._probed[1]
        if self._probe is None or self._probe.done():
            self._probe = asyncio.get_running_loop().run_in_executor(self._pool, self._writable)
        try:
            ready = await asyncio.wait_for(asyncio.shield(self._probe), self._probe_timeout)
        except TimeoutError:
            ready = False
        self._probed = (now, ready)
        return ready

    def place_of(self, organization: str) -> OrganizationPlace:
        """Where ``organization``'s directory is: below its declared root, else ``lake_path``."""
        declared = self._declarations.get(organization)
        if declared is None:
            return place_of(organization, None, False, self._lake_path)
        return place_of(organization, declared.root, True, self._lake_path, declared.export or None)

    async def check_marker(self, place: OrganizationPlace) -> None:
        """Refuse with ``LAKE_UNAVAILABLE`` unless the marker guarding ``place`` is this lake's."""
        await self._call(lambda: self._check_marker(place))

    async def resolve(self, relative: str) -> Path:
        """The absolute path of an API path (``<organization>/…``) inside the lake.

        Raises ``OUTSIDE_LAKE`` for a path outside ``lake_path`` or on another filesystem, and
        ``LAKE_UNAVAILABLE`` when ``lake_path`` is not a directory.
        """
        return await self._call(lambda: self._resolve(relative))

    async def run[T](self, path: Path, action: Callable[[], T]) -> T:
        """Run ``action`` in the disk pool while holding the lock of ``path``.

        The lock stays held until ``action`` returns, also when the caller is cancelled: a
        worker thread cannot be stopped, so the next action on ``path`` waits for it. When
        ``action`` raises after its caller is cancelled, the error goes to the log, because no
        caller is left.
        """
        return await self._hold(path, lambda: self._submit(action))

    async def set_share_group(self, catalog_path: str, group: str | None) -> ShareWarning | None:
        """Try to give the catalog directory its share group, or the service group for ``None``.

        A catalog without a share group carries the service group, which only this process
        reads. ``None`` when the directory has the group; otherwise the ``SHARE_GROUP_PENDING``
        warning for the storage administrator, which names the service group by its number.
        """
        path = await self.resolve(catalog_path)
        place = self.place_of(_organization(catalog_path))
        target = self._service_gid if group is None else group

        def attempt() -> GroupResult:
            self._check_marker(place)
            return self._storage.set_group(path, target)

        result = await self.run(path, attempt)
        if result.outcome is not GroupOutcome.PENDING:
            return None
        return ShareWarning(SHARE_GROUP_PENDING, f"{target}", result.reason or "")

    async def place(
        self, uploads: Uploads, actor: Actor, upload: Upload, destination: Destination
    ) -> Upload:
        """Place the actor's pending ``upload`` at ``destination`` and record its receipt.

        The file goes to the names of ``destination.rel_path`` below the collection directory
        ``destination.directory``.

        The hash runs in the hash pool, outside every lock. The link, the removal of tusd's files
        and the receipt run under the lock of the destination path. A file the placement
        replaces stays as a backup until the receipt is recorded. A receipt refused because the
        collection or the upload ended during the hash takes the placed file away again, puts a
        replaced file back, and raises the refusal. A path outside the lake and a missing
        collection directory fail the upload. When the upload's file is gone, another attempt
        moved it: the upload's state, or the file at the destination, decides. Raises
        ``STORAGE_FAILED`` when neither proves the placement, and ``LAKE_UNAVAILABLE`` when the
        lake or its marker refuses the write.
        """
        try:
            collection_dir = await self.resolve(destination.directory)
        except OutsideLake as error:
            await uploads.fail(upload.id, error.code, error.message)
            raise
        await self.check_marker(self.place_of(_organization(destination.directory)))
        source = self._placer.upload_file(upload.id)
        measured = await self._hash(lambda: self._placer.measure(source, upload.size))
        path = collection_dir.joinpath(*PurePosixPath(destination.rel_path).parts)
        placement = _Placement(uploads, actor, upload, path, collection_dir)
        return await self._hold(path, lambda: self._settle(placement, measured))

    async def _settle(self, placement: _Placement, measured: Measured | None) -> Upload:
        if measured is None:
            return await self._replay(placement)
        upload, path = placement.upload, placement.path
        source, info = self._placer.upload_file(upload.id), self._placer.info_file(upload.id)
        try:
            linked = await self._call(
                lambda: self._placer.link(source, info, path, placement.collection_dir, upload.id)
            )
        except CollectionDirectoryMissing as error:
            await placement.uploads.fail(upload.id, error.code, error.message)
            raise
        except SourceGone:
            return await self._replay(placement)
        try:
            placed = await placement.uploads.receipt(
                upload.id, measured.size, measured.sha256, measured.inode
            )
        except (UploadNotFound, UploadStateConflict):
            await self._call(lambda: self._placer.undo(path, measured.inode, linked))
            raise
        await self._call(lambda: self._placer.drop_backup(path, upload.id))
        return placed

    async def _replay(self, placement: _Placement) -> Upload:
        upload, path = placement.upload, placement.path
        current = await placement.uploads.get(placement.actor, upload.id)
        if current.state in {UploadState.PLACED, UploadState.COMMITTED}:
            return current
        if current.state is UploadState.PENDING:
            measured = await self._hash(lambda: self._placer.measure_destination(path, upload.size))
            if measured is not None:
                placed = await placement.uploads.receipt(
                    upload.id, measured.size, measured.sha256, measured.inode
                )
                await self._call(lambda: self._placer.drop_backup(path, upload.id))
                return placed
        raise StorageError(
            f"the file of upload {upload.id} is gone, and {path} does not hold its bytes",
            {"path": str(path), "upload": str(upload.id)},
        )

    async def _hold[T](self, path: Path, start: Callable[[], Awaitable[T]]) -> T:
        """Await the work ``start`` begins while holding the lock of ``path``.

        The lock stays held until the work ends, also when the caller is cancelled; an error
        the work then raises goes to the log.
        """
        async with self._locks.hold(path):
            work = asyncio.ensure_future(start())
            try:
                return await asyncio.shield(work)
            except asyncio.CancelledError:
                await _settled(work)
                if not work.cancelled() and (error := work.exception()) is not None:
                    _log.error("disk.cancelled_action_failed", path=str(path), error=repr(error))
                raise

    def _submit[T](self, action: Callable[[], T]) -> asyncio.Future[T]:
        return asyncio.get_running_loop().run_in_executor(self._pool, action)

    async def _call[T](self, action: Callable[[], T]) -> T:
        return await self._submit(action)

    async def _hash[T](self, action: Callable[[], T]) -> T:
        return await asyncio.get_running_loop().run_in_executor(self._hash_pool, action)

    def _open(self) -> None:
        self._require_lake()
        try:
            self._storage.make_directory(self.upload_dir, UPLOAD_DIR_MODE)
        except StorageError as error:
            raise LakeUnavailable(
                f"the API cannot write the lake {self._lake_path}: {error.message}",
                {"lake_path": str(self._lake_path), **error.context},
            ) from error

    def _writable(self) -> bool:
        probe = self.upload_dir / f"{MARKER_FILE}-ready-{uuid.uuid4().hex}"
        try:
            if not self._storage.is_directory(self.upload_dir):
                return False
            self._storage.write_bytes(probe, b"")
            self._storage.remove_file(probe)
        except (StorageError, OSError):
            return False
        return True

    def _check_marker(self, place: OrganizationPlace) -> None:
        organization = place.name if place.own_marker else None
        try:
            verify_marker(self._storage, place.marker_directory, self._instance_id, organization)
        except StorageError as error:
            raise LakeUnavailable(error.message, error.context) from error

    def _resolve(self, relative: str) -> Path:
        place = self.place_of(_organization(relative))
        try:
            path = place.resolve(relative)
        except StorageError as error:
            raise OutsideLake(error.message, error.context) from error
        context = {"path": relative, "lake_path": str(self._lake_path)}
        if not path.is_relative_to(self._lake_path):
            raise OutsideLake(f"{path} is outside the lake {self._lake_path}", context)
        self._require_lake()
        existing = path
        while not self._storage.exists(existing):
            existing = existing.parent
        if self._storage.device(existing) != self._storage.device(self._lake_path):
            raise OutsideLake(
                f"{existing} is on a different filesystem than the lake {self._lake_path}",
                context,
            )
        return path

    def _require_lake(self) -> None:
        if not self._storage.is_directory(self._lake_path):
            raise LakeUnavailable(
                f"the lake {self._lake_path} is not a directory",
                {"lake_path": str(self._lake_path)},
            )


@dataclass(frozen=True, slots=True)
class _Placement:
    """One attempt to place ``upload`` at the absolute ``path`` in ``collection_dir``."""

    uploads: Uploads
    actor: Actor
    upload: Upload
    path: Path
    collection_dir: Path


def _organization(relative: str) -> str:
    return relative.split("/")[0]


async def _settled[T](work: asyncio.Future[T]) -> None:
    # A second cancellation must not end the wait either: the work still runs in its thread.
    while not work.done():
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.wait([work])
