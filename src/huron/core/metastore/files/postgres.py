"""PostgreSQL files and commits."""

from __future__ import annotations

from typing import TYPE_CHECKING

from huron.core.lake.files.models import Commit, FileRecord

if TYPE_CHECKING:
    import uuid
    from collections.abc import Collection, Sequence

    from huron.core.metastore.rows import Db

__all__ = ["PostgresCommits", "PostgresFiles"]

_FILE_COLUMNS = (
    "collection_id, rel_path, rel_path_key, size, sha256, recorded_at, recorded_by, commit_id"
)
_COMMIT_COLUMNS = (
    "id, collection_id, base_version, new_version, adds, removes, host, message, actor, created_at"
)


class PostgresFiles:
    """Recorded files in table ``huron.files``."""

    def __init__(self, connection: Db) -> None:
        self._db = connection

    async def upsert_many(self, records: Sequence[FileRecord]) -> None:
        """Insert or replace records in one statement."""
        if not records:
            return
        await self._db.execute(
            f"insert into huron.files ({_FILE_COLUMNS})"
            " select * from unnest($1::uuid[], $2::text[], $3::text[], $4::bigint[], $5::text[],"
            " $6::timestamptz[], $7::text[], $8::uuid[])"
            " on conflict (collection_id, rel_path_key) do update set"
            " rel_path = excluded.rel_path, size = excluded.size, sha256 = excluded.sha256,"
            " recorded_at = excluded.recorded_at, recorded_by = excluded.recorded_by,"
            " commit_id = excluded.commit_id",
            [r.collection_id for r in records],
            [r.rel_path for r in records],
            [r.rel_path_key for r in records],
            [r.size for r in records],
            [r.sha256 for r in records],
            [r.recorded_at for r in records],
            [r.recorded_by for r in records],
            [r.commit_id for r in records],
        )

    async def delete_many(self, collection_id: uuid.UUID, keys: Collection[str]) -> None:
        """Remove records."""
        await self._db.execute(
            "delete from huron.files where collection_id = $1 and rel_path_key = any($2)",
            collection_id,
            list(keys),
        )

    async def existing(self, collection_id: uuid.UUID, keys: Collection[str]) -> set[str]:
        """Which keys are recorded."""
        rows = await self._db.fetch(
            "select rel_path_key from huron.files where collection_id = $1"
            " and rel_path_key = any($2)",
            collection_id,
            list(keys),
        )
        return {row["rel_path_key"] for row in rows}

    async def beneath(
        self, collection_id: uuid.UUID, prefixes: Collection[str], limit: int
    ) -> set[str]:
        """Recorded keys under any of ``prefixes``."""
        rows = await self._db.fetch(
            "select f.rel_path_key from huron.files f"
            " where f.collection_id = $1"
            " and exists (select 1 from unnest($2::text[]) p where starts_with(f.rel_path_key, p))"
            " order by f.rel_path_key limit $3",
            collection_id,
            list(prefixes),
            limit,
        )
        return {row["rel_path_key"] for row in rows}

    async def list(
        self, collection_id: uuid.UUID, after: str | None, limit: int
    ) -> Sequence[FileRecord]:
        """Records sorted by key."""
        rows = await self._db.fetch(
            f"select {_FILE_COLUMNS} from huron.files where collection_id = $1"
            " and ($2::text is null or rel_path_key > $2) order by rel_path_key limit $3",
            collection_id,
            after,
            limit,
        )
        return [FileRecord(**row) for row in rows]

    async def count(self, collection_id: uuid.UUID) -> int:
        """How many files are recorded."""
        count: int = await self._db.fetchval(
            "select count(*) from huron.files where collection_id = $1", collection_id
        )
        return count


class PostgresCommits:
    """Commits in table ``huron.commits``."""

    def __init__(self, connection: Db) -> None:
        self._db = connection

    async def insert(self, commit: Commit) -> None:
        """Store a commit."""
        c = commit
        await self._db.execute(
            f"insert into huron.commits ({_COMMIT_COLUMNS})"
            " values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)",
            c.id,
            c.collection_id,
            c.base_version,
            c.new_version,
            c.adds,
            c.removes,
            c.host,
            c.message,
            c.actor,
            c.created_at,
        )

    async def list(
        self, collection_id: uuid.UUID, before: uuid.UUID | None, limit: int
    ) -> Sequence[Commit]:
        """Commits newest first."""
        rows = await self._db.fetch(
            f"select {_COMMIT_COLUMNS} from huron.commits where collection_id = $1"
            " and ($2::uuid is null or id < $2) order by id desc limit $3",
            collection_id,
            before,
            limit,
        )
        return [Commit(**row) for row in rows]
