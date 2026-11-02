"""PostgreSQL grants with the catalog → organization hierarchy."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from huron.core.security.rbac import PLATFORM, Role, Scope, ScopeType

if TYPE_CHECKING:
    import uuid
    from collections.abc import Iterable, Mapping, Sequence

    from huron.core.metastore.rows import Db

__all__ = ["PostgresGrants"]


class PostgresGrants:
    """Grants in table ``huron.grants``."""

    def __init__(self, connection: Db) -> None:
        self._db = connection

    async def roles_for_groups(self, groups: Iterable[str]) -> Sequence[tuple[Scope, Role]]:
        """Every ``(scope, role)`` granted to any of ``groups``."""
        rows = await self._db.fetch(
            "select distinct scope_type, scope_id, role from huron.grants"
            " where ldap_group = any($1) order by scope_type, scope_id, role",
            list(groups),
        )
        return [(_scope(row["scope_type"], row["scope_id"]), Role(row["role"])) for row in rows]

    async def groups_for_scope(self, scope: Scope) -> Mapping[Role, Sequence[str]]:
        """Groups per role at exactly ``scope``."""
        rows = await self._db.fetch(
            "select role, ldap_group from huron.grants where scope_type = $1"
            " and scope_id is not distinct from $2 order by role, ldap_group",
            str(scope.type),
            scope.id,
        )
        found: dict[Role, list[str]] = {}
        for row in rows:
            found.setdefault(Role(row["role"]), []).append(row["ldap_group"])
        return found

    async def enclosing(self, scope: Scope) -> Sequence[Scope]:
        """``scope`` and its enclosing scopes, innermost first."""
        if scope.type is ScopeType.PLATFORM:
            return [PLATFORM]
        if scope.type is ScopeType.ORGANIZATION:
            return [scope, PLATFORM]
        organization = await self._db.fetchval(
            "select organization_id from huron.catalogs where id = $1", scope.id
        )
        if organization is None:
            return [scope, PLATFORM]
        return [scope, Scope.organization(organization), PLATFORM]

    async def replace(
        self, scope: Scope, role: Role, groups: Iterable[str], created_by: str
    ) -> tuple[list[str], list[str]]:
        """Make ``groups`` the exact set granted ``role`` at ``scope``."""
        wanted = sorted(set(groups))
        removed = await self._db.fetch(
            "delete from huron.grants where scope_type = $1 and scope_id is not distinct from $2"
            " and role = $3 and not (ldap_group = any($4)) returning ldap_group",
            str(scope.type),
            scope.id,
            str(role),
            wanted,
        )
        added = await self._db.fetch(
            "insert into huron.grants (id, scope_type, scope_id, role, ldap_group, created_at,"
            " created_by) select gen_random_uuid(), $1, $2, $3, g, $5, $6 from unnest($4::text[]) g"
            " on conflict do nothing returning ldap_group",
            str(scope.type),
            scope.id,
            str(role),
            wanted,
            datetime.now(UTC),
            created_by,
        )
        return sorted(r["ldap_group"] for r in added), sorted(r["ldap_group"] for r in removed)

    async def delete_scope(self, scope: Scope) -> None:
        """Remove every grant at ``scope``."""
        await self._db.execute(
            "delete from huron.grants where scope_type = $1 and scope_id is not distinct from $2",
            str(scope.type),
            scope.id,
        )


def _scope(scope_type: str, scope_id: uuid.UUID | None) -> Scope:
    return Scope(ScopeType(scope_type), scope_id)
