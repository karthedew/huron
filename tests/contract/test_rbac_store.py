"""Proves the Postgres RBAC schema and huron.core.security.roles.ROLES cannot drift.

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
   standing between a bad row and a stored grant;
4. ``create_service_account`` inserts a principal and a service-account row
   in one transaction, so it can hit either of two different UNIQUE
   constraints - the organization already has this name, or some other
   principal already holds the derived subject - and each must come back as
   its own error rather than one misreporting the other.

The organization/project hierarchy has no Postgres-backed store of its own
yet, so the rows ``service_accounts.organization_id`` and
``api_keys.project_id`` foreign-key against are inserted directly with SQL
in this module's fixtures rather than through the (still in-memory) catalog.

Two more ``CHECK`` constraints pin ``policies.spec`` and
``role_bindings.conditions`` to their own top-level jsonb type - the two of
the fourteen ``0008`` columns whose tables live in this module's fixture
set rather than ``tests/contract/test_catalog_store.py``'s. Both get the
generic refuse-a-bare-scalar-or-array/accept-an-object pairing; neither is
one of the four columns that carries a design decision of its own.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from pydantic import BaseModel, ConfigDict
from testcontainers.postgres import PostgresContainer

from huron.applications.api.routes.v1.pagination import paginate
from huron.core.security.ports import ApiKeyWriter, RbacStore
from huron.core.security.apikeys import ApiKeyRecord
from huron.core.foundation.errors import ResourceNotFound
from huron.core.security.errors import UsernameTaken
from huron.core.foundation.identifiers import uuid7
from huron.core.security.types import Policy, RoleBindingRecord, ServiceAccount
from huron.core.metastore import InMemoryRbacStore, PostgresApiKeyStore, PostgresRbacStore
from huron.core.security.rules import ScopeType
from huron.core.security.roles import (
    CAPABILITIES,
    LAYER_SCOPED_CAPABILITIES,
    ROLES,
    PrincipalKindNotAllowed,
    ScopeNotBindable,
    compile_binding,
)

pytestmark = pytest.mark.contract

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


def _migrate(sqlalchemy_url: str) -> None:
    """Upgrades the target database to the latest Alembic migration head."""
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", sqlalchemy_url)
    command.upgrade(config, "head")


def test_the_postgres_rbac_and_api_key_stores_against_a_migrated_database() -> None:
    """The RBAC and API-key stores behave correctly against a real, migrated PostgreSQL database."""
    with PostgresContainer("postgres:16") as postgres:
        _migrate(postgres.get_connection_url(driver="asyncpg"))
        asyncio.run(_assert_against(postgres.get_connection_url(driver=None)))


def test_stores_conform_to_their_ports_structurally_not_by_inheritance() -> None:
    """Neither Postgres nor in-memory store inherits its Protocol; conformance stays structural.

    ``RbacStore`` and ``ApiKeyWriter`` now share a package with every
    implementation of them, which makes inheriting the Protocol a one-line
    temptation. Conformance must stay structural: an implementation that
    names the Protocol in its bases gets its signatures checked once at
    definition and stops being the independent conformer this module exists
    to compare against the in-memory reference.
    """
    assert RbacStore not in PostgresRbacStore.__mro__
    assert RbacStore not in InMemoryRbacStore.__mro__
    assert ApiKeyWriter not in PostgresApiKeyStore.__mro__


async def _assert_against(dsn: str) -> None:
    """Runs every RBAC and API-key store assertion against one connection pool."""
    pool = await asyncpg.create_pool(dsn)
    try:
        await _assert_seed_matches_roles(pool)
        await _assert_seed_capabilities_match_the_python_capability_vocabulary(pool)
        await _assert_grant_role_validates_before_touching_the_database(pool)
        await _assert_grant_role_round_trips_through_bindings_for_and_bindings_at(pool)
        await _assert_service_account_round_trip(pool)
        await _assert_create_service_account_reports_a_missing_organization(pool)
        await _assert_create_service_account_reports_a_subject_collision(pool)
        await _assert_disable_service_account_is_idempotent(pool)
        await _assert_policy_round_trip(pool)
        await _assert_api_key_round_trip(pool)
        await _assert_api_key_add_reports_a_missing_project(pool)
        await _assert_trigger_rejects_any_service_account_binding(pool)
        await _assert_trigger_rejects_platform_owner_at_organization_scope(pool)
        await _assert_trigger_rejects_a_malformed_principal_prefix(pool)
        await _assert_trigger_rejects_an_exact_duplicate_system_binding(pool)
        await _assert_trigger_rejects_a_service_account_row_over_a_user_principal(pool)
        await _assert_role_delete_is_refused_while_a_binding_still_names_it(pool)
        await _assert_capability_delete_is_refused_while_a_role_still_grants_it(pool)
        await _assert_role_delete_cascades_its_capability_rows_once_its_bindings_are_gone(pool)
        await _assert_policies_and_role_bindings_jsonb_shape(pool)
        await _assert_store_order_agrees_between_backends_and_matches_the_boundary_key(pool)
        await _assert_postgres_orders_policy_names_by_byte_order_not_locale_order(pool)
        await _assert_a_duplicate_policy_name_is_walked_exactly_once(pool)
    finally:
        await pool.close()


# -- fixtures inserted directly, standing in for the not-yet-Postgres --------
# -- organization/project hierarchy -------------------------------------------


async def _insert_organization(pool: asyncpg.Pool, *, slug: str) -> UUID:
    """Inserts an organization row directly, standing in for the not-yet-Postgres catalog store."""
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


async def _insert_user_principal(pool: asyncpg.Pool, *, subject: str) -> UUID:
    """Inserts a principal row of kind 'user' directly, standing in for the auth store."""
    principal_id = uuid7()
    await pool.execute(
        """
        INSERT INTO principals (id, kind, subject, display_name, created_at)
        VALUES ($1, 'user', $2, $2, now())
        """,
        principal_id,
        subject,
    )
    return principal_id


async def _insert_project(pool: asyncpg.Pool, *, organization_id: UUID, slug: str) -> UUID:
    """Inserts a project row directly, standing in for the not-yet-Postgres catalog store."""
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
    """The seeded roles table matches ROLES exactly in kinds, scopes, and every capability grant."""
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
    """The seeded capabilities table holds exactly the codes in CAPABILITIES."""
    seeded = {row["code"] for row in await pool.fetch("SELECT code FROM capabilities")}
    assert seeded == CAPABILITIES


# -- grant_role: Python-side validation, then a real round trip -------------


async def _assert_grant_role_validates_before_touching_the_database(pool: asyncpg.Pool) -> None:
    """``grant_role`` refuses a bad principal kind or scope before writing to ``role_bindings``."""
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
    """A granted binding is found by every read method and gone from all of them once revoked."""
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
    """A service account round-trips through get and list; an unknown id raises ResourceNotFound."""
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
    """``create_service_account`` raises ResourceNotFound for an unknown organization id."""
    store = PostgresRbacStore(pool)
    with pytest.raises(ResourceNotFound):
        await store.create_service_account(
            uuid4(), name="orphan", subject="nowhere/orphan", created_by="contract-test"
        )


async def _assert_create_service_account_reports_a_subject_collision(pool: asyncpg.Pool) -> None:
    """A subject some other principal already holds is refused as UsernameTaken.

    The derived subject is ``{organization slug}/{name}``; a password user
    provisioned with exactly that username collides with it on the
    ``principals.subject`` constraint - a different conflict from another
    service account in the same organization sharing this ``name``, and
    reported with a different code.
    """
    store = PostgresRbacStore(pool)
    organization_id = await _insert_organization(pool, slug="astro-subject")
    await _insert_user_principal(pool, subject="astro-subject/taken")
    with pytest.raises(UsernameTaken):
        await store.create_service_account(
            organization_id,
            name="taken",
            subject="astro-subject/taken",
            created_by="contract-test",
        )


async def _assert_disable_service_account_is_idempotent(pool: asyncpg.Pool) -> None:
    """A second ``disable_service_account`` call returns the original instant, unchanged."""
    store = PostgresRbacStore(pool)
    organization_id = await _insert_organization(pool, slug="astro-disable")
    account = await store.create_service_account(
        organization_id,
        name="pipeline-disable",
        subject="astro-disable/pipeline-disable",
        created_by="contract-test",
    )

    first = await store.disable_service_account(account.principal_id, disabled_at=datetime.now(UTC))
    second = await store.disable_service_account(
        account.principal_id, disabled_at=datetime.now(UTC) + timedelta(days=1)
    )
    assert first.disabled_at is not None
    assert second.disabled_at == first.disabled_at

    with pytest.raises(ResourceNotFound):
        await store.disable_service_account(uuid4(), disabled_at=datetime.now(UTC))


# -- policies -------------------------------------------------------------------


async def _assert_policy_round_trip(pool: asyncpg.Pool) -> None:
    """A created policy round-trips through attach and list, and attaching an unknown id fails."""
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
    """An API key round-trips through get; touch_last_used stamps it; an unknown key is None."""
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
    """``add`` raises ResourceNotFound for an API key naming a project id that doesn't exist."""
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
    """The guard trigger refuses any role binding naming a service-account principal."""
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
    """The guard trigger refuses ``platform_owner`` bound at ORGANIZATION scope."""
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
    """The guard trigger refuses a principal with no kind prefix, even at an otherwise valid scope.

    A principal with no ``user:``/``group:``/``sa:`` prefix, at a scope
    (SYSTEM) and role (platform_owner) that would otherwise be entirely
    valid - isolating the prefix check from the kind and scope checks.
    """
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
    """A duplicate SYSTEM-scope binding for one principal and role is refused outright."""
    insert = """
        INSERT INTO role_bindings
            (id, principal, role_code, scope_type, scope_id, effect, created_by, created_at)
        VALUES ($1, 'user:frank', 'platform_owner', 'SYSTEM', NULL, 'ALLOW',
                'trigger-test', now())
    """
    await pool.execute(insert, uuid7())
    with pytest.raises(asyncpg.exceptions.UniqueViolationError):
        await pool.execute(insert, uuid7())


async def _insert_role(
    pool: asyncpg.Pool, *, code: str, bindable_scopes: list[str] | None = None
) -> None:
    """Inserts a role row directly, allowing only 'user' principals at the given bindable scopes."""
    await pool.execute(
        """
        INSERT INTO roles (code, title, allowed_principal_kinds, bindable_scopes)
        VALUES ($1, $1, ARRAY['user'], $2)
        """,
        code,
        bindable_scopes or ["SYSTEM"],
    )


async def _insert_capability(pool: asyncpg.Pool, *, code: str) -> None:
    """Inserts a capability row directly, by code alone."""
    await pool.execute("INSERT INTO capabilities (code) VALUES ($1)", code)


# -- referential actions on the role catalog: the one place a parent key is --
# -- natural text and parent rows are really deleted -------------------------


async def _assert_role_delete_is_refused_while_a_binding_still_names_it(
    pool: asyncpg.Pool,
) -> None:
    """Deleting a role is refused by its foreign key while a role_bindings row still names it."""
    role_code = "contract_test_role_bound"
    await _insert_role(pool, code=role_code)
    await pool.execute(
        """
        INSERT INTO role_bindings
            (id, principal, role_code, scope_type, scope_id, effect, created_by, created_at)
        VALUES ($1, 'user:role-delete-fk', $2, 'SYSTEM', NULL, 'ALLOW', 'contract-test', now())
        """,
        uuid7(),
        role_code,
    )
    with pytest.raises(asyncpg.exceptions.ForeignKeyViolationError):
        await pool.execute("DELETE FROM roles WHERE code = $1", role_code)

    # The refused delete leaves both rows in place - remove them so this
    # helper's fixture data cannot influence assertions that run after it.
    await pool.execute("DELETE FROM role_bindings WHERE role_code = $1", role_code)
    await pool.execute("DELETE FROM roles WHERE code = $1", role_code)


async def _assert_capability_delete_is_refused_while_a_role_still_grants_it(
    pool: asyncpg.Pool,
) -> None:
    """Deleting a capability is refused by its foreign key while a role still grants it."""
    role_code = "contract_test_role_granting"
    capability_code = "contract_test.capability_granted"
    await _insert_role(pool, code=role_code)
    await _insert_capability(pool, code=capability_code)
    await pool.execute(
        "INSERT INTO role_capabilities (role_code, capability_code) VALUES ($1, $2)",
        role_code,
        capability_code,
    )
    with pytest.raises(asyncpg.exceptions.ForeignKeyViolationError):
        await pool.execute("DELETE FROM capabilities WHERE code = $1", capability_code)

    # The refused delete leaves all three rows in place - remove them so this
    # helper's fixture data cannot influence assertions that run after it.
    await pool.execute(
        "DELETE FROM role_capabilities WHERE role_code = $1 AND capability_code = $2",
        role_code,
        capability_code,
    )
    await pool.execute("DELETE FROM roles WHERE code = $1", role_code)
    await pool.execute("DELETE FROM capabilities WHERE code = $1", capability_code)


async def _assert_role_delete_cascades_its_capability_rows_once_its_bindings_are_gone(
    pool: asyncpg.Pool,
) -> None:
    """Deleting a role, once its bindings are gone, cascades to its role_capabilities rows."""
    role_code = "contract_test_role_retired"
    capability_code = "contract_test.capability_retired"
    binding_id = uuid7()
    await _insert_role(pool, code=role_code)
    await _insert_capability(pool, code=capability_code)
    await pool.execute(
        "INSERT INTO role_capabilities (role_code, capability_code) VALUES ($1, $2)",
        role_code,
        capability_code,
    )
    await pool.execute(
        """
        INSERT INTO role_bindings
            (id, principal, role_code, scope_type, scope_id, effect, created_by, created_at)
        VALUES ($1, 'user:role-delete-cascade', $2, 'SYSTEM', NULL, 'ALLOW',
                'contract-test', now())
        """,
        binding_id,
        role_code,
    )

    # 0004, 0006 and 0007 each retire a role the same way: delete its bindings
    # first, deliberately, then the role - which is the positive control that
    # proves role_capabilities_role_code_fkey's ON DELETE CASCADE is real
    # rather than the delete merely having failed silently for lack of rows.
    await pool.execute("DELETE FROM role_bindings WHERE id = $1", binding_id)
    await pool.execute("DELETE FROM roles WHERE code = $1", role_code)

    remaining = await pool.fetchval(
        "SELECT count(*) FROM role_capabilities WHERE role_code = $1", role_code
    )
    assert remaining == 0


async def _assert_trigger_rejects_a_service_account_row_over_a_user_principal(
    pool: asyncpg.Pool,
) -> None:
    """The guard trigger refuses a service_accounts row naming a 'user'-kind principal."""
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


# -- jsonb top-level type constraints: policies.spec, role_bindings.conditions ---

_BAD_OBJECT_LITERALS = ('"just a string"', "42", "true", "[]", "null")


@dataclass(frozen=True)
class _JsonbShapeColumn:
    """One jsonb column's refused-and-permitted literal pair, checked against a fixture row.

    One jsonb column's refused/permitted pair, checked by ``UPDATE`` against
    a fixture row already holding a legal value - `where`/`key` locate that
    row, with `key` bound starting at `$2`.
    """

    table: str
    column: str
    where: str
    key: tuple[object, ...]
    accepted: str = "{}"
    accepted_populated: str = '{"contract_test_key": "contract_test_value"}'
    bad: tuple[str, ...] = _BAD_OBJECT_LITERALS


async def _insert_policy_for_jsonb_shape(pool: asyncpg.Pool) -> UUID:
    """Inserts a policy row directly, with an empty jsonb object as its spec."""
    policy_id = uuid7()
    await pool.execute(
        """
        INSERT INTO policies (id, policy_type, name, spec, created_by, created_at)
        VALUES ($1, 'jsonb_shape', 'jsonb-shape-policy', $2::jsonb, 'contract-test', now())
        """,
        policy_id,
        json.dumps({}),
    )
    return policy_id


async def _insert_role_binding_for_jsonb_shape(pool: asyncpg.Pool) -> UUID:
    """Inserts a role and a role_bindings row directly, its conditions an empty jsonb object."""
    role_code = "contract_test_role_jsonb_shape"
    await _insert_role(pool, code=role_code)
    binding_id = uuid7()
    await pool.execute(
        """
        INSERT INTO role_bindings
            (id, principal, role_code, scope_type, scope_id, effect, conditions, created_by,
             created_at)
        VALUES ($1, 'user:jsonb-shape', $2, 'SYSTEM', NULL, 'ALLOW', $3::jsonb,
                'contract-test', now())
        """,
        binding_id,
        role_code,
        json.dumps({}),
    )
    return binding_id


async def _assert_policies_and_role_bindings_jsonb_shape(pool: asyncpg.Pool) -> None:
    """``policies.spec`` and ``role_bindings.conditions`` each refuse a non-object jsonb value.

    ``policies.spec`` and ``role_bindings.conditions`` each refuse a bare
    string, number, boolean, array and JSON ``null``, and accept both an
    empty and a populated object - the same pairing
    ``tests/contract/test_catalog_store.py`` applies to its own twelve jsonb
    columns.
    """
    cases = (
        _JsonbShapeColumn(
            table="policies",
            column="spec",
            where="id = $2",
            key=(await _insert_policy_for_jsonb_shape(pool),),
        ),
        _JsonbShapeColumn(
            table="role_bindings",
            column="conditions",
            where="id = $2",
            key=(await _insert_role_binding_for_jsonb_shape(pool),),
        ),
    )
    for case in cases:
        update = f"UPDATE {case.table} SET {case.column} = $1::jsonb WHERE {case.where}"
        for literal in case.bad:
            with pytest.raises(asyncpg.exceptions.CheckViolationError):
                await pool.execute(update, literal, *case.key)
        await pool.execute(update, case.accepted, *case.key)
        await pool.execute(update, case.accepted_populated, *case.key)


# -- ordering: the keyset cursor's assumption about store order --------------


def _policy_key(item: Policy) -> tuple[str, str]:
    """Returns the (name, id) tuple that orders policies the way the HTTP boundary's cursor does."""
    return (item.name, str(item.id))


def _service_account_key(item: ServiceAccount) -> tuple[str]:
    """Returns the (name,) tuple that orders service accounts the way the cursor does."""
    return (item.name,)


def _binding_key(item: RoleBindingRecord) -> tuple[str, str]:
    """Returns the (principal, role_code) tuple that orders bindings the way the cursor does."""
    return (item.principal, item.role_code)


async def _insert_policy_row(pool: asyncpg.Pool, record: Policy) -> None:
    """Inserts a policy row directly with every field controlled, for testing store order."""
    await pool.execute(
        """
        INSERT INTO policies (id, policy_type, name, spec, created_by, created_at)
        VALUES ($1, $2, $3, $4::jsonb, $5, $6)
        """,
        record.id,
        record.policy_type,
        record.name,
        json.dumps(record.spec),
        record.created_by,
        record.created_at,
    )


async def _assert_store_order_agrees_between_backends_and_matches_the_boundary_key(
    pool: asyncpg.Pool,
) -> None:
    """The in-memory and Postgres stores list policies, accounts, and bindings in the same order.

    The one property no other assertion in this module checks: that the
    two backends return records from the same collection in the same
    sequence, and that the sequence is what sorting the records by the HTTP
    boundary's own cursor key would produce - for all three collections
    ``RbacStore`` orders.
    """
    memory_store = InMemoryRbacStore()
    postgres_store = PostgresRbacStore(pool)

    names = ["zebra", "apple", "mango"]

    memory_policies = [
        await memory_store.create_policy(
            policy_type="retention", name=f"{name}-policy", spec={}, created_by="contract-test"
        )
        for name in names
    ]
    postgres_policies = [
        await postgres_store.create_policy(
            policy_type="retention", name=f"{name}-policy", spec={}, created_by="contract-test"
        )
        for name in names
    ]
    memory_policy_ids = {record.id for record in memory_policies}
    postgres_policy_ids = {record.id for record in postgres_policies}
    memory_listed_policies = [
        item for item in await memory_store.list_policies() if item.id in memory_policy_ids
    ]
    postgres_listed_policies = [
        item for item in await postgres_store.list_policies() if item.id in postgres_policy_ids
    ]
    assert [item.name for item in memory_listed_policies] == [
        item.name for item in postgres_listed_policies
    ]
    assert memory_listed_policies == sorted(memory_policies, key=_policy_key)
    assert postgres_listed_policies == sorted(postgres_policies, key=_policy_key)

    # ``service_accounts.name`` is restricted to lowercase, digits and
    # hyphens, so case and accents can't probe the collation here - a
    # hyphen against an adjacent character can: under the default locale it
    # is treated as ignorable, reordering these three relative to byte order.
    account_names = ["a-count", "a1-count", "ab-count"]
    memory_organization_id = uuid4()
    postgres_organization_id = await _insert_organization(pool, slug="astro-ordering")
    memory_accounts = [
        await memory_store.create_service_account(
            memory_organization_id,
            name=name,
            subject=f"astro-ordering-memory/{name}",
            created_by="contract-test",
        )
        for name in account_names
    ]
    postgres_accounts = [
        await postgres_store.create_service_account(
            postgres_organization_id,
            name=name,
            subject=f"astro-ordering-postgres/{name}",
            created_by="contract-test",
        )
        for name in account_names
    ]
    memory_listed_accounts = await memory_store.list_service_accounts(memory_organization_id)
    postgres_listed_accounts = await postgres_store.list_service_accounts(postgres_organization_id)
    assert [item.name for item in memory_listed_accounts] == [
        item.name for item in postgres_listed_accounts
    ]
    assert memory_listed_accounts == sorted(memory_accounts, key=_service_account_key)
    assert postgres_listed_accounts == sorted(postgres_accounts, key=_service_account_key)

    principals = ["user:zoe", "user:amy", "user:mia"]
    memory_project_id = uuid4()
    postgres_project_id = uuid4()
    memory_bindings = [
        await memory_store.grant_role(
            principal=principal,
            role_code="developer",
            scope_type=ScopeType.PROJECT,
            scope_id=memory_project_id,
            created_by="contract-test",
        )
        for principal in principals
    ]
    postgres_bindings = [
        await postgres_store.grant_role(
            principal=principal,
            role_code="developer",
            scope_type=ScopeType.PROJECT,
            scope_id=postgres_project_id,
            created_by="contract-test",
        )
        for principal in principals
    ]
    memory_listed_bindings = await memory_store.bindings_at(ScopeType.PROJECT, memory_project_id)
    postgres_listed_bindings = await postgres_store.bindings_at(
        ScopeType.PROJECT, postgres_project_id
    )
    assert [item.principal for item in memory_listed_bindings] == [
        item.principal for item in postgres_listed_bindings
    ]
    assert memory_listed_bindings == sorted(memory_bindings, key=_binding_key)
    assert postgres_listed_bindings == sorted(postgres_bindings, key=_binding_key)


async def _assert_postgres_orders_policy_names_by_byte_order_not_locale_order(
    pool: asyncpg.Pool,
) -> None:
    """``list_policies`` orders names by raw byte value, not the cluster's folding collation.

    This cluster's default collation folds case and treats a hyphen and
    an accent as insignificant; ``COLLATE "C"`` must override that so the
    store's order is exactly Python's ``str`` order, which is the order the
    keyset cursor's comparison assumes.
    """
    store = PostgresRbacStore(pool)
    now = datetime.now(UTC)
    names = ["pii-mask", "piimask", "PII-mask", "cafe", "café"]
    records = [Policy(uuid7(), "retention", name, {}, "contract-test", now) for name in names]
    for record in records:
        await _insert_policy_row(pool, record)

    ids = {record.id for record in records}
    listed = [item for item in await store.list_policies() if item.id in ids]
    assert [item.name for item in listed] == sorted(names)


class _PolicyIdView(BaseModel):
    """A minimal view exposing only a policy's id, for driving this module's keyset paginator."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID


async def _assert_a_duplicate_policy_name_is_walked_exactly_once(pool: asyncpg.Pool) -> None:
    """The keyset paginator visits every policy exactly once even when two rows share a name.

    Two policies sharing a name have no natural tiebreak but ``id``.
    Inserting the lexicographically later id first means an id-less order
    would come back in insertion order - the wrong order for the cursor's
    key - and walking that order at ``limit=1`` would skip the row the
    cursor's ``>`` comparison can no longer see.
    """
    store = PostgresRbacStore(pool)
    now = datetime.now(UTC)
    high = Policy(
        UUID("ffffffff-ffff-ffff-ffff-fffffffffffe"),
        "retention",
        "shared-name",
        {},
        "contract-test",
        now,
    )
    low = Policy(
        UUID("00000000-0000-0000-0000-000000000001"),
        "retention",
        "shared-name",
        {},
        "contract-test",
        now,
    )
    solo = Policy(uuid7(), "retention", "solo-name", {}, "contract-test", now)
    expected = [item.id for item in sorted((high, low, solo), key=_policy_key)]

    memory_store = InMemoryRbacStore()
    for record in (high, low, solo):  # high inserted first, on purpose
        memory_store._policies[record.id] = record
    assert [item.id for item in await memory_store.list_policies()] == expected

    for record in (high, low, solo):  # high inserted first, on purpose
        await _insert_policy_row(pool, record)

    ids = {high.id, low.id, solo.id}
    listed = [item for item in await store.list_policies() if item.id in ids]

    seen: list[UUID] = []
    after: str | None = None
    while True:
        page = paginate(listed, _PolicyIdView, key=_policy_key, limit=1, after=after)
        if not page.items:
            break
        seen.append(page.items[0].id)
        after = page.next_cursor
        if after is None:
            break

    assert seen == expected
