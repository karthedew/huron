"""The free-space limit of a new upload attempt.

Three limits stop an upload: ``max_upload_bytes`` for one file, ``max_staged_bytes`` for all
staged uploads, and ``min_free_bytes`` for the free space. ``Attempts.begin`` applies the first
two. This module applies the third one, which only the filesystems know. The caller checks it
before ``begin``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from huron.core.lake.uploads.errors import CapacityExceeded

if TYPE_CHECKING:
    from huron.applications.api.disk.lake import LakeDisk, Located
    from huron.core.storage import FreeSpace, Storage

__all__ = ["Capacity"]


class Capacity:
    """Refuses an upload that would leave less than ``min_free_bytes`` free on a filesystem."""

    def __init__(self, disk: LakeDisk, storage: Storage, min_free_bytes: int) -> None:
        self._disk = disk
        self._storage = storage
        self._min_free_bytes = min_free_bytes

    async def admit(self, organization: str, size: int) -> None:
        """Refuse an upload of ``size`` bytes to ``organization`` that does not fit now.

        tusd's file lands on the filesystem of ``.tus-uploads``, and the sealed copy on the
        filesystem of the organization's object area. The object area lies in the organization
        directory and on its mount, so the check reads the free space of that directory. When
        the two places are on one filesystem, that filesystem must keep ``min_free_bytes`` free
        after ``2 × size`` bytes. When they are on two filesystems, each one must keep
        ``min_free_bytes`` free after ``size`` bytes. Raises ``CAPACITY_EXCEEDED`` when a
        filesystem does not, and ``LAKE_UNAVAILABLE`` when a marker refuses the read.
        """
        uploads = await self._free(self._disk.in_uploads())
        objects = await self._free(self._disk.locate(organization))
        if uploads.filesystem == objects.filesystem:
            self._fits(objects, 2 * size, doubled=True)
            return
        self._fits(uploads, size)
        self._fits(objects, size)

    async def _free(self, located: Located) -> FreeSpace:
        return await self._disk.work(located, lambda: self._storage.free_space(located.location))

    def _fits(self, space: FreeSpace, requested: int, *, doubled: bool = False) -> None:
        if space.free - requested < self._min_free_bytes:
            available = max(0, space.free - self._min_free_bytes)
            raise CapacityExceeded("min_free_bytes", requested, available, doubled=doubled)
