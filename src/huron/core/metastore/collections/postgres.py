"""PostgreSQL collections."""

from __future__ import annotations

from typing import TYPE_CHECKING

from huron.core.lake.collections.models import Collection, Search, State
from huron.core.metastore.rows import Db, unique

if TYPE_CHECKING:
    import uuid
    from collections.abc import Collection as Container
    from collections.abc import Sequence

    import asyncpg

__all__ = ["PostgresCollections"]

_COLUMNS = (
    "id, catalog_id, namespace_id, name, identifier, state, version, metadata, schema_override,"
    " file_count, created_at, created_by, updated_at, activated_at"
)


class PostgresCollections:
    """Collections in table ``huron.collections``; a trigger enforces sibling exclusion."""

    def __init__(self, connection: Db) -> None:
        self._db = connection

    async def insert(self, collection: Collection) -> None:
        """Store a collection."""
        c = collection
        await unique(
            lambda: self._db.execute(
                f"insert into huron.collections ({_COLUMNS}) values"
                " ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)",
                c.id,
                c.catalog_id,
                c.namespace_id,
                c.name,
                c.identifier,
                str(c.state),
                c.version,
                c.metadata,
                c.schema_override,
                c.file_count,
                c.created_at,
                c.created_by,
                c.updated_at,
                c.activated_at,
            ),
            c.name,
        )

    async def get(self, collection_id: uuid.UUID) -> Collection | None:
        """The collection with ``collection_id``."""
        return _one(
            await self._db.fetchrow(
                f"select {_COLUMNS} from huron.collections where id = $1", collection_id
            )
        )

    async def get_by_identifier(self, identifier: str) -> Collection | None:
        """The collection with ``identifier``."""
        return _one(
            await self._db.fetchrow(
                f"select {_COLUMNS} from huron.collections where identifier = $1", identifier
            )
        )

    async def lock(self, collection_id: uuid.UUID) -> Collection | None:
        """The collection, locked ``for update``."""
        return _one(
            await self._db.fetchrow(
                f"select {_COLUMNS} from huron.collections where id = $1 for update", collection_id
            )
        )

    async def update(self, collection: Collection) -> None:
        """Replace the stored row."""
        c = collection
        await self._db.execute(
            "update huron.collections set state = $2, version = $3, metadata = $4,"
            " schema_override = $5, file_count = $6, updated_at = $7, activated_at = $8"
            " where id = $1",
            c.id,
            str(c.state),
            c.version,
            c.metadata,
            c.schema_override,
            c.file_count,
            c.updated_at,
            c.activated_at,
        )

    async def delete(self, collection_id: uuid.UUID) -> None:
        """Remove a collection and its commits."""
        await self._db.execute("delete from huron.collections where id = $1", collection_id)

    async def list_in_namespace(
        self, namespace_id: uuid.UUID, states: Container[State], after: str | None, limit: int
    ) -> Sequence[Collection]:
        """Collections in a namespace sorted by name."""
        rows = await self._db.fetch(
            f"select {_COLUMNS} from huron.collections where namespace_id = $1"
            " and state = any($2) and ($3::text is null or name > $3) order by name limit $4",
            namespace_id,
            _states(states),
            after,
            limit,
        )
        return [_row(row) for row in rows]

    async def list_in_catalog(
        self, catalog_id: uuid.UUID, states: Container[State]
    ) -> Sequence[Collection]:
        """Every collection of a catalog in ``states``."""
        rows = await self._db.fetch(
            f"select {_COLUMNS} from huron.collections where catalog_id = $1"
            " and state = any($2) order by identifier",
            catalog_id,
            _states(states),
        )
        return [_row(row) for row in rows]

    async def search(
        self, catalog_id: uuid.UUID, query: Search, after: str | None, limit: int
    ) -> Sequence[Collection]:
        """Collections matching ``query`` sorted by identifier."""
        labels = {"labels": dict(query.labels)} if query.labels else None
        rows = await self._db.fetch(
            f"select {_COLUMNS} from huron.collections where catalog_id = $1"
            " and state = any($2)"
            " and ($3::jsonb is null or metadata @> $3)"
            " and ($4::text is null or strpos(lower(identifier), $4) > 0"
            "      or strpos(lower(coalesce(metadata->>'title', '')), $4) > 0"
            "      or strpos(lower(coalesce(metadata->>'description', '')), $4) > 0)"
            " and ($5::text is null or identifier > $5)"
            " order by identifier limit $6",
            catalog_id,
            _states(query.states),
            labels,
            query.q.casefold() if query.q else None,
            after,
            limit,
        )
        return [_row(row) for row in rows]


def _states(states: Container[State]) -> list[str]:
    return [str(state) for state in State if state in states]


def _row(row: asyncpg.Record) -> Collection:
    values = dict(row.items())
    values["state"] = State(values["state"])
    return Collection(**values)


def _one(row: asyncpg.Record | None) -> Collection | None:
    return None if row is None else _row(row)
