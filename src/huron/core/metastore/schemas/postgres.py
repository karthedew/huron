"""PostgreSQL schema registry."""

from __future__ import annotations

from typing import TYPE_CHECKING

from huron.core.lake.schemas.models import SchemaEntry
from huron.core.metastore.rows import Db, unique

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence


__all__ = ["PostgresSchemas"]

_COLUMNS = "id, organization_id, name, version, extends_id, document, created_at, created_by"


class PostgresSchemas:
    """Registry entries in table ``huron.schemas``."""

    def __init__(self, connection: Db) -> None:
        self._db = connection

    async def insert(self, entry: SchemaEntry) -> None:
        """Store a new entry."""
        e = entry
        await unique(
            lambda: self._db.execute(
                f"insert into huron.schemas ({_COLUMNS}) values ($1, $2, $3, $4, $5, $6, $7, $8)",
                e.id,
                e.organization_id,
                e.name,
                e.version,
                e.extends_id,
                e.document,
                e.created_at,
                e.created_by,
            ),
            e.name,
        )

    async def get(self, schema_id: uuid.UUID) -> SchemaEntry | None:
        """The entry with ``schema_id``."""
        row = await self._db.fetchrow(
            f"select {_COLUMNS} from huron.schemas where id = $1", schema_id
        )
        return None if row is None else SchemaEntry(**row)

    async def latest(self, organization_id: uuid.UUID | None, name: str) -> SchemaEntry | None:
        """The highest version of ``name``."""
        row = await self._db.fetchrow(
            f"select {_COLUMNS} from huron.schemas where organization_id is not distinct from $1"
            " and name = $2 order by version desc limit 1",
            organization_id,
            name,
        )
        return None if row is None else SchemaEntry(**row)

    async def list(
        self, organization_id: uuid.UUID | None, after: tuple[str, int] | None, limit: int
    ) -> Sequence[SchemaEntry]:
        """Entries sorted by name, then version descending."""
        name, version = after if after is not None else (None, None)
        rows = await self._db.fetch(
            f"select {_COLUMNS} from huron.schemas where organization_id is not distinct from $1"
            " and ($2::text is null or name > $2 or (name = $2 and version < $3))"
            " order by name, version desc limit $4",
            organization_id,
            name,
            version,
            limit,
        )
        return [SchemaEntry(**row) for row in rows]
