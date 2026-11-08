"""The share group of a catalog directory, set on the lake after the catalog's rows."""

from __future__ import annotations

from typing import TYPE_CHECKING

from huron.core.storage import SHARE_GROUP_PENDING, GroupOutcome, ShareWarning

if TYPE_CHECKING:
    from huron.applications.api.disk.lake import LakeDisk
    from huron.core.storage import Storage

__all__ = ["ShareGroups"]


class ShareGroups:
    """Gives catalog directories their share group through ``disk``.

    ``service_gid`` is the service group, the process's primary group, which a catalog
    without a share group carries.
    """

    def __init__(self, disk: LakeDisk, storage: Storage, service_gid: int) -> None:
        self._disk = disk
        self._storage = storage
        self._service_gid = service_gid

    async def set_share_group(self, catalog_path: str, group: str | None) -> ShareWarning | None:
        """Try to give the catalog directory its share group, or the service group for ``None``.

        ``None`` when the directory has the group; otherwise the ``SHARE_GROUP_PENDING``
        warning for the storage administrator, which names the service group by its number.
        """
        located = self._disk.locate(catalog_path)
        target = self._service_gid if group is None else group
        result = await self._disk.work(
            located, lambda: self._storage.set_group(located.location, target)
        )
        if result.outcome is not GroupOutcome.PENDING:
            return None
        return ShareWarning(SHARE_GROUP_PENDING, f"{target}", result.reason or "")
