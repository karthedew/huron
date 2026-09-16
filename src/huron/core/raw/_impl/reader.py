"""Reading a committed revision, its stored manifest and its payload files.

:class:`RevisionService` is the read side of a committed raw revision: it
resolves authoritative records and hands
back wherever its documents live on disk together with a freshly taken
``stat`` for a transport to stream without touching storage itself.
Every call consults storage fresh - nothing is cached between requests - and
every filesystem operation runs through :func:`asyncer.asyncify`, off the
event loop.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from asyncer import asyncify

from huron.core.foundation.errors import ResourceNotFound
from huron.core.raw.documents import decode_manifest
from huron.core.raw.manifest import validate_manifest_path
from huron.core.raw.types import PayloadFile, RevisionRecord

if TYPE_CHECKING:
    import os
    from uuid import UUID

    from huron.core.raw.ports import RawStore, RevisionStore
    from huron.core.security.rules import Visibility


__all__ = ["PayloadFile", "RevisionService"]


class RevisionService:
    """The read side of a committed revision: its record, manifest and payload files.

    Consults storage on every call and caches nothing between requests, so
    a revoked authorization or a change on disk is visible on the very
    next one.
    """

    def __init__(self, raw_store: RawStore, hierarchy: RevisionStore) -> None:
        """Wire the service over the raw store and hierarchy store it reads.

        Args:
            raw_store: The store holding every published revision's
                documents.
            hierarchy: Durable storage for revision and dataset records.
        """
        self._raw_store = raw_store
        self._hierarchy = hierarchy

    async def revision(self, revision_id: UUID, visibility: Visibility) -> RevisionRecord:
        """Return one committed revision, if its dataset is visible to the caller.

        An id that names no revision, and one whose dataset visibility
        does not admit, are indistinguishable to the caller: both answer
        through the hierarchy store's own not-found error, before any
        binding is ever read.

        Args:
            revision_id: The revision to read.
            visibility: The caller's discovery rights.

        Returns:
            The revision's record.
        """
        record = await self._hierarchy.revision(revision_id)
        await self._hierarchy.datasets.get(record.dataset_id, visibility)
        return record

    async def manifest_file(self, record: RevisionRecord) -> tuple[Path, os.stat_result]:
        """Locate and stat the revision's stored manifest document.

        Args:
            record: The revision whose manifest is being read.

        Returns:
            The manifest's location and its freshly read ``stat`` result.
        """
        location = Path(record.revision_path) / "manifest.json"
        stat = await asyncify(self._raw_store.stat_document)(PurePosixPath(location))
        return location, stat

    async def payload_file(self, record: RevisionRecord, path: str) -> PayloadFile:
        """Locate, validate and stat one payload file the manifest lists.

        ``path`` is checked against every storage-layout rule before
        anything is read from disk, so a request naming a path outside the
        payload directory, or otherwise breaking one of the manifest's own
        rules, never touches storage; the location served is always
        composed from the manifest entry the path resolved to, never from
        the request string itself.

        Args:
            record: The revision the file belongs to.
            path: The file's manifest path, exactly as declared.

        Returns:
            The resolved entry, its location and its freshly read ``stat``
            result.

        Raises:
            ResourceNotFound: If the stored manifest lists no such path.
            RuntimeError: If the stored manifest's identity does not match
                the revision's recorded digest, or the file's size on disk
                does not match what the manifest declares - storage and
                the catalog disagree either way.
        """
        validate_manifest_path(path)
        payload = await asyncify(self._raw_store.read_document)(
            PurePosixPath(record.revision_path) / "manifest.json"
        )
        manifest = decode_manifest(payload)
        if manifest.sha256 != record.manifest_sha256:
            raise RuntimeError(
                f"stored manifest {manifest.sha256} does not match the revision's "
                f"recorded identity {record.manifest_sha256}"
            )
        entry = next((candidate for candidate in manifest.files if candidate.path == path), None)
        if entry is None:
            raise ResourceNotFound(f"no such file in revision: {path}")
        location = Path(record.revision_path) / entry.path
        stat = await asyncify(self._raw_store.stat_document)(PurePosixPath(location))
        if stat.st_size != entry.size:
            raise RuntimeError(
                f"{location} is {stat.st_size} bytes on disk, the manifest declares {entry.size}"
            )
        return PayloadFile(entry=entry, location=location, stat=stat)
