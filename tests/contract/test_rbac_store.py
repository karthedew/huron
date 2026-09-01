"""Proves the Postgres RBAC schema and huron.pkg.rbac.roles.ROLES cannot drift.

Requires Docker (testcontainers spins up a real PostgreSQL). Not runnable in
every environment - see the module-level skip note in CI docs. Checked
against a database migrated with the project's own Alembic revisions:

1. the seeded ``roles``/``capabilities``/``role_capabilities`` rows
   reconstruct exactly the role definitions in ``ROLES`` - the seed
   (``migrations/versions/0002_rbac.py``) and the Python source of truth
   are written by hand in two different files and nothing else keeps them
   in sync;
2. ``grant_role`` validates in Python before ever writing, so its own
   negative cases never touch the database; every other assertion here
   pushes a real row through ``PostgresRbacStore``/``PostgresApiKeyStore``
   and reads it back, because that is the only way to catch a query that
   is syntactically fine but wrong against the actual schema - a foreign
   key the store doesn't handle, a column the store doesn't select;
3. the guard triggers (``role_bindings_guard``, ``service_accounts_kind_guard``)
   independently reject the same invalid rows the stores refuse in Python,
   exercised here through raw INSERTs that deliberately bypass the store,
   proving the triggers are a working backstop and not the only thing
   standing between a bad row and a stored grant.

The organization/project hierarchy has no Postgres-backed store of its own
yet, so the rows ``service_accounts.organization_id`` and
``api_keys.project_id`` foreign-key against are inserted directly with SQL
in this module's fixtures rather than through the (still in-memory) catalog.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from testcontainers.postgres import PostgresContainer

from huron.pkg.auth import ApiKeyRecord
from huron.pkg.catalog.ids import uuid7
from huron.pkg.rbac import ScopeType
from huron.pkg.rbac.roles import (
    CAPABILITIES,
    LAYER_SCOPED_CAPABILITIES,
    ROLES,
    PrincipalKindNotAllowed,
    ScopeNotBindable,
    compile_binding,
)
from huron.service.api.postgres_rbac import PostgresApiKeyStore, PostgresRbacStore
from huron.service.api.repository import ResourceNotFound

pytestmark = pytest.mark.contract

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


def _migrate(sqlalchemy_url: str) -> None:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", sqlalchemy_url)
    command.upgrade(config, "head")


def test_postgres_rbac_and_api_key_stores_against_a_migrated_database() -> None:
    with PostgresContainer("postgres:16") as postgres:
        _migrate(postgres.get_connection_url(driver="asyncpg"))
        asyncio.run(_assert_against(postgres.get_connection_url(driver=None)))


async def _assert_against(dsn: str) -> None:
    pool = await asyncpg.create_pool(dsn)
    try:
        await _assert_seed_matches_roles(pool)
        await _assert_seed_capabilities_match_the_python_capability_vocabulary(pool)
        await _assert_grant_role_validates_before_touching_the_database(pool)
        await _assert_grant_role_round_trips_through_bindings_for_and_bindings_at(pool)
        await _assert_service_account_round_trip(pool)
        await _assert_create_service_account_reports_a_missing_organization(pool)
        await _assert_policy_round_trip(pool)
        await _assert_api_key_round_trip(pool)
        await _assert_api_key_add_reports_a_missing_project(pool)
        await _assert_trigger_rejects_any_service_account_binding(pool)
        await _assert_trigger_rejects_platform_owner_at_organization_scope(pool)
        await _assert_trigger_rejects_a_malformed_principal_prefix(pool)
        await _assert_trigger_rejects_an_exact_duplicate_system_binding(pool)
        await _assert_trigger_rejects_a_service_account_row_over_a_user_principal(pool)
    finally:
        await pool.close()


# -- fixtures inserted directly, standing in for the not-yet-Postgres --------
# -- organization/project hierarchy -------------------------------------------


async def _insert_organization(pool: asyncpg.Pool, *, slug: str) -> UUID:
    organization_id = uuid7()
    now = datetime.now(UTC)
    await pool.execute(
        """
        INSERT INTO organizations (id, slug, title, created_at, updated_at)
        VALUES ($1, $2, $3, $4, $4)
        """,
        organization_id,
        slug,
        slug.title(),
        now,
    )
    return organization_id


async def _insert_project(pool: asyncpg.Pool, *, organization_id: UUID, slug: str) -> UUID:
    project_id = uuid7()
    now = datetime.now(UTC)
    await pool.execute(
        """
        INSERT INTO projects (id, organization_id, slug, title, classification_default,
                               created_at, updated_at)
        VALUES ($1, $2, $3, $4, 'open', $5, $5)
        """,
        project_id,
        organization_id,
        slug,
        slug.title(),
        now,
    )
    return project_id


# -- role/capability seed vs. the Python role model ---------------------------


async def _assert_seed_matches_roles(pool: asyncpg.Pool) -> None:
    role_rows = {row["code"]: row for row in await pool.fetch("SELECT * FROM roles")}
    assert set(role_rows) == set(ROLES)

    capability_rows = await pool.fetch(
        "SELECT role_code, capability_code, layers FROM role_capabilities"
    )
    by_role: dict[str, list[asyncpg.Record]] = {}
    for row in capability_rows:
        by_role.setdefault(row["role_code"], []).append(row)

    for role in ROLES.values():
        db_role = role_rows[role.code]
        assert set(db_role["allowed_principal_kinds"]) == role.allowed_principal_kinds, role.code
        assert {ScopeType(value) for value in db_role["bindable_scopes"]} == role.bindable_scopes, (
            role.code
        )

        rows = by_role.get(role.code, [])
        control_plane = {
            row["capability_code"]
            for row in rows
            if row["capability_code"] not in LAYER_SCOPED_CAPABILITIES
        }
        assert control_plane == role.capabilities, role.code

        db_layer_grants = {
            (
                row["capability_code"],
                frozenset(row["layers"]) if row["layers"] is not None else None,
            )
            for row in rows
            if row["capability_code"] in LAYER_SCOPED_CAPABILITIES
        }
        python_layer_grants = {(grant.capability, grant.layers) for grant in role.layer_grants}
        assert db_layer_grants == python_layer_grants, role.code


async def _assert_seed_capabilities_match_the_python_capability_vocabulary(
    pool: asyncpg.Pool,
) -> None:
    seeded = {row["code"] for row in await pool.fetch("SELECT code FROM capabilities")}
    assert seeded == CAPABILITIES


# -- grant_role: Python-side validation, then a real round trip -------------


async def _assert_grant_role_validates_before_touching_the_database(pool: asyncpg.Pool) -> None:
    store = PostgresRbacStore(pool)
    with pytest.raises(PrincipalKindNotAllowed):
        await store.grant_role(
            principal="sa:astro/feed",
            role_code="reader",
            scope_type=ScopeType.PROJECT,
            scope_id=uuid4(),
            created_by="contract-test",
        )
    with pytest.raises(ScopeNotBindable):
        await store.grant_role(
            principal="user:eve",
            role_code="platform_owner",
            scope_type=ScopeType.ORGANIZATION,
            scope_id=uuid4(),
            created_by="contract-test",
        )
    # Neither invalid grant reached role_bindings - the trigger never ran.
    count = await pool.fetchval(
        "SELECT count(*) FROM role_bindings WHERE created_by = 'contract-test'"
    )
    assert count == 0


async def _assert_grant_role_round_trips_through_bindings_for_and_bindings_at(
    pool: asyncpg.Pool,
) -> None:
    store = PostgresRbacStore(pool)
    project_id = uuid4()
    principal = "user:diana"

    granted = await store.grant_role(
        principal=principal,
        role_code="developer",
        scope_type=ScopeType.PROJECT,
        scope_id=project_id,
        created_by="contract-test",
    )
    assert granted.role_code == "developer"
    assert granted.scope_id == project_id

    expected = set(
        compile_binding(
            "developer",
            principal_identifier=principal,
            principal_kind="user",
            scope_type=ScopeType.PROJECT,
            scope_id=project_id,
        )
    )
    actual = set(await store.bindings_for(frozenset({principal})))
    assert actual == expected

    at_scope = await store.bindings_at(ScopeType.PROJECT, project_id)
    assert [item.id for item in at_scope] == [granted.id]
    assert at_scope[0].principal == principal
    assert at_scope[0].role_code == "developer"

    fetched = await store.get_role_binding(granted.id)
    assert fetched == granted

    revoked = await store.revoke_role(granted.id)
    assert revoked.id == granted.id
    assert await store.bindings_for(frozenset({principal})) == ()
    with pytest.raises(ResourceNotFound):
        await store.get_role_binding(granted.id)


# -- service accounts ----------------------------------------------------------


async def _assert_service_account_round_trip(pool: asyncpg.Pool) -> None:
    store = PostgresRbacStore(pool)
    organization_id = await _insert_organization(pool, slug="astro-sa")

    account = await store.create_service_account(
        organization_id,
        name="pipeline-runner",
        subject="astro-sa/pipeline-runner",
        created_by="contract-test",
    )
    assert account.organization_id == organization_id
    assert account.subject == "astro-sa/pipeline-runner"

    fetched = await store.get_service_account(account.principal_id)
    assert fetched == account

    listed = await store.list_service_accounts(organization_id)
    assert [item.principal_id for item in listed] == [account.principal_id]

    with pytest.raises(ResourceNotFound):
        await store.get_service_account(uuid4())


async def _assert_create_service_account_reports_a_missing_organization(
    pool: asyncpg.Pool,
) -> None:
    store = PostgresRbacStore(pool)
    with pytest.raises(ResourceNotFound):
        await store.create_service_account(
            uuid4(), name="orphan", subject="nowhere/orphan", created_by="contract-test"
        )


# -- policies -------------------------------------------------------------------


async def _assert_policy_round_trip(pool: asyncpg.Pool) -> None:
    store = PostgresRbacStore(pool)
    organization_id = await _insert_organization(pool, slug="astro-policy")

    policy = await store.create_policy(
        policy_type="retention", name="raw-90d", spec={"days": 90}, created_by="contract-test"
    )
    assert policy.spec == {"days": 90}

    attachment = await store.attach_policy(
        policy.id,
        scope_type=ScopeType.ORGANIZATION,
        scope_id=organization_id,
        attached_by="contract-test",
    )
    assert attachment.policy_id == policy.id

    listed = await store.list_policies()
    assert policy.id in {item.id for item in listed}

    with pytest.raises(ResourceNotFound):
        await store.attach_policy(
            uuid4(),
            scope_type=ScopeType.ORGANIZATION,
            scope_id=organization_id,
            attached_by="contract-test",
        )


# -- API keys ---------------------------------------------------------------


async def _assert_api_key_round_trip(pool: asyncpg.Pool) -> None:
    store = PostgresApiKeyStore(pool)
    organization_id = await _insert_organization(pool, slug="astro-keys")
    project_id = await _insert_project(pool, organization_id=organization_id, slug="survey")

    record = ApiKeyRecord(
        key_id="contracttestkey",
        subject="diana",
        name="diana-laptop",
        secret_sha256="0" * 64,
        scopes=frozenset({"read"}),
        project_id=str(project_id),
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    await store.add(record)

    fetched = await store.get(record.key_id)
    assert fetched == record

    await store.touch_last_used(record.key_id)
    last_used_at = await pool.fetchval(
        "SELECT last_used_at FROM api_keys WHERE key_id = $1", record.key_id
    )
    assert last_used_at is not None

    assert await store.get("does-not-exist") is None


async def _assert_api_key_add_reports_a_missing_project(pool: asyncpg.Pool) -> None:
    store = PostgresApiKeyStore(pool)
    record = ApiKeyRecord(
        key_id="orphankey",
        subject="diana",
        name="orphan",
        secret_sha256="1" * 64,
        scopes=frozenset({"read"}),
        project_id=str(uuid4()),
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    with pytest.raises(ResourceNotFound):
        await store.add(record)


# -- triggers: the backstop for rows a store never wrote ----------------------


async def _assert_trigger_rejects_any_service_account_binding(pool: asyncpg.Pool) -> None:
    with pytest.raises(asyncpg.exceptions.RaiseError):
        await pool.execute(
            """
            INSERT INTO role_bindings
                (id, principal, role_code, scope_type, scope_id, effect, created_by, created_at)
            VALUES ($1, 'sa:astro/feed', 'reader', 'PROJECT', $2, 'ALLOW', 'trigger-test', now())
            """,
            uuid7(),
            uuid4(),
        )


async def _assert_trigger_rejects_platform_owner_at_organization_scope(pool: asyncpg.Pool) -> None:
    with pytest.raises(asyncpg.exceptions.RaiseError):
        await pool.execute(
            """
            INSERT INTO role_bindings
                (id, principal, role_code, scope_type, scope_id, effect, created_by, created_at)
            VALUES
                ($1, 'user:eve', 'platform_owner', 'ORGANIZATION', $2, 'ALLOW',
                 'trigger-test', now())
            """,
            uuid7(),
            uuid4(),
        )


async def _assert_trigger_rejects_a_malformed_principal_prefix(pool: asyncpg.Pool) -> None:
    """A principal with no ``user:``/``group:``/``sa:`` prefix, at a scope
    (SYSTEM) and role (platform_owner) that would otherwise be entirely
    valid - isolating the prefix check from the kind and scope checks."""
    with pytest.raises(asyncpg.exceptions.RaiseError):
        await pool.execute(
            """
            INSERT INTO role_bindings
                (id, principal, role_code, scope_type, scope_id, effect, created_by, created_at)
            VALUES ($1, 'eve', 'platform_owner', 'SYSTEM', NULL, 'ALLOW', 'trigger-test', now())
            """,
            uuid7(),
        )


async def _assert_trigger_rejects_an_exact_duplicate_system_binding(pool: asyncpg.Pool) -> None:
    insert = """
        INSERT INTO role_bindings
            (id, principal, role_code, scope_type, scope_id, effect, created_by, created_at)
        VALUES ($1, 'user:frank', 'platform_owner', 'SYSTEM', NULL, 'ALLOW',
                'trigger-test', now())
    """
    await pool.execute(insert, uuid7())
    with pytest.raises(asyncpg.exceptions.UniqueViolationError):
        await pool.execute(insert, uuid7())


async def _assert_trigger_rejects_a_service_account_row_over_a_user_principal(
    pool: asyncpg.Pool,
) -> None:
    principal_id = uuid7()
    await pool.execute(
        """
        INSERT INTO principals (id, kind, subject, created_at) VALUES ($1, 'user', $2, now())
        """,
        principal_id,
        f"trigger-test-{principal_id}",
    )
    organization_id = await _insert_organization(pool, slug="astro-guard")
    with pytest.raises(asyncpg.exceptions.RaiseError):
        await pool.execute(
            """
            INSERT INTO service_accounts
                (principal_id, organization_id, name, created_by, created_at)
            VALUES ($1, $2, 'not-a-service-account', 'trigger-test', now())
            """,
            principal_id,
            organization_id,
        )
