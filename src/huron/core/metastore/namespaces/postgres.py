"""PostgreSQL namespaces."""

from __future__ import annotations

from typing import TYPE_CHECKING

from huron.core.lake.listing import ListOrder, Position
from huron.core.lake.namespaces.models import Namespace
from huron.core.metastore.rows import Db, unique
from huron.core.metastore.sorting import ListingSql

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence


__all__ = ["PostgresNamespaces"]

_COLUMNS = (
    "id, catalog_id, parent_id, name, path, collections_allowed, version, created_at, created_by"
)


class PostgresNamespaces:
    """Namespaces in table ``huron.namespaces``; a trigger enforces sibling exclusion."""

    def __init__(self, connection: Db) -> None:
        self._db = connection

    async def insert(self, namespace: Namespace) -> None:
        """Store a namespace."""
        n = namespace
        await unique(
            lambda: self._db.execute(
                f"insert into huron.namespaces ({_COLUMNS})"
                " values ($1, $2, $3, $4, $5, $6, $7, $8, $9)",
                n.id,
                n.catalog_id,
                n.parent_id,
                n.name,
                n.path,
                n.collections_allowed,
                n.version,
                n.created_at,
                n.created_by,
            ),
            n.name,
        )

    async def get(self, namespace_id: uuid.UUID) -> Namespace | None:
        """The namespace with ``namespace_id``."""
        row = await self._db.fetchrow(
            f"select {_COLUMNS} from huron.namespaces where id = $1", namespace_id
        )
        return None if row is None else Namespace(**row)

    async def get_by_path(self, catalog_id: uuid.UUID, path: str) -> Namespace | None:
        """The namespace at ``path``."""
        row = await self._db.fetchrow(
            f"select {_COLUMNS} from huron.namespaces where catalog_id = $1 and path = $2",
            catalog_id,
            path,
        )
        return None if row is None else Namespace(**row)

    async def children(
        self,
        catalog_id: uuid.UUID,
        parent_id: uuid.UUID | None,
        after: Position,
        limit: int,
        ordering: ListOrder | None = None,
    ) -> Sequence[Namespace]:
        """Direct children in the requested order."""
        sorting = ListingSql(ordering or ListOrder(), 3)
        rows = await self._db.fetch(
            f"select {_COLUMNS} from huron.namespaces where catalog_id = $1"
            " and parent_id is not distinct from $2" + sorting.clause(),
            catalog_id,
            parent_id,
            *sorting.values(after, limit),
        )
        return [Namespace(**row) for row in rows]

    async def list_in_catalog(self, catalog_id: uuid.UUID) -> Sequence[Namespace]:
        """Every namespace of a catalog, sorted by path."""
        rows = await self._db.fetch(
            f"select {_COLUMNS} from huron.namespaces where catalog_id = $1 order by path",
            catalog_id,
        )
        return [Namespace(**row) for row in rows]

    async def child_counts(self, namespace_id: uuid.UUID) -> tuple[int, int]:
        """``(child namespaces, collections)``."""
        row = await self._db.fetchrow(
            "select (select count(*) from huron.namespaces where parent_id = $1) as namespaces,"
            " (select count(*) from huron.collections where namespace_id = $1) as collections",
            namespace_id,
        )
        assert row is not None
        return int(row["namespaces"]), int(row["collections"])

    async def draft_count(self, namespace_id: uuid.UUID) -> int:
        """How many drafts are directly inside the namespace."""
        count: int = await self._db.fetchval(
            "select count(*) from huron.collections where namespace_id = $1 and state = 'draft'",
            namespace_id,
        )
        return count

    async def update(self, namespace: Namespace) -> None:
        """Replace the stored row."""
        await self._db.execute(
            "update huron.namespaces set collections_allowed = $2, version = $3 where id = $1",
            namespace.id,
            namespace.collections_allowed,
            namespace.version,
        )

    async def delete(self, namespace_id: uuid.UUID) -> None:
        """Remove a namespace."""
        await self._db.execute("delete from huron.namespaces where id = $1", namespace_id)
