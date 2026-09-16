"""Authorized revision discovery and downloads."""

from __future__ import annotations

from typing import TYPE_CHECKING

from huron.core.security.rules import ScopeType

if TYPE_CHECKING:
    import os
    from pathlib import Path
    from uuid import UUID

    from huron.core.raw.types import PayloadFile, RevisionRecord
    from huron.core.security import AccessPolicy

    from .reader import RevisionService


class RevisionReadService:
    """Authorize discovery and downloads against authoritative revision identities."""

    def __init__(self, operations: RevisionService, access: AccessPolicy) -> None:
        """Bind the revision reader to an authenticated actor.

        Args:
            operations: Revision lookup and storage reads.
            access: The caller's current authorization policy.
        """
        self._operations = operations
        self._access = access

    async def revision(self, revision_id: UUID) -> RevisionRecord:
        """Discover a revision through its dataset's current visibility.

        Args:
            revision_id: The revision identifier.

        Returns:
            Its authoritative catalog record.
        """
        return await self._operations.revision(revision_id, await self._access.visibility())

    async def _readable(self, revision_id: UUID) -> RevisionRecord:
        """Resolve a revision and require current Raw read permission.

        Args:
            revision_id: The revision identifier.

        Returns:
            The authorized record.
        """
        record = await self.revision(revision_id)
        await self._access.require("data.read", ScopeType.DATASET, record.dataset_id, layer="raw")
        return record

    async def manifest_file(self, record: RevisionRecord) -> tuple[Path, os.stat_result]:
        """Read a manifest using a freshly resolved, authorized record.

        Args:
            record: The requested revision; caller-supplied paths are never trusted.

        Returns:
            Its manifest location and stat.
        """
        return await self._operations.manifest_file(await self._readable(record.id))

    async def payload_file(self, record: RevisionRecord, path: str) -> PayloadFile:
        """Read a listed payload using a freshly resolved, authorized record.

        Args:
            record: The requested revision; caller-supplied paths are never trusted.
            path: A manifest-relative file path.

        Returns:
            The authorized file's descriptor.
        """
        return await self._operations.payload_file(await self._readable(record.id), path)
