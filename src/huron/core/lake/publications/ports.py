"""Persistence port for commit requests and their entries."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence
    from datetime import datetime

    from huron.core.lake.publications.models import CommitEntry, CommitOutcome

__all__ = ["CommitRequestStore"]


class CommitRequestStore(Protocol):
    """Reads and writes commit requests and the entries that publish them.

    A transaction locks a commit request row after the collection row, and before the upload
    attempt rows and the object rows.
    """

    async def insert_or_lock(self, outcome: CommitOutcome) -> CommitOutcome:
        """Store ``outcome`` when its key is free, then return the request of the key, locked.

        The key is the subject and the ``request_id``. When a request with the key exists, it is
        returned and ``outcome`` is not stored. Two transactions that store one key together give
        one request: the second waits for the first and gets the first's request.

        Raises ``NameTaken`` when another request has the row ID of ``outcome``.
        """
        ...

    async def get(self, subject: str, request_id: uuid.UUID) -> CommitOutcome | None:
        """The request of ``subject`` with ``request_id``."""
        ...

    async def find(self, row_id: uuid.UUID) -> CommitOutcome | None:
        """The request with the row ID ``row_id``, read without a row lock."""
        ...

    async def lock(self, row_id: uuid.UUID) -> CommitOutcome | None:
        """The request with the row ID ``row_id``, locked until the transaction ends."""
        ...

    async def pending(self) -> Sequence[CommitOutcome]:
        """Every ``accepted`` and ``blocked`` request, the oldest first."""
        ...

    async def update(self, outcome: CommitOutcome) -> None:
        """Replace the state, the result, the refusal and the update time of a request.

        The result is the version, the file count and the commit. Nothing happens when no
        request has the row ID of ``outcome``.
        """
        ...

    async def insert_entries(self, row_id: uuid.UUID, entries: Sequence[CommitEntry]) -> None:
        """Store the entries of the request with the row ID ``row_id``.

        Raises ``NameTaken`` when the request has an entry with the ordinal of one of ``entries``.
        """
        ...

    async def entries(self, row_id: uuid.UUID) -> Sequence[CommitEntry]:
        """The entries of the request with the row ID ``row_id``, in the order of their ordinals."""
        ...

    async def mark_done(self, row_id: uuid.UUID, ordinal: int, done_at: datetime) -> None:
        """Mark an entry of the request with the row ID ``row_id`` done at ``done_at``.

        An entry that is done already keeps its time. Nothing happens when the request has no
        entry with ``ordinal``.
        """
        ...
