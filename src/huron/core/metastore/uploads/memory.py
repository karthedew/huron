"""In-memory upload attempts and stored objects."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from huron.core.lake.errors import NameTaken
from huron.core.lake.uploads.models import AttemptState, ObjectState

if TYPE_CHECKING:
    import uuid
    from collections.abc import Collection, Iterable, Mapping, Sequence
    from datetime import datetime

    from huron.core.lake.uploads.models import StoredObject, UploadAttempt
    from huron.core.metastore.memory import MemoryState

__all__ = ["MemoryAttempts", "MemoryObjects"]


class MemoryAttempts:
    """Upload attempts and their issued IDs in a :class:`MemoryState`.

    Transactions are serialized, so a lock is a read.
    """

    def __init__(self, state: MemoryState) -> None:
        self._state = state

    async def insert_or_lock(self, attempt: UploadAttempt) -> UploadAttempt:
        """Store the attempt unless its key has one, then return the attempt of the key."""
        found = await self.get(attempt.subject, attempt.attempt_id)
        if found is not None:
            return found
        if attempt.id in self._state.attempts or any(
            upload_id in self._state.issued for upload_id in attempt.upload_ids
        ):
            raise _taken(str(attempt.attempt_id))
        for upload_id in attempt.upload_ids:
            self._state.issued[upload_id] = (attempt.id, attempt.created_at)
        stored = replace(attempt, upload_ids=self._issued_ids(attempt.upload_ids))
        self._state.attempts[attempt.id] = stored
        return stored

    async def get(self, subject: str, attempt_id: uuid.UUID) -> UploadAttempt | None:
        """The attempt of ``subject`` with ``attempt_id``."""
        return next(
            (
                attempt
                for attempt in self._state.attempts.values()
                if (attempt.subject, attempt.attempt_id) == (subject, attempt_id)
            ),
            None,
        )

    async def find_uploads(
        self, upload_ids: Collection[uuid.UUID]
    ) -> Mapping[uuid.UUID, UploadAttempt]:
        """The attempt of each issued ID of ``upload_ids``."""
        return await self.lock_uploads(upload_ids)

    async def lock_uploads(
        self, upload_ids: Collection[uuid.UUID]
    ) -> Mapping[uuid.UUID, UploadAttempt]:
        """The attempt of each issued ID of ``upload_ids``."""
        return {
            upload_id: self._state.attempts[self._state.issued[upload_id][0]]
            for upload_id in upload_ids
            if upload_id in self._state.issued
        }

    async def lock_idle(self, before: datetime, limit: int) -> Sequence[UploadAttempt]:
        """The idle attempts, the oldest activity first."""
        idle = sorted(
            (
                attempt
                for attempt in self._state.attempts.values()
                if _idle(attempt) and attempt.active_at < before
            ),
            key=lambda attempt: (attempt.active_at, attempt.id),
        )
        return idle[:limit]

    async def staged_bytes(self) -> int:
        """The total declared size of the attempts that wait for a commit."""
        return sum(
            attempt.size for attempt in self._state.attempts.values() if attempt.state in _STAGED
        )

    async def spent(self, upload_ids: Collection[uuid.UUID]) -> set[uuid.UUID]:
        """The issued IDs of ``upload_ids`` that are not current or whose attempt is final."""
        return {
            upload_id
            for upload_id in upload_ids
            if upload_id in self._state.issued and _spent(self._state, upload_id)
        }

    async def issue(self, attempt_id: uuid.UUID, upload_id: uuid.UUID, issued_at: datetime) -> None:
        """Store ``upload_id`` for the attempt and make it the current ID."""
        stored = self._state.attempts.get(attempt_id)
        if stored is None:
            return
        if upload_id in self._state.issued:
            raise _taken(str(upload_id))
        self._state.issued[upload_id] = (attempt_id, issued_at)
        self._state.attempts[attempt_id] = replace(
            stored,
            current_upload_id=upload_id,
            upload_ids=self._issued_ids([*stored.upload_ids, upload_id]),
        )

    async def update(self, attempt: UploadAttempt) -> None:
        """Replace the state, the activity time, the commit request and the failure."""
        stored = self._state.attempts.get(attempt.id)
        if stored is not None:
            self._state.attempts[attempt.id] = replace(
                stored,
                state=attempt.state,
                active_at=attempt.active_at,
                commit_request_id=attempt.commit_request_id,
                failure=attempt.failure,
            )

    def _issued_ids(self, upload_ids: Iterable[uuid.UUID]) -> tuple[uuid.UUID, ...]:
        """``upload_ids`` in the order of their time of issue, then of the IDs."""
        return tuple(
            sorted(upload_ids, key=lambda upload_id: (self._state.issued[upload_id][1], upload_id))
        )


class MemoryObjects:
    """Stored objects in a :class:`MemoryState`.

    Transactions are serialized, so a lock is a read.
    """

    def __init__(self, state: MemoryState) -> None:
        self._state = state

    async def insert_or_lock(self, stored: StoredObject) -> StoredObject:
        """Store the object unless its upload ID has one, then return that object."""
        found = (await self.lock_uploads([stored.upload_id])).get(stored.upload_id)
        if found is not None:
            return found
        if stored.id in self._state.objects or any(
            other.path == stored.path for other in self._state.objects.values()
        ):
            raise _taken(stored.path)
        self._state.objects[stored.id] = stored
        return stored

    async def lock_uploads(
        self, upload_ids: Collection[uuid.UUID]
    ) -> Mapping[uuid.UUID, StoredObject]:
        """The objects of ``upload_ids``, by upload ID."""
        wanted = set(upload_ids)
        found = (stored for stored in self._state.objects.values() if stored.upload_id in wanted)
        return {stored.upload_id: stored for stored in sorted(found, key=lambda o: o.upload_id)}

    async def unreferenced(self, after: uuid.UUID | None, limit: int) -> Sequence[StoredObject]:
        """The objects that no row needs, in the order of their IDs, after ``after``."""
        named = {record.object_id for record in self._state.files.values()}
        pending = {
            entry.upload_id
            for (owner, _), entry in self._state.commit_entries.items()
            if self._state.commit_requests[owner].pending
        }
        found = sorted(
            (
                stored
                for stored in self._state.objects.values()
                if (after is None or stored.id > after)
                and stored.id not in named
                and stored.upload_id not in pending
                and self._removable(stored)
            ),
            key=lambda stored: stored.id,
        )
        return found[:limit]

    async def update(self, stored: StoredObject) -> None:
        """Replace the state, the size, the SHA-256, the inode and the seal time."""
        found = self._state.objects.get(stored.id)
        if found is not None:
            self._state.objects[stored.id] = replace(
                found,
                state=stored.state,
                size=stored.size,
                sha256=stored.sha256,
                inode=stored.inode,
                sealed_at=stored.sealed_at,
            )

    def _removable(self, stored: StoredObject) -> bool:
        """Whether ``stored`` is not removed and its upload ID is spent."""
        return stored.state is not ObjectState.REMOVED and _spent(self._state, stored.upload_id)


_STAGED = frozenset({AttemptState.RECEIVING, AttemptState.SEALING, AttemptState.READY})
_UNSEALED = frozenset({AttemptState.RECEIVING, AttemptState.SEALING})
_FINAL = frozenset(
    {AttemptState.CONSUMED, AttemptState.FAILED, AttemptState.CANCELLED, AttemptState.EXPIRED}
)


def _idle(attempt: UploadAttempt) -> bool:
    """Whether ``attempt`` is receiving or sealing, or ready and held by no commit request."""
    return attempt.state in _UNSEALED or (
        attempt.state is AttemptState.READY and attempt.commit_request_id is None
    )


def _spent(state: MemoryState, upload_id: uuid.UUID) -> bool:
    """Whether the issued ``upload_id`` is not current, or its attempt is final."""
    attempt = state.attempts[state.issued[upload_id][0]]
    return attempt.current_upload_id != upload_id or attempt.state in _FINAL


def _taken(name: str) -> NameTaken:
    return NameTaken(f"{name!r} is in use", {"name": name})
