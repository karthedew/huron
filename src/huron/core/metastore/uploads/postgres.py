"""PostgreSQL uploads and removals."""

from __future__ import annotations

from dataclasses import astuple, fields
from typing import TYPE_CHECKING

from huron.core.lake.uploads.models import Failure, Removal, Upload, UploadState

if TYPE_CHECKING:
    import uuid
    from collections.abc import Collection, Sequence
    from datetime import datetime

    import asyncpg

    from huron.core.metastore.rows import Db

__all__ = ["PostgresUploads"]

_UPLOAD_COLUMNS = (
    "id, collection_id, rel_path, rel_path_key, size, state, created_by, created_at, sha256,"
    " failure, placed_at, commit_id"
)
_REMOVAL_COLUMNS = ", ".join(field.name for field in fields(Removal))


class PostgresUploads:
    """Uploads in table ``huron.uploads`` and removals in table ``huron.removals``."""

    def __init__(self, connection: Db) -> None:
        self._db = connection

    async def insert(self, upload: Upload) -> None:
        """Store a new upload."""
        u = upload
        await self._db.execute(
            f"insert into huron.uploads ({_UPLOAD_COLUMNS})"
            " values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)",
            u.id,
            u.collection_id,
            u.rel_path,
            u.rel_path_key,
            u.size,
            str(u.state),
            u.created_by,
            u.created_at,
            u.sha256,
            None if u.failure is None else u.failure.as_dict(),
            u.placed_at,
            u.commit_id,
        )

    async def get(self, upload_id: uuid.UUID) -> Upload | None:
        """The upload with ``upload_id``."""
        row = await self._db.fetchrow(
            f"select {_UPLOAD_COLUMNS} from huron.uploads where id = $1", upload_id
        )
        return None if row is None else _upload(row)

    async def lock(self, upload_id: uuid.UUID) -> Upload | None:
        """The upload, locked for update."""
        row = await self._db.fetchrow(
            f"select {_UPLOAD_COLUMNS} from huron.uploads where id = $1 for update", upload_id
        )
        return None if row is None else _upload(row)

    async def update(self, upload: Upload) -> None:
        """Replace the state, receipt and failure of a stored upload."""
        u = upload
        await self._db.execute(
            "update huron.uploads set state = $2, sha256 = $3, failure = $4, placed_at = $5,"
            " commit_id = $6 where id = $1",
            u.id,
            str(u.state),
            u.sha256,
            None if u.failure is None else u.failure.as_dict(),
            u.placed_at,
            u.commit_id,
        )

    async def latest_placements(
        self, collection_id: uuid.UUID, keys: Collection[str]
    ) -> Sequence[Upload]:
        """The latest placed or committed upload of each of ``keys``."""
        rows = await self._db.fetch(
            f"select distinct on (rel_path_key) {_UPLOAD_COLUMNS} from huron.uploads"
            " where collection_id = $1 and rel_path_key = any($2)"
            " and state in ('placed', 'committed')"
            " order by rel_path_key, placed_at desc, id desc",
            collection_id,
            list(keys),
        )
        return [_upload(row) for row in rows]

    async def placed(self, collection_id: uuid.UUID) -> Sequence[Upload]:
        """The placed uploads of a collection, in the order they began."""
        rows = await self._db.fetch(
            f"select {_UPLOAD_COLUMNS} from huron.uploads"
            " where collection_id = $1 and state = 'placed' order by id",
            collection_id,
        )
        return [_upload(row) for row in rows]

    async def mark_committed(self, upload_ids: Collection[uuid.UUID], commit_id: uuid.UUID) -> None:
        """Move the uploads to ``committed`` in one statement."""
        await self._db.execute(
            "update huron.uploads set state = 'committed', commit_id = $2 where id = any($1)",
            list(upload_ids),
            commit_id,
        )

    async def insert_removals(self, removals: Sequence[Removal]) -> None:
        """Store new removals in one statement."""
        if not removals:
            return
        # One array per field of Removal, in field order, as in _REMOVAL_COLUMNS.
        columns = zip(*(astuple(removal) for removal in removals), strict=True)
        await self._db.execute(
            f"insert into huron.removals ({_REMOVAL_COLUMNS})"
            " select * from unnest($1::uuid[], $2::uuid[], $3::text[], $4::text[], $5::text[],"
            " $6::text[], $7::uuid[], $8::timestamptz[], $9::timestamptz[])",
            *(list(column) for column in columns),
        )

    async def delete_removals(self, collection_id: uuid.UUID, keys: Collection[str]) -> None:
        """Forget the removals of ``keys``."""
        await self._db.execute(
            "delete from huron.removals where collection_id = $1 and rel_path_key = any($2)",
            collection_id,
            list(keys),
        )

    async def claim_removals(
        self, now: datetime, stale_before: datetime, limit: int
    ) -> Sequence[Removal]:
        """Claim the oldest claimable removals, skipping rows another claim holds locked."""
        rows = await self._db.fetch(
            "update huron.removals set claimed_at = $1 where id in ("
            " select id from huron.removals where claimed_at is null or claimed_at < $2"
            " order by created_at, id limit $3 for update skip locked)"
            f" returning {_REMOVAL_COLUMNS}",
            now,
            stale_before,
            limit,
        )
        return sorted((Removal(**row) for row in rows), key=lambda r: (r.created_at, r.id))

    async def get_removal(self, removal_id: uuid.UUID) -> Removal | None:
        """The removal with ``removal_id``."""
        row = await self._db.fetchrow(
            f"select {_REMOVAL_COLUMNS} from huron.removals where id = $1", removal_id
        )
        return None if row is None else Removal(**row)

    async def delete_removal(self, removal_id: uuid.UUID) -> None:
        """Forget a removal."""
        await self._db.execute("delete from huron.removals where id = $1", removal_id)


def _upload(row: asyncpg.Record) -> Upload:
    values = dict(row)
    failure = values.pop("failure")
    values["state"] = UploadState(values["state"])
    return Upload(**values, failure=None if failure is None else Failure(**failure))
