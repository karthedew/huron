"""Placement of finished uploads: measure, then link under the lock of the destination."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from huron.core.lake.uploads.errors import UploadNotFound, UploadStateConflict
from huron.core.lake.uploads.models import UploadState
from huron.core.storage import CollectionDirectoryMissing, SourceGone, StorageError, SymlinkInLake

if TYPE_CHECKING:
    from huron.applications.api.disk.lake import LakeDisk, Run
    from huron.core.lake.uploads.models import Destination, Upload
    from huron.core.lake.uploads.operations import Uploads
    from huron.core.security.rbac import Actor
    from huron.core.storage import LakePath, Measured, Placer

__all__ = ["Placements"]


class Placements:
    """Places finished uploads on the lake with ``placer``, through ``disk``."""

    def __init__(self, disk: LakeDisk, placer: Placer) -> None:
        self._disk = disk
        self._placer = placer

    async def place(
        self, uploads: Uploads, actor: Actor, upload: Upload, destination: Destination
    ) -> Upload:
        """Place the actor's pending ``upload`` at ``destination`` and record its receipt.

        The file goes to the names of ``destination.rel_path`` below the collection directory
        ``destination.directory``. The hash runs in the hash pool, outside every lock. The
        link, the removal of tusd's files and the receipt run under the lock of the
        destination, each disk step after the marker check. A file the placement replaces
        stays as a backup until the receipt is recorded. A receipt refused because the
        collection or the upload ended during the hash takes the placed file away again, puts
        a replaced file back, and raises the refusal. A symbolic link on the way, or at the
        upload's file, and a missing collection directory fail the upload. When the upload's
        file is gone, another attempt moved it: the upload's state, or the file at the
        destination, decides. Raises
        ``STORAGE_FAILED`` when neither proves the placement, and ``LAKE_UNAVAILABLE`` when the
        lake or its marker refuses the write.
        """
        collection = self._disk.locate(destination.directory)
        target = collection.joinpath(*destination.rel_path.split("/"))
        attempt = _Attempt(uploads, actor, upload, collection.location, target.location)
        try:
            measured = await self._disk.measure(
                lambda: self._placer.measure(upload.id, upload.size)
            )
        except SymlinkInLake as error:
            await uploads.fail(upload.id, error.code, error.message)
            raise
        return await self._disk.hold(target, lambda run: self._settle(run, attempt, measured))

    async def _settle(self, run: Run, attempt: _Attempt, measured: Measured | None) -> Upload:
        if measured is None:
            return await self._replay(run, attempt)
        upload, target = attempt.upload, attempt.target
        try:
            linked = await run(
                lambda: self._placer.link(upload.id, attempt.collection, target, measured.inode)
            )
        except (CollectionDirectoryMissing, SymlinkInLake) as error:
            await attempt.uploads.fail(upload.id, error.code, error.message)
            raise
        except SourceGone:
            return await self._replay(run, attempt)
        try:
            placed = await attempt.uploads.receipt(
                upload.id, measured.size, measured.sha256, measured.inode
            )
        except (UploadNotFound, UploadStateConflict):
            await run(lambda: self._placer.undo(target, measured.inode, linked))
            raise
        await run(lambda: self._placer.drop_backup(target, upload.id))
        return placed

    async def _replay(self, run: Run, attempt: _Attempt) -> Upload:
        upload, target = attempt.upload, attempt.target
        current = await attempt.uploads.get(attempt.actor, upload.id)
        if current.state in {UploadState.PLACED, UploadState.COMMITTED}:
            return current
        if current.state is UploadState.PENDING:
            measured = await self._disk.measure(
                lambda: self._placer.measure_destination(target, upload.size)
            )
            if measured is not None:
                placed = await attempt.uploads.receipt(
                    upload.id, measured.size, measured.sha256, measured.inode
                )
                await run(lambda: self._placer.drop_backup(target, upload.id))
                return placed
        raise StorageError(
            f"the file of upload {upload.id} is gone, and {target} does not hold its bytes",
            {"path": str(target), "upload": str(upload.id)},
        )


@dataclass(frozen=True, slots=True)
class _Attempt:
    """One attempt to place ``upload`` at ``target`` in the directory ``collection``."""

    uploads: Uploads
    actor: Actor
    upload: Upload
    collection: LakePath
    target: LakePath
