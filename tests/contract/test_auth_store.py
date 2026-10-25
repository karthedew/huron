"""Real PostgreSQL principal identity and API-key revocation contracts."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from testcontainers.postgres import PostgresContainer

from huron.core.security.apikeys import ApiKeyRecord
from huron.core.security.oidc import OidcUser
from huron.core.security.principals import PrincipalSubjectExists
from huron.core.foundation.identifiers import uuid7
from huron.core.metastore import (
    PostgresApiKeyStore,
    PostgresPrincipalStore,
)

pytestmark = pytest.mark.contract

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


def _migrate(sqlalchemy_url: str) -> None:
    """Upgrades the target database to the latest Alembic migration head."""
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", sqlalchemy_url)
    command.upgrade(config, "head")


def test_the_postgres_auth_stores_against_a_migrated_database() -> None:
    """The auth stores behave correctly against a freshly migrated PostgreSQL 16 database."""
    with PostgresContainer("postgres:16") as postgres:
        _migrate(postgres.get_connection_url(driver="asyncpg"))
        asyncio.run(_assert_against(postgres.get_connection_url(driver=None)))


async def _assert_against(dsn: str) -> None:
    """Runs every auth store assertion against one connection pool."""
    pool = await asyncpg.create_pool(dsn)
    try:
        await _assert_api_key_revoke_all_for_ignores_owner_kind(pool)
        await _assert_upsert_oidc_user_creates_then_updates_without_duplicating(pool)
        await _assert_upsert_oidc_user_refuses_a_subject_another_identity_holds(pool)
        await _assert_disable_sets_disabled_at_and_returns_none_for_an_unknown_id(pool)
        await _assert_get_by_id_returns_every_kind_and_none_when_absent(pool)
    finally:
        await pool.close()


# -- fixtures: principals inserted directly, for scenarios the store's own
# -- write methods don't build (a disabled row, a bare service account) ------


async def _insert_user_principal(
    pool: asyncpg.Pool, *, subject: str, disabled: bool = False
) -> UUID:
    """Inserts a principal row of kind 'user' directly, optionally already disabled."""
    principal_id = uuid7()
    await pool.execute(
        """
        INSERT INTO principals (id, kind, subject, display_name, created_at, disabled_at)
        VALUES ($1, 'user', $2, $2, now(), $3)
        """,
        principal_id,
        subject,
        datetime.now(UTC) if disabled else None,
    )
    return principal_id


async def _insert_service_account_principal(pool: asyncpg.Pool, *, subject: str) -> UUID:
    """Inserts a principal row of kind 'service_account' directly, with no other table touched."""
    principal_id = uuid7()
    await pool.execute(
        """
        INSERT INTO principals (id, kind, subject, created_at)
        VALUES ($1, 'service_account', $2, now())
        """,
        principal_id,
        subject,
    )
    return principal_id


# -- api keys ---------------------------------------------------------------


async def _assert_api_key_revoke_all_for_ignores_owner_kind(pool: asyncpg.Pool) -> None:
    """``revoke_all_for`` revokes a subject's key whatever its ``owner_kind``.

    A user-owned key and a service-account-owned key belong to two
    different subjects; revoking one subject's keys must not filter by
    ``owner_kind`` and must not touch the other subject's key.
    """
    store = PostgresApiKeyStore(pool)
    user_subject, service_account_subject = "contract-key-user", "contract-key-sa"
    expires_at = datetime.now(UTC) + timedelta(days=1)

    user_key = ApiKeyRecord(
        key_id="contract-revoke-user-key",
        subject=user_subject,
        name="user key",
        secret_sha256="a" * 64,
        scopes=frozenset({"read"}),
        project_id=None,
        expires_at=expires_at,
        owner_kind="user",
    )
    service_account_key = ApiKeyRecord(
        key_id="contract-revoke-sa-key",
        subject=service_account_subject,
        name="service account key",
        secret_sha256="b" * 64,
        scopes=frozenset({"read"}),
        project_id=None,
        expires_at=expires_at,
        owner_kind="service_account",
    )
    await store.add(user_key)
    await store.add(service_account_key)

    revoked_at = datetime.now(UTC)
    count = await store.revoke_all_for(user_subject, revoked_at)
    assert count == 1

    revoked = await store.get(user_key.key_id)
    untouched = await store.get(service_account_key.key_id)
    assert revoked is not None and revoked.revoked_at == revoked_at
    assert untouched is not None and untouched.revoked_at is None


# -- principals: identity upsert, disablement, and lookup ------------


async def _assert_upsert_oidc_user_creates_then_updates_without_duplicating(
    pool: asyncpg.Pool,
) -> None:
    """``upsert_oidc_user`` updates the same row on a second login rather than duplicating it."""
    store = PostgresPrincipalStore(pool)
    first_login = OidcUser(
        idp_subject="idp-contract-carol",
        display_name="Carol",
        email="carol@example.org",
        groups=frozenset(),
    )
    created = await store.upsert_oidc_user(first_login)
    assert created.subject == "idp-contract-carol"
    assert created.display_name == "Carol"
    assert created.kind == "user"

    renamed_login = OidcUser(
        idp_subject="idp-contract-carol",
        display_name="Carol Renamed",
        email="carol@example.org",
        groups=frozenset(),
    )
    updated = await store.upsert_oidc_user(renamed_login)
    assert updated.id == created.id
    assert updated.display_name == "Carol Renamed"

    count = await pool.fetchval(
        "SELECT count(*) FROM principals WHERE idp_subject = $1", "idp-contract-carol"
    )
    assert count == 1


async def _assert_upsert_oidc_user_refuses_a_subject_another_identity_holds(
    pool: asyncpg.Pool,
) -> None:
    """A first-ever OIDC login is refused, not auto-linked, when its subject is a local username."""
    store = PostgresPrincipalStore(pool)
    await _insert_user_principal(pool, subject="contract-collide-s")

    with pytest.raises(PrincipalSubjectExists):
        await store.upsert_oidc_user(
            OidcUser(
                idp_subject="contract-collide-s",
                display_name="Impostor",
                email=None,
                groups=frozenset(),
            )
        )

    count = await pool.fetchval(
        "SELECT count(*) FROM principals WHERE subject = $1", "contract-collide-s"
    )
    assert count == 1

    existing_id = await _insert_user_principal(pool, subject="contract-existing-id")
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr("huron.core.metastore.principals.uuid7", lambda: existing_id)
        with pytest.raises(asyncpg.UniqueViolationError) as refused:
            await store.upsert_oidc_user(
                OidcUser("contract-new-subject", "New User", None, frozenset())
            )
    assert refused.value.constraint_name == "principals_pkey"
    assert (
        await pool.fetchval(
            "SELECT count(*) FROM principals WHERE subject = $1", "contract-new-subject"
        )
        == 0
    )


async def _assert_disable_sets_disabled_at_and_returns_none_for_an_unknown_id(
    pool: asyncpg.Pool,
) -> None:
    """``disable`` persists ``disabled_at`` and returns None for an unknown id."""
    store = PostgresPrincipalStore(pool)
    principal_id = await _insert_user_principal(pool, subject="contract-disable-me")

    moment = datetime.now(UTC)
    updated = await store.disable(principal_id, disabled_at=moment)
    assert updated is not None
    assert updated.disabled_at == moment

    reread = await store.get_by_id(principal_id)
    assert reread is not None
    assert reread.disabled_at == moment

    # The zero-row UPDATE ... RETURNING path - what users.py's disable_user
    # route relies on to turn an unknown id into a 404 rather than a crash.
    assert await store.disable(uuid7(), disabled_at=moment) is None


async def _assert_get_by_id_returns_every_kind_and_none_when_absent(pool: asyncpg.Pool) -> None:
    """``get_by_id`` returns a user or a service-account row alike, and None for an unknown id.

    ``get_by_id`` deliberately does not filter on kind. The identity service's
    human-kind check depends on seeing a service-account row so it can refuse
    it explicitly.
    """
    store = PostgresPrincipalStore(pool)

    user_id = await _insert_user_principal(pool, subject="contract-get-by-id-user")
    found_user = await store.get_by_id(user_id)
    assert found_user is not None
    assert found_user.kind == "user"

    sa_id = await _insert_service_account_principal(pool, subject="contract-get-by-id-sa")
    found_sa = await store.get_by_id(sa_id)
    assert found_sa is not None
    assert found_sa.kind == "service_account"

    assert await store.get_by_id(uuid7()) is None
