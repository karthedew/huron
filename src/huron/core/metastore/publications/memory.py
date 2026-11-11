"""In-memory commit requests and their entries."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from huron.core.lake.errors import NameTaken

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence
    from datetime import datetime

    from huron.core.lake.publications.models import CommitEntry, CommitOutcome
    from huron.core.metastore.memory import MemoryState

__all__ = ["MemoryCommitRequests"]


class MemoryCommitRequests:
    """Commit requests and their entries in a :class:`MemoryState`.

    Transactions are serialized, so a lock is a read.
    """

    def __init__(self, state: MemoryState) -> None:
        self._state = state

    async def insert_or_lock(self, outcome: CommitOutcome) -> CommitOutcome:
        """Store the request unless its key has one, then return the request of the key."""
        found = await self.get(outcome.subject, outcome.request_id)
        if found is not None:
            return found
        if outcome.id in self._state.commit_requests:
            raise _taken(str(outcome.request_id))
        self._state.commit_requests[outcome.id] = outcome
        return outcome

    async def get(self, subject: str, request_id: uuid.UUID) -> CommitOutcome | None:
        """The request of ``subject`` with ``request_id``."""
        return next(
            (
                outcome
                for outcome in self._state.commit_requests.values()
                if (outcome.subject, outcome.request_id) == (subject, request_id)
            ),
            None,
        )

    async def lock(self, row_id: uuid.UUID) -> CommitOutcome | None:
        """The request with ``row_id``."""
        return self._state.commit_requests.get(row_id)

    async def pending(self) -> Sequence[CommitOutcome]:
        """The accepted and blocked requests, the oldest first."""
        return sorted(
            (outcome for outcome in self._state.commit_requests.values() if outcome.pending),
            key=lambda outcome: (outcome.created_at, outcome.id),
        )

    async def update(self, outcome: CommitOutcome) -> None:
        """Replace the state, the result, the refusal and the update time."""
        stored = self._state.commit_requests.get(outcome.id)
        if stored is not None:
            self._state.commit_requests[outcome.id] = replace(
                stored,
                state=outcome.state,
                version=outcome.version,
                file_count=outcome.file_count,
                commit_id=outcome.commit_id,
                refusal=outcome.refusal,
                updated_at=outcome.updated_at,
            )

    async def insert_entries(self, row_id: uuid.UUID, entries: Sequence[CommitEntry]) -> None:
        """Store the entries of the request."""
        keys = [(row_id, entry.ordinal) for entry in entries]
        if any(key in self._state.commit_entries for key in keys) or len(set(keys)) < len(keys):
            raise _taken(str(row_id))
        for key, entry in zip(keys, entries, strict=True):
            self._state.commit_entries[key] = entry

    async def entries(self, row_id: uuid.UUID) -> Sequence[CommitEntry]:
        """The entries of the request in the order of their ordinals."""
        return sorted(
            (entry for (owner, _), entry in self._state.commit_entries.items() if owner == row_id),
            key=lambda entry: entry.ordinal,
        )

    async def mark_done(self, row_id: uuid.UUID, ordinal: int, done_at: datetime) -> None:
        """Mark the entry done unless it is done already."""
        entry = self._state.commit_entries.get((row_id, ordinal))
        if entry is not None and entry.done_at is None:
            self._state.commit_entries[(row_id, ordinal)] = replace(entry, done_at=done_at)


def _taken(name: str) -> NameTaken:
    return NameTaken(f"{name!r} is in use", {"name": name})
