"""In-memory files and commits."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import uuid
    from collections.abc import Collection, Sequence

    from huron.core.lake.files.models import Commit, FileRecord
    from huron.core.metastore.memory import MemoryState

__all__ = ["MemoryCommits", "MemoryFiles"]


class MemoryFiles:
    """Recorded files in a :class:`MemoryState`."""

    def __init__(self, state: MemoryState) -> None:
        self._state = state

    async def upsert_many(self, records: Sequence[FileRecord]) -> None:
        """Insert or replace records."""
        for record in records:
            self._state.files[(record.collection_id, record.rel_path_key)] = record

    async def delete_many(self, collection_id: uuid.UUID, keys: Collection[str]) -> None:
        """Remove records."""
        for key in keys:
            self._state.files.pop((collection_id, key), None)

    async def existing(self, collection_id: uuid.UUID, keys: Collection[str]) -> set[str]:
        """Which keys are recorded."""
        return {key for key in keys if (collection_id, key) in self._state.files}

    async def beneath(
        self, collection_id: uuid.UUID, prefixes: Collection[str], limit: int
    ) -> set[str]:
        """Recorded keys under any of ``prefixes``."""
        found = sorted(
            key
            for owner, key in self._state.files
            if owner == collection_id and any(key.startswith(p) for p in prefixes)
        )
        return set(found[:limit])

    async def list(
        self, collection_id: uuid.UUID, after: str | None, limit: int
    ) -> Sequence[FileRecord]:
        """Records sorted by key."""
        rows = sorted(
            (
                record
                for (owner, key), record in self._state.files.items()
                if owner == collection_id and (after is None or key > after)
            ),
            key=lambda record: record.rel_path_key,
        )
        return rows[:limit]

    async def count(self, collection_id: uuid.UUID) -> int:
        """How many files are recorded."""
        return sum(1 for owner, _ in self._state.files if owner == collection_id)


class MemoryCommits:
    """Commits in a :class:`MemoryState`."""

    def __init__(self, state: MemoryState) -> None:
        self._state = state

    async def insert(self, commit: Commit) -> None:
        """Store a commit."""
        self._state.commits[commit.id] = commit

    async def list(
        self, collection_id: uuid.UUID, before: uuid.UUID | None, limit: int
    ) -> Sequence[Commit]:
        """Commits newest first."""
        rows = sorted(
            (
                commit
                for commit in self._state.commits.values()
                if commit.collection_id == collection_id and (before is None or commit.id < before)
            ),
            key=lambda commit: commit.id,
            reverse=True,
        )
        return rows[:limit]
