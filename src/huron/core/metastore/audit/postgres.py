"""PostgreSQL audit log."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from huron.core.lake.audit.models import Action, AuditEntry, ObjectType

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence

    import asyncpg

    from huron.core.metastore.rows import Db

__all__ = ["PostgresAudit"]

_COLUMNS = "id, at, actor, action, object_type, object_id, catalog_id, organization_id, detail"


class PostgresAudit:
    """The audit log in table ``huron.audit``."""

    def __init__(self, connection: Db) -> None:
        self._db = connection

    async def write(self, entry: AuditEntry) -> AuditEntry:
        """Append an entry; the identity column assigns its id."""
        e = entry
        identifier = await self._db.fetchval(
            "insert into huron.audit (at, actor, action, object_type, object_id, catalog_id,"
            " organization_id, detail) values ($1, $2, $3, $4, $5, $6, $7, $8) returning id",
            e.at,
            e.actor,
            str(e.action),
            str(e.object_type),
            e.object_id,
            e.catalog_id,
            e.organization_id,
            e.detail,
        )
        return replace(entry, id=identifier)

    async def for_object(
        self, object_id: uuid.UUID, before: int | None, limit: int
    ) -> Sequence[AuditEntry]:
        """Entries about one object, newest first."""
        rows = await self._db.fetch(
            f"select {_COLUMNS} from huron.audit where object_id = $1"
            " and ($2::bigint is null or id < $2) order by id desc limit $3",
            object_id,
            before,
            limit,
        )
        return [_entry(row) for row in rows]

    async def for_catalog(
        self, catalog_id: uuid.UUID, before: int | None, limit: int
    ) -> Sequence[AuditEntry]:
        """Entries within one catalog, newest first."""
        rows = await self._db.fetch(
            f"select {_COLUMNS} from huron.audit where catalog_id = $1"
            " and ($2::bigint is null or id < $2) order by id desc limit $3",
            catalog_id,
            before,
            limit,
        )
        return [_entry(row) for row in rows]


def _entry(row: asyncpg.Record) -> AuditEntry:
    values = dict(row.items())
    values["action"] = Action(values["action"])
    values["object_type"] = ObjectType(values["object_type"])
    return AuditEntry(**values)
