"""PostgreSQL organizations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from huron.core.lake.organizations.models import Organization
from huron.core.metastore.rows import Db, unique

if TYPE_CHECKING:
    import uuid
    from collections.abc import Collection, Sequence


__all__ = ["PostgresOrganizations"]

_COLUMNS = "id, name, display_name, description, version, created_at, created_by"


class PostgresOrganizations:
    """Organizations in table ``huron.organizations``."""

    def __init__(self, connection: Db) -> None:
        self._db = connection

    async def insert(self, organization: Organization) -> None:
        """Store a new organization."""
        o = organization
        await unique(
            lambda: self._db.execute(
                f"insert into huron.organizations ({_COLUMNS}) values ($1, $2, $3, $4, $5, $6, $7)",
                o.id,
                o.name,
                o.display_name,
                o.description,
                o.version,
                o.created_at,
                o.created_by,
            ),
            o.name,
        )

    async def get(self, organization_id: uuid.UUID) -> Organization | None:
        """The organization with ``organization_id``."""
        row = await self._db.fetchrow(
            f"select {_COLUMNS} from huron.organizations where id = $1", organization_id
        )
        return None if row is None else Organization(**row)

    async def get_by_name(self, name: str) -> Organization | None:
        """The organization named ``name``."""
        row = await self._db.fetchrow(
            f"select {_COLUMNS} from huron.organizations where name = $1", name
        )
        return None if row is None else Organization(**row)

    async def list(
        self, ids: Collection[uuid.UUID] | None, after: str | None, limit: int
    ) -> Sequence[Organization]:
        """Organizations sorted by name."""
        rows = await self._db.fetch(
            f"select {_COLUMNS} from huron.organizations"
            " where ($1::uuid[] is null or id = any($1))"
            " and ($2::text is null or name > $2) order by name limit $3",
            None if ids is None else list(ids),
            after,
            limit,
        )
        return [Organization(**row) for row in rows]

    async def delete(self, organization_id: uuid.UUID) -> None:
        """Remove an organization."""
        await self._db.execute("delete from huron.organizations where id = $1", organization_id)

    async def catalog_count(self, organization_id: uuid.UUID) -> int:
        """How many catalogs the organization has."""
        count: int = await self._db.fetchval(
            "select count(*) from huron.catalogs where organization_id = $1", organization_id
        )
        return count
