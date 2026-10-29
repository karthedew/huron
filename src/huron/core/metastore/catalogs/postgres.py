"""PostgreSQL catalogs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from huron.core.lake.catalogs.models import Catalog
from huron.core.metastore.rows import Db, unique

if TYPE_CHECKING:
    import uuid
    from collections.abc import Collection, Sequence


__all__ = ["PostgresCatalogs"]

_COLUMNS = (
    "id, organization_id, name, display_name, description, schema_id, version,"
    " created_at, created_by"
)


class PostgresCatalogs:
    """Catalogs in table ``huron.catalogs``."""

    def __init__(self, connection: Db) -> None:
        self._db = connection

    async def insert(self, catalog: Catalog) -> None:
        """Store a new catalog."""
        c = catalog
        await unique(
            lambda: self._db.execute(
                f"insert into huron.catalogs ({_COLUMNS})"
                " values ($1, $2, $3, $4, $5, $6, $7, $8, $9)",
                c.id,
                c.organization_id,
                c.name,
                c.display_name,
                c.description,
                c.schema_id,
                c.version,
                c.created_at,
                c.created_by,
            ),
            c.name,
        )

    async def get(self, catalog_id: uuid.UUID) -> Catalog | None:
        """The catalog with ``catalog_id``."""
        row = await self._db.fetchrow(
            f"select {_COLUMNS} from huron.catalogs where id = $1", catalog_id
        )
        return None if row is None else Catalog(**row)

    async def get_by_name(self, name: str) -> Catalog | None:
        """The catalog named ``name``."""
        row = await self._db.fetchrow(
            f"select {_COLUMNS} from huron.catalogs where name = $1", name
        )
        return None if row is None else Catalog(**row)

    async def list(
        self,
        organization_id: uuid.UUID | None,
        visible: tuple[Collection[uuid.UUID], Collection[uuid.UUID]] | None,
        after: str | None,
        limit: int,
    ) -> Sequence[Catalog]:
        """Catalogs sorted by name."""
        orgs, ids = (None, None) if visible is None else (list(visible[0]), list(visible[1]))
        rows = await self._db.fetch(
            f"select {_COLUMNS} from huron.catalogs"
            " where ($1::uuid is null or organization_id = $1)"
            " and ($2::uuid[] is null or organization_id = any($2) or id = any($3::uuid[]))"
            " and ($4::text is null or name > $4) order by name limit $5",
            organization_id,
            orgs,
            ids,
            after,
            limit,
        )
        return [Catalog(**row) for row in rows]

    async def update(self, catalog: Catalog) -> None:
        """Replace the stored row."""
        c = catalog
        await self._db.execute(
            "update huron.catalogs set display_name = $2, description = $3, schema_id = $4,"
            " version = $5 where id = $1",
            c.id,
            c.display_name,
            c.description,
            c.schema_id,
            c.version,
        )

    async def delete(self, catalog_id: uuid.UUID) -> None:
        """Remove a catalog."""
        await self._db.execute("delete from huron.catalogs where id = $1", catalog_id)

    async def namespace_count(self, catalog_id: uuid.UUID) -> int:
        """How many namespaces the catalog has."""
        count: int = await self._db.fetchval(
            "select count(*) from huron.namespaces where catalog_id = $1", catalog_id
        )
        return count
