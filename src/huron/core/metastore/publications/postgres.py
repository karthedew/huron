"""PostgreSQL commit requests and their entries."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from huron.core.lake.publications.models import (
    CommitEntry,
    CommitOutcome,
    CommitState,
    EntryAction,
    Refusal,
)
from huron.core.metastore.rows import columns, unique

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence
    from datetime import datetime

    import asyncpg

    from huron.core.metastore.rows import Db

__all__ = ["PostgresCommitRequests"]

_REQUEST_COLUMNS = (
    "id, subject, request_id, collection_id, body_digest, base_version, host, message, state,"
    " created_at, updated_at, version, file_count, commit_id, refusal"
)
_ENTRY_COLUMNS = "ordinal, action, rel_path, upload_id, done_at"


class PostgresCommitRequests:
    """Commit requests in ``huron.commit_requests``, their entries in ``huron.commit_entries``."""

    def __init__(self, connection: Db) -> None:
        self._db = connection

    async def insert_or_lock(self, outcome: CommitOutcome) -> CommitOutcome:
        """Store the request unless its key has one, then lock and read the request of the key."""
        await unique(
            lambda: self._db.execute(
                f"insert into huron.commit_requests ({_REQUEST_COLUMNS})"
                " values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)"
                " on conflict (subject, request_id) do nothing",
                *_request_row(outcome),
            ),
            str(outcome.request_id),
        )
        row = await self._db.fetchrow(
            f"select {_REQUEST_COLUMNS} from huron.commit_requests"
            " where subject = $1 and request_id = $2 for update",
            outcome.subject,
            outcome.request_id,
        )
        assert row is not None
        return _request(row)

    async def get(self, subject: str, request_id: uuid.UUID) -> CommitOutcome | None:
        """The request of ``subject`` with ``request_id``."""
        row = await self._db.fetchrow(
            f"select {_REQUEST_COLUMNS} from huron.commit_requests"
            " where subject = $1 and request_id = $2",
            subject,
            request_id,
        )
        return None if row is None else _request(row)

    async def find(self, row_id: uuid.UUID) -> CommitOutcome | None:
        """The request with ``row_id``, read without a row lock."""
        row = await self._db.fetchrow(
            f"select {_REQUEST_COLUMNS} from huron.commit_requests where id = $1", row_id
        )
        return None if row is None else _request(row)

    async def lock(self, row_id: uuid.UUID) -> CommitOutcome | None:
        """The request with ``row_id``, locked ``for update``."""
        row = await self._db.fetchrow(
            f"select {_REQUEST_COLUMNS} from huron.commit_requests where id = $1 for update",
            row_id,
        )
        return None if row is None else _request(row)

    async def pending(self) -> Sequence[CommitOutcome]:
        """The accepted and blocked requests, the oldest first."""
        rows = await self._db.fetch(
            f"select {_REQUEST_COLUMNS} from huron.commit_requests"
            " where state in ('accepted', 'blocked') order by created_at, id"
        )
        return [_request(row) for row in rows]

    async def update(self, outcome: CommitOutcome) -> None:
        """Replace the state, the result, the refusal and the update time."""
        o = outcome
        await self._db.execute(
            "update huron.commit_requests set state = $2, version = $3, file_count = $4,"
            " commit_id = $5, refusal = $6, updated_at = $7 where id = $1",
            o.id,
            str(o.state),
            o.version,
            o.file_count,
            o.commit_id,
            None if o.refusal is None else o.refusal.as_dict(),
            o.updated_at,
        )

    async def insert_entries(self, row_id: uuid.UUID, entries: Sequence[CommitEntry]) -> None:
        """Store the entries of the request in one statement."""
        if not entries:
            return
        await unique(
            lambda: self._db.execute(
                f"insert into huron.commit_entries (commit_request_id, {_ENTRY_COLUMNS})"
                " select $1, * from unnest($2::integer[], $3::text[], $4::text[], $5::uuid[],"
                " $6::timestamptz[])",
                row_id,
                *columns([_entry_row(entry) for entry in entries]),
            ),
            str(row_id),
        )

    async def entries(self, row_id: uuid.UUID) -> Sequence[CommitEntry]:
        """The entries of the request in the order of their ordinals."""
        rows = await self._db.fetch(
            f"select {_ENTRY_COLUMNS} from huron.commit_entries where commit_request_id = $1"
            " order by ordinal",
            row_id,
        )
        return [_entry(row) for row in rows]

    async def mark_done(self, row_id: uuid.UUID, ordinal: int, done_at: datetime) -> None:
        """Mark the entry done unless it is done already."""
        await self._db.execute(
            "update huron.commit_entries set done_at = $3"
            " where commit_request_id = $1 and ordinal = $2 and done_at is null",
            row_id,
            ordinal,
            done_at,
        )


def _request_row(outcome: CommitOutcome) -> tuple[Any, ...]:
    """The values of ``outcome`` in the order of ``_REQUEST_COLUMNS``."""
    o = outcome
    return (
        o.id,
        o.subject,
        o.request_id,
        o.collection_id,
        o.body_digest,
        o.base_version,
        o.host,
        o.message,
        str(o.state),
        o.created_at,
        o.updated_at,
        o.version,
        o.file_count,
        o.commit_id,
        None if o.refusal is None else o.refusal.as_dict(),
    )


def _request(row: asyncpg.Record) -> CommitOutcome:
    values = dict(row)
    refusal = values.pop("refusal")
    values["state"] = CommitState(values["state"])
    return CommitOutcome(**values, refusal=None if refusal is None else Refusal(**refusal))


def _entry_row(entry: CommitEntry) -> tuple[Any, ...]:
    """The values of ``entry`` in the order of ``_ENTRY_COLUMNS``."""
    return (entry.ordinal, str(entry.action), entry.rel_path, entry.upload_id, entry.done_at)


def _entry(row: asyncpg.Record) -> CommitEntry:
    values = dict(row)
    values["action"] = EntryAction(values["action"])
    return CommitEntry(**values)
