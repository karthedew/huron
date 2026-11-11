"""PostgreSQL upload attempts and stored objects."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from huron.core.lake.uploads.models import (
    AttemptState,
    Failure,
    ObjectState,
    StoredObject,
    UploadAttempt,
)
from huron.core.metastore.rows import signed_inode, unique, unsigned_inode

if TYPE_CHECKING:
    import uuid
    from collections.abc import Collection, Mapping, Sequence
    from datetime import datetime

    import asyncpg

    from huron.core.metastore.rows import Db

__all__ = ["PostgresAttempts", "PostgresObjects"]

_ATTEMPT_COLUMNS = (
    "id, subject, attempt_id, collection_id, rel_path, size, state, current_upload_id,"
    " created_at, active_at, commit_request_id, failure"
)
_ATTEMPT_SELECT = (
    "select s.id, s.subject, s.attempt_id, s.collection_id, s.rel_path, s.size, s.state,"
    " s.current_upload_id, s.created_at, s.active_at, s.commit_request_id, s.failure,"
    " array(select i.upload_id from huron.staged_upload_ids i where i.staged_upload_id = s.id"
    " order by i.issued_at, i.upload_id) as upload_ids"
    " from huron.staged_uploads s"
)
_OBJECT_COLUMNS = "id, upload_id, path, state, created_at, size, sha256, inode, sealed_at"
#: An issued ID ``i`` of the attempt ``s`` whose tusd files and object no row needs.
_SPENT = (
    "(i.upload_id <> s.current_upload_id"
    " or s.state in ('consumed', 'failed', 'cancelled', 'expired'))"
)


class PostgresAttempts:
    """Upload attempts in ``huron.staged_uploads`` and their issued IDs in
    ``huron.staged_upload_ids``.

    A lock and the read of the locked rows are two statements: a read in the statement that
    waited for a lock would not see the upload IDs that the other transaction issued.
    """

    def __init__(self, connection: Db) -> None:
        self._db = connection

    async def insert_or_lock(self, attempt: UploadAttempt) -> UploadAttempt:
        """Store the attempt unless its key has one, then lock and read the attempt of the key."""
        await unique(lambda: self._insert(attempt), str(attempt.attempt_id))
        locked = await self._db.fetchval(
            "select id from huron.staged_uploads where subject = $1 and attempt_id = $2 for update",
            attempt.subject,
            attempt.attempt_id,
        )
        (found,) = await self._read([locked])
        return found

    async def get(self, subject: str, attempt_id: uuid.UUID) -> UploadAttempt | None:
        """The attempt of ``subject`` with ``attempt_id``."""
        row = await self._db.fetchrow(
            f"{_ATTEMPT_SELECT} where s.subject = $1 and s.attempt_id = $2", subject, attempt_id
        )
        return None if row is None else _attempt(row)

    async def find_uploads(
        self, upload_ids: Collection[uuid.UUID]
    ) -> Mapping[uuid.UUID, UploadAttempt]:
        """The attempt of each issued ID of ``upload_ids``, read without a row lock."""
        found = await self._db.fetch(
            "select distinct i.staged_upload_id as id from huron.staged_upload_ids i"
            " where i.upload_id = any($1::uuid[])",
            list(upload_ids),
        )
        return _by_upload(await self._read([row["id"] for row in found]), upload_ids)

    async def lock_uploads(
        self, upload_ids: Collection[uuid.UUID]
    ) -> Mapping[uuid.UUID, UploadAttempt]:
        """The attempt of each issued ID of ``upload_ids``, locked in the order of row IDs."""
        locked = await self._db.fetch(
            "select s.id from huron.staged_uploads s where s.id in ("
            " select i.staged_upload_id from huron.staged_upload_ids i"
            " where i.upload_id = any($1::uuid[])) order by s.id for update of s",
            list(upload_ids),
        )
        return _by_upload(await self._read([row["id"] for row in locked]), upload_ids)

    async def lock_idle(self, before: datetime, limit: int) -> Sequence[UploadAttempt]:
        """Lock the idle attempts, the oldest activity first, and skip rows locked elsewhere."""
        locked = await self._db.fetch(
            "select id from huron.staged_uploads"
            " where (state in ('receiving', 'sealing')"
            " or (state = 'ready' and commit_request_id is null))"
            " and active_at < $1 order by active_at, id limit $2 for update skip locked",
            before,
            limit,
        )
        attempts = await self._read([row["id"] for row in locked])
        return sorted(attempts, key=lambda attempt: (attempt.active_at, attempt.id))

    async def staged_bytes(self) -> int:
        """The total declared size of the attempts that wait for a commit."""
        total: int = await self._db.fetchval(
            "select coalesce(sum(size), 0)::bigint from huron.staged_uploads"
            " where state in ('receiving', 'sealing', 'ready')"
        )
        return total

    async def spent(self, upload_ids: Collection[uuid.UUID]) -> set[uuid.UUID]:
        """The issued IDs of ``upload_ids`` that are not current or whose attempt is final."""
        rows = await self._db.fetch(
            "select i.upload_id from huron.staged_upload_ids i"
            " join huron.staged_uploads s on s.id = i.staged_upload_id"
            f" where i.upload_id = any($1::uuid[]) and {_SPENT}",
            list(upload_ids),
        )
        return {row["upload_id"] for row in rows}

    async def issue(self, attempt_id: uuid.UUID, upload_id: uuid.UUID, issued_at: datetime) -> None:
        """Store ``upload_id`` for the attempt and make it the current ID, in one statement."""
        await unique(
            lambda: self._db.execute(
                "with issued as (insert into huron.staged_upload_ids"
                " (upload_id, staged_upload_id, issued_at)"
                " select $2, id, $3 from huron.staged_uploads where id = $1"
                " returning staged_upload_id)"
                " update huron.staged_uploads set current_upload_id = $2"
                " where id in (select staged_upload_id from issued)",
                attempt_id,
                upload_id,
                issued_at,
            ),
            str(upload_id),
        )

    async def update(self, attempt: UploadAttempt) -> None:
        """Replace the state, the activity time, the commit request and the failure."""
        a = attempt
        await self._db.execute(
            "update huron.staged_uploads set state = $2, active_at = $3, commit_request_id = $4,"
            " failure = $5 where id = $1",
            a.id,
            str(a.state),
            a.active_at,
            a.commit_request_id,
            None if a.failure is None else a.failure.as_dict(),
        )

    async def _insert(self, attempt: UploadAttempt) -> None:
        a = attempt
        stored = await self._db.fetchval(
            f"insert into huron.staged_uploads ({_ATTEMPT_COLUMNS})"
            " values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)"
            " on conflict (subject, attempt_id) do nothing returning id",
            a.id,
            a.subject,
            a.attempt_id,
            a.collection_id,
            a.rel_path,
            a.size,
            str(a.state),
            a.current_upload_id,
            a.created_at,
            a.active_at,
            a.commit_request_id,
            None if a.failure is None else a.failure.as_dict(),
        )
        if stored is not None:
            await self._db.execute(
                "insert into huron.staged_upload_ids (upload_id, staged_upload_id, issued_at)"
                " select unnest($1::uuid[]), $2, $3",
                list(a.upload_ids),
                a.id,
                a.created_at,
            )

    async def _read(self, attempt_ids: Sequence[uuid.UUID]) -> list[UploadAttempt]:
        rows = await self._db.fetch(
            f"{_ATTEMPT_SELECT} where s.id = any($1::uuid[]) order by s.id", list(attempt_ids)
        )
        return [_attempt(row) for row in rows]


class PostgresObjects:
    """Stored objects in table ``huron.objects``."""

    def __init__(self, connection: Db) -> None:
        self._db = connection

    async def insert_or_lock(self, stored: StoredObject) -> StoredObject:
        """Store the object unless its upload ID has one, then lock and read that object."""
        o = stored
        await unique(
            lambda: self._db.execute(
                f"insert into huron.objects ({_OBJECT_COLUMNS})"
                " values ($1, $2, $3, $4, $5, $6, $7, $8, $9)"
                " on conflict (upload_id) do nothing",
                *_object_row(o),
            ),
            o.path,
        )
        row = await self._db.fetchrow(
            f"select {_OBJECT_COLUMNS} from huron.objects where upload_id = $1 for update",
            o.upload_id,
        )
        assert row is not None
        return _object(row)

    async def lock_uploads(
        self, upload_ids: Collection[uuid.UUID]
    ) -> Mapping[uuid.UUID, StoredObject]:
        """The objects of ``upload_ids``, locked in the order of their upload IDs."""
        rows = await self._db.fetch(
            f"select {_OBJECT_COLUMNS} from huron.objects where upload_id = any($1::uuid[])"
            " order by upload_id for update",
            list(upload_ids),
        )
        return {row["upload_id"]: _object(row) for row in rows}

    async def unreferenced(self, after: uuid.UUID | None, limit: int) -> Sequence[StoredObject]:
        """The objects that no row needs, in the order of their IDs, after ``after``.

        The partial index ``ix_objects_present`` gives the objects that are not ``removed``,
        and each condition is one index look-up for such an object, so a run reads no removed
        object.
        """
        rows = await self._db.fetch(
            f"select {_OBJECT_COLUMNS} from huron.objects o"
            " where o.state <> 'removed' and ($1::uuid is null or o.id > $1)"
            " and exists (select 1 from huron.staged_upload_ids i"
            " join huron.staged_uploads s on s.id = i.staged_upload_id"
            f" where i.upload_id = o.upload_id and {_SPENT})"
            " and not exists (select 1 from huron.files f where f.object_id = o.id)"
            " and not exists (select 1 from huron.commit_entries e"
            " join huron.commit_requests r on r.id = e.commit_request_id"
            " where e.upload_id = o.upload_id and r.state in ('accepted', 'blocked'))"
            " order by o.id limit $2",
            after,
            limit,
        )
        return [_object(row) for row in rows]

    async def update(self, stored: StoredObject) -> None:
        """Replace the state, the size, the SHA-256, the inode and the seal time."""
        o = stored
        await self._db.execute(
            "update huron.objects set state = $2, size = $3, sha256 = $4, inode = $5,"
            " sealed_at = $6 where id = $1",
            o.id,
            str(o.state),
            o.size,
            o.sha256,
            signed_inode(o.inode),
            o.sealed_at,
        )


def _by_upload(
    attempts: Sequence[UploadAttempt], upload_ids: Collection[uuid.UUID]
) -> dict[uuid.UUID, UploadAttempt]:
    """Each of ``upload_ids`` that one of ``attempts`` issued, with that attempt."""
    wanted = set(upload_ids)
    return {
        upload_id: attempt
        for attempt in attempts
        for upload_id in attempt.upload_ids
        if upload_id in wanted
    }


def _attempt(row: asyncpg.Record) -> UploadAttempt:
    values = dict(row)
    failure = values.pop("failure")
    values["state"] = AttemptState(values["state"])
    values["upload_ids"] = tuple(values["upload_ids"])
    return UploadAttempt(**values, failure=None if failure is None else Failure(**failure))


def _object_row(stored: StoredObject) -> tuple[Any, ...]:
    """The values of ``stored`` in the order of ``_OBJECT_COLUMNS``."""
    o = stored
    return (
        o.id,
        o.upload_id,
        o.path,
        str(o.state),
        o.created_at,
        o.size,
        o.sha256,
        signed_inode(o.inode),
        o.sealed_at,
    )


def _object(row: asyncpg.Record) -> StoredObject:
    values = dict(row)
    values["state"] = ObjectState(values["state"])
    values["inode"] = unsigned_inode(values["inode"])
    return StoredObject(**values)
