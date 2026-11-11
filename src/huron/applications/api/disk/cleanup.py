"""Cleanup of the lake: the tusd files and the objects that no row needs any more.

A run marks the lapsed attempts ``expired``, then removes:

- the object of each upload ID whose attempt ended or was consumed, or that is not current,
  when no file row and no pending request names the object;
- the tusd files (data and ``.info``) of each upload ID that is not current or whose attempt
  ended or was consumed.

The database decides each removal by object ID or by upload ID (``Leftovers``). The run reads
the names in ``.tus-uploads`` only to learn which upload IDs still have files there. It never
removes a file because of its age or the form of its name, and it never touches an upload whose
seal task runs. A failed removal is logged, and the next run tries it again.
"""

from __future__ import annotations

from functools import partial
from itertools import batched
from typing import TYPE_CHECKING

import structlog

from huron.core.storage import StorageError

if TYPE_CHECKING:
    import uuid
    from collections.abc import Callable

    from huron.applications.api.disk.lake import LakeDisk, Located
    from huron.applications.api.disk.sealing import Sealing
    from huron.core.lake.uploads.attempts import Attempts
    from huron.core.lake.uploads.leftovers import Leftovers
    from huron.core.lake.uploads.models import StoredObject
    from huron.core.storage import Sealer, Storage

__all__ = ["Cleanup"]

#: How many rows one read of a run gets.
_PAGE = 500

_log = structlog.get_logger(__name__)


class Cleanup:
    """Removes the leftovers of uploads from the lake of ``disk``."""

    def __init__(
        self,
        disk: LakeDisk,
        storage: Storage,
        attempts: Attempts,
        leftovers: Leftovers,
        sealing: Sealing,
        sealer: Sealer,
    ) -> None:
        self._disk = disk
        self._storage = storage
        self._attempts = attempts
        self._leftovers = leftovers
        self._sealing = sealing
        self._sealer = sealer

    async def run(self) -> None:
        """Expire the lapsed attempts, then remove the objects and the tusd files to remove."""
        while len(await self._attempts.expire(_PAGE)) == _PAGE:
            continue
        await self._remove_objects()
        await self._remove_uploads()

    async def _remove_objects(self) -> None:
        after: uuid.UUID | None = None
        while page := await self._leftovers.unreferenced(after, _PAGE):
            for stored in page:
                if not self._sealing.running(stored.upload_id):
                    await self._remove_object(stored)
            after = page[-1].id

    async def _remove_object(self, stored: StoredObject) -> None:
        """Remove the file of ``stored``, then record that it is gone.

        A sealed object's file is removed only while it has the object's inode.
        """
        located = self._disk.locate(stored.path)
        remove = partial(self._storage.remove_file, located.location, inode=stored.inode)
        if await self._removed(located, remove):
            await self._leftovers.removed(stored)

    async def _remove_uploads(self) -> None:
        found = await self._disk.work(self._disk.in_uploads(), self._sealer.upload_ids)
        for chunk in batched(sorted(found), _PAGE):
            for upload_id in sorted(await self._leftovers.spent(chunk)):
                if not self._sealing.running(upload_id):
                    located = self._disk.in_uploads(str(upload_id))
                    await self._removed(located, partial(self._sealer.remove_upload, upload_id))

    async def _removed(self, located: Located, remove: Callable[[], object]) -> bool:
        """Run ``remove`` on ``located``; ``False`` after a storage error, which is logged."""
        try:
            await self._disk.work(located, remove)
        except StorageError as error:
            _log.warning(
                "cleanup.failed", path=str(located.location), code=error.code, error=error.message
            )
            return False
        return True
