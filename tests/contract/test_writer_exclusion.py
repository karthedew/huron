"""Application database fencing against real PostgreSQL identities and surviving sessions."""

import asyncio

import asyncpg
import pytest
from testcontainers.postgres import PostgresContainer

from huron.pkg.metastore.maintenance import PostgresRoleExclusion

pytestmark = pytest.mark.contract


def test_database_exclusion_revokes_inherited_rights_and_terminates_admitted_sessions() -> None:
    """Old logins and already connected sessions are independently excluded."""
    with PostgresContainer("postgres:16") as postgres:
        asyncio.run(_exercise_exclusion(postgres.get_connection_url(driver=None)))


async def _exercise_exclusion(dsn: str) -> None:
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)
    try:
        async with pool.acquire() as admin:
            await admin.execute("CREATE ROLE old_app LOGIN PASSWORD 'old-app-test'")
            await admin.execute("CREATE ROLE new_app LOGIN PASSWORD 'new-app-test'")
            await admin.execute("CREATE ROLE inherited_writer")
            await admin.execute("CREATE TABLE scientific_values(value integer)")
            await admin.execute("GRANT INSERT ON scientific_values TO inherited_writer")
            await admin.execute("GRANT inherited_writer TO old_app")
            await admin.execute('CREATE SCHEMA "quoted""schema"')
            await admin.execute('CREATE TABLE "quoted""schema".preserved(value integer)')
            await admin.execute("CREATE ROLE unrelated_reader")
            await admin.execute('GRANT USAGE ON SCHEMA "quoted""schema" TO old_app, unrelated_reader')
            await admin.execute('GRANT INSERT ON "quoted""schema".preserved TO old_app')
            await admin.execute('GRANT SELECT ON "quoted""schema".preserved TO unrelated_reader')
        old = await asyncpg.connect(dsn, user="old_app", password="old-app-test")
        new = await asyncpg.connect(dsn, user="new_app", password="new-app-test")
        await old.execute("INSERT INTO scientific_values VALUES (1)")
        fence = PostgresRoleExclusion(pool)
        await fence.exclude(("old_app",), "new_app")
        assert old.is_closed()
        assert new.is_closed()
        with pytest.raises(asyncpg.InvalidAuthorizationSpecificationError):
            await asyncpg.connect(dsn, user="old_app", password="old-app-test")
        with pytest.raises(asyncpg.InvalidAuthorizationSpecificationError):
            await asyncpg.connect(dsn, user="new_app", password="new-app-test")
        await fence.check(("old_app",), "new_app")
        async with pool.acquire() as admin:
            assert not await admin.fetchval(
                "SELECT has_table_privilege('old_app','scientific_values','INSERT')"
            )
            assert not await admin.fetchval(
                "SELECT has_schema_privilege('old_app', $1, 'USAGE')", 'quoted"schema'
            )
            assert not await admin.fetchval(
                "SELECT has_table_privilege('old_app', $1, 'INSERT')", '"quoted""schema".preserved'
            )
            assert await admin.fetchval(
                "SELECT has_schema_privilege('unrelated_reader', $1, 'USAGE')", 'quoted"schema'
            )
            assert await admin.fetchval(
                "SELECT has_table_privilege('unrelated_reader', $1, 'SELECT')",
                '"quoted""schema".preserved',
            )
            assert await admin.fetchval(
                "SELECT has_table_privilege('inherited_writer', 'scientific_values', 'INSERT')"
            )
            await admin.execute("ALTER ROLE new_app LOGIN")
        with pytest.raises(ValueError, match="login or session fence was lost"):
            await fence.check(("old_app",), "new_app")
        await fence.exclude(("old_app",), "new_app")
        async with pool.acquire() as admin:
            await admin.execute("GRANT INSERT ON scientific_values TO PUBLIC")
        with pytest.raises(ValueError, match="effective application access"):
            await fence.check(("old_app",), "new_app")
    finally:
        await pool.close()


def test_database_owner_and_administrative_roles_are_not_eligible_application_identities() -> None:
    """The maintenance adapter refuses legacy owner credentials without altering their objects."""
    with PostgresContainer("postgres:16") as postgres:
        asyncio.run(_exercise_owner_refusal(postgres.get_connection_url(driver=None)))


async def _exercise_owner_refusal(dsn: str) -> None:
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    try:
        async with pool.acquire() as admin:
            await admin.execute("CREATE ROLE old_owner LOGIN")
            await admin.execute("CREATE ROLE new_app LOGIN")
            await admin.execute("CREATE TABLE preserved(value integer)")
            await admin.execute("ALTER TABLE preserved OWNER TO old_owner")
        with pytest.raises(ValueError, match="owns database objects"):
            await PostgresRoleExclusion(pool).exclude(("old_owner",), "new_app")
        async with pool.acquire() as admin:
            assert await admin.fetchval(
                "SELECT rolcanlogin FROM pg_roles WHERE rolname='old_owner'"
            )
            assert await admin.fetchval("SELECT to_regclass('preserved') IS NOT NULL")
    finally:
        await pool.close()


@pytest.mark.parametrize(
    ("grant", "revoke"),
    [
        (
            "GRANT UPDATE(value) ON scientific_values TO PUBLIC",
            "REVOKE UPDATE(value) ON scientific_values FROM PUBLIC",
        ),
        (
            "GRANT USAGE ON scientific_sequence TO PUBLIC",
            "REVOKE USAGE ON scientific_sequence FROM PUBLIC",
        ),
        (
            "GRANT EXECUTE ON FUNCTION scientific_write() TO PUBLIC",
            "REVOKE EXECUTE ON FUNCTION scientific_write() FROM PUBLIC",
        ),
        ("GRANT CREATE ON DATABASE test TO PUBLIC", "REVOKE CREATE ON DATABASE test FROM PUBLIC"),
        ("GRANT inherited_writer TO old_app", "REVOKE inherited_writer FROM old_app"),
    ],
)
def test_effective_public_and_inherited_write_paths_invalidate_exclusion(
    grant: str, revoke: str
) -> None:
    """Effective access through columns, sequences, functions, databases and roles is detected."""
    with PostgresContainer("postgres:16") as postgres:
        asyncio.run(
            _exercise_effective_access(postgres.get_connection_url(driver=None), grant, revoke)
        )


async def _exercise_effective_access(dsn: str, grant: str, revoke: str) -> None:
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    try:
        async with pool.acquire() as admin:
            await admin.execute("CREATE ROLE old_app LOGIN")
            await admin.execute("CREATE ROLE new_app LOGIN")
            await admin.execute("CREATE ROLE inherited_writer")
            await admin.execute("CREATE TABLE scientific_values(value integer)")
            await admin.execute("CREATE SEQUENCE scientific_sequence")
            await admin.execute(
                "CREATE FUNCTION scientific_write() RETURNS void LANGUAGE sql "
                "SECURITY DEFINER AS 'INSERT INTO scientific_values VALUES (1)'"
            )
            await admin.execute("REVOKE EXECUTE ON FUNCTION scientific_write() FROM PUBLIC")
        fence = PostgresRoleExclusion(pool)
        await fence.exclude(("old_app",), "new_app")
        async with pool.acquire() as admin:
            await admin.execute(grant)
        with pytest.raises(ValueError, match="effective application access"):
            await fence.check(("old_app",), "new_app")
        async with pool.acquire() as admin:
            await admin.execute(revoke)
        await fence.check(("old_app",), "new_app")
    finally:
        await pool.close()


@pytest.mark.parametrize(
    "setup",
    [
        "ALTER ROLE old_app SUPERUSER",
        "ALTER ROLE old_app CREATEROLE",
        "ALTER ROLE new_app BYPASSRLS",
        "ALTER TABLE preserved OWNER TO new_app",
        "DROP ROLE old_app",
    ],
)
def test_unsafe_old_or_replacement_identity_refuses_without_partial_role_changes(
    setup: str,
) -> None:
    """Both identities must be dedicated; refusal rolls back earlier role changes in the batch."""
    with PostgresContainer("postgres:16") as postgres:
        asyncio.run(_exercise_unsafe_role(postgres.get_connection_url(driver=None), setup))


async def _exercise_unsafe_role(dsn: str, setup: str) -> None:
    async with asyncpg.create_pool(dsn) as pool:
        await pool.execute("CREATE ROLE old_app LOGIN")
        await pool.execute("CREATE ROLE new_app LOGIN")
        await pool.execute("CREATE TABLE preserved(value integer)")
        await pool.execute(setup)
        with pytest.raises(ValueError, match="missing, administrative or owns"):
            await PostgresRoleExclusion(pool).exclude(("old_app",), "new_app")
        assert await pool.fetchval("SELECT rolcanlogin FROM pg_roles WHERE rolname='new_app'")
        if setup != "DROP ROLE old_app":
            assert await pool.fetchval("SELECT rolcanlogin FROM pg_roles WHERE rolname='old_app'")
        assert await pool.fetchval("SELECT to_regclass('preserved') IS NOT NULL")
