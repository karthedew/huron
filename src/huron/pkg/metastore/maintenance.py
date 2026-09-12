"""Dedicated-role exclusion and audited schema-0010 maintenance."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncpg


class PostgresRoleExclusion:
    """Revoke legacy application access without treating a login check as process death."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        """Bind the separately authenticated cutover database pool.

        Args:
            pool: Maintenance identity with authority over dedicated application roles.
        """
        self._pool = pool

    async def exclude(self, old_roles: tuple[str, ...], new_role: str) -> None:
        """Disable logins, remove old inherited/direct access and terminate application sessions.

        Dedicated application roles must own no objects and hold no administrative
        attributes. The adapter refuses owner-role deployments instead of deleting or
        transferring their objects.

        Args:
            old_roles: Permanent legacy application exclusions.
            new_role: Replacement role kept disabled during the verification interval.

        Raises:
            ValueError: If a role is unsafe or a backend cannot be terminated.
        """
        roles = _roles(old_roles, new_role)
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                for role in roles:
                    await _require_dedicated(connection, role)
                    await connection.execute(f"ALTER ROLE {_identifier(role)} NOLOGIN")
                for role in old_roles:
                    await _revoke_access(connection, role)
            stopped = await connection.fetch(
                "SELECT pg_terminate_backend(pid, 10000) AS stopped FROM pg_stat_activity "
                "WHERE usename = ANY($1::text[]) AND pid <> pg_backend_pid()",
                list(roles),
            )
            if any(not row["stopped"] for row in stopped):
                raise ValueError("application database session termination was not confirmed")
        await self.check(old_roles, new_role)

    async def check(self, old_roles: tuple[str, ...], new_role: str) -> None:
        """Verify live login, session, ownership, inherited and effective application access.

        Args:
            old_roles: Permanently excluded legacy application roles.
            new_role: Replacement role excluded until validated activation.

        Raises:
            ValueError: If any application identity has escaped its database fence.
        """
        roles = _roles(old_roles, new_role)
        async with self._pool.acquire() as connection:
            for role in roles:
                await _require_dedicated(connection, role)
            admitted = await connection.fetchval(
                "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=ANY($1::text[]) "
                "AND rolcanlogin) OR EXISTS(SELECT 1 FROM pg_stat_activity "
                "WHERE usename=ANY($1::text[]))",
                list(roles),
            )
            if admitted:
                raise ValueError("application database login or session fence was lost")
            for role in old_roles:
                if await _effective_access(connection, role):
                    raise ValueError("legacy role retains effective application access")


def _identifier(value: str) -> str:
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", value):
        raise ValueError("maintenance requires simple dedicated role names")
    return f'"{value}"'


def _roles(old_roles: tuple[str, ...], new_role: str) -> tuple[str, ...]:
    roles = (*old_roles, new_role)
    if not old_roles or len(set(roles)) != len(roles):
        raise ValueError("legacy and replacement roles must be distinct and nonempty")
    for role in roles:
        _identifier(role)
    return roles


async def _require_dedicated(connection: asyncpg.Connection, role: str) -> None:
    safe = await connection.fetchval(
        "SELECT NOT (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls) "
        "AND rolname <> session_user AND NOT EXISTS (SELECT 1 FROM pg_shdepend "
        "WHERE refclassid='pg_authid'::regclass AND refobjid=pg_roles.oid AND deptype='o') "
        "FROM pg_roles WHERE rolname=$1",
        role,
    )
    if not safe:
        raise ValueError("application role is missing, administrative or owns database objects")


async def _revoke_access(connection: asyncpg.Connection, role: str) -> None:
    parents = await connection.fetch(
        "SELECT parent.rolname FROM pg_auth_members membership "
        "JOIN pg_roles parent ON parent.oid=membership.roleid "
        "JOIN pg_roles child ON child.oid=membership.member WHERE child.rolname=$1",
        role,
    )
    for parent in parents:
        await connection.execute(
            f"REVOKE {_identifier(parent['rolname'])} FROM {_identifier(role)}"
        )
    schemas = await connection.fetch(
        "SELECT nspname FROM pg_namespace WHERE nspname NOT LIKE 'pg_%' "
        "AND nspname <> 'information_schema'"
    )
    for schema in schemas:
        name = '"' + str(schema["nspname"]).replace('"', '""') + '"'
        for kind in ("TABLES", "SEQUENCES", "FUNCTIONS"):
            await connection.execute(
                f"REVOKE ALL ON ALL {kind} IN SCHEMA {name} FROM {_identifier(role)}"
            )
        await connection.execute(f"REVOKE ALL ON SCHEMA {name} FROM {_identifier(role)}")


async def _effective_access(connection: asyncpg.Connection, role: str) -> bool:
    return bool(
        await connection.fetchval(
            "SELECT EXISTS(SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member "
            "WHERE r.rolname=$1) OR EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n "
            "ON n.oid=c.relnamespace WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname "
            "<> 'information_schema' AND c.relkind IN ('r','p','v','f') AND "
            "(has_table_privilege($1,c.oid,'INSERT,UPDATE,DELETE,TRUNCATE,TRIGGER') OR "
            "has_any_column_privilege($1,c.oid,'INSERT,UPDATE'))) OR EXISTS(SELECT 1 "
            "FROM pg_namespace n WHERE n.nspname NOT LIKE 'pg_%' AND "
            "has_schema_privilege($1,n.oid,'CREATE')) OR EXISTS(SELECT 1 FROM pg_proc p "
            "JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname NOT LIKE 'pg_%' "
            "AND p.prosecdef AND has_function_privilege($1,p.oid,'EXECUTE')) OR EXISTS("
            "SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname NOT LIKE 'pg_%' AND CASE WHEN c.relkind='S' THEN "
            "has_sequence_privilege($1,c.oid,'USAGE,UPDATE') ELSE false END) OR "
            "has_database_privilege($1,current_database(),'CREATE')",
            role,
        )
    )
