"""Persistence ports for files and commits."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import uuid
    from collections.abc import Collection, Sequence

    from huron.core.lake.files.models import Commit, FileRecord

__all__ = ["CommitStore", "FileStore"]


class FileStore(Protocol):
    """Reads and writes recorded files."""

    async def upsert_many(self, records: Sequence[FileRecord]) -> None:
        """Insert or replace records by ``(collection_id, rel_path_key)``."""
        ...

    async def delete_many(self, collection_id: uuid.UUID, keys: Collection[str]) -> None:
        """Remove the records with ``keys``."""
        ...

    async def existing(self, collection_id: uuid.UUID, keys: Collection[str]) -> set[str]:
        """Which of ``keys`` are recorded."""
        ...

    async def beneath(
        self, collection_id: uuid.UUID, prefixes: Collection[str], limit: int
    ) -> set[str]:
        """Up to ``limit`` recorded keys that start with one of ``prefixes``."""
        ...

    async def list(
        self, collection_id: uuid.UUID, after: str | None, limit: int
    ) -> Sequence[FileRecord]:
        """Records sorted by key after ``after``."""
        ...

    async def count(self, collection_id: uuid.UUID) -> int:
        """How many files are recorded."""
        ...


class CommitStore(Protocol):
    """Reads and writes commits."""

    async def insert(self, commit: Commit) -> None:
        """Store a commit."""
        ...

    async def list(
        self, collection_id: uuid.UUID, before: uuid.UUID | None, limit: int
    ) -> Sequence[Commit]:
        """Commits newest first, with ids below ``before``."""
        ...
