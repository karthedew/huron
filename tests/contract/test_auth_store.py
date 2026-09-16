"""Proves the Postgres auth stores round-trip and the schema's guards hold outside them.

Proves the Postgres auth schema (``0005_auth``) round-trips through
``PostgresCredentialStore``/``PostgresSessionStore``/``PostgresPrincipalStore``/
``PostgresApiKeyStore``, and that the guard trigger and CHECK constraints it
seeds truly protect a row inserted outside those stores - the same
two-pronged proof ``test_rbac_store.py`` makes for RBAC, applied to the auth
tables:

1. every store method is pushed through a real Postgres connection and read
   back, because that is the only way to catch a query that is syntactically
   fine but wrong against the actual schema;
2. ``local_credentials_kind_guard`` and the ``password_hash``/``secret_sha256``
   CHECKs are exercised through raw INSERTs that deliberately bypass the
   stores, proving the database refuses a bad row on its own, independent of
   any Python-side validation;
3. ``revoke_all_for`` is exercised on both the session and API-key stores
   for the property nothing else can catch: revocation is scoped to exactly
   one subject's *active* rows, and for API keys holds regardless of the
   key's ``owner_kind``; ``upsert_oidc_user`` is exercised on the principal
   store, proving a repeat login for the same ``idp_subject`` updates in
   place rather than creating a second row, and that a first-ever login
   whose subject collides with an existing password user's username is
   refused as :class:`~huron.core.security.principals.PrincipalSubjectExists` rather than
   auto-linked;
4. ``create_user``, ``disable``, and ``get_by_id`` - the admin-provisioning
   surface - are proven against the real ``principals.subject`` UNIQUE
   constraint: a subject already claimed by a password user, an OIDC login,
   or a service account must all be refused as
   :class:`~huron.core.security.principals.PrincipalSubjectExists`, the same way regardless
   of what kind of principal is already holding the name;
5. ``local_credentials_kind_guard`` raises the same message whether
   ``principal_id`` names no principal at all or an existing service
   account, and ``PostgresCredentialStore.upsert`` must tell the two apart:
   an unknown id stays :class:`~huron.core.foundation.errors.ResourceNotFound`,
   a real service account becomes
   :class:`~huron.core.security.errors.PrincipalKindMismatch`.

Requires Docker (testcontainers spins up a real PostgreSQL). Checked against
a database migrated with the project's own Alembic revisions.
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from testcontainers.postgres import PostgresContainer

from huron.core.security.apikeys import ApiKeyRecord
from huron.core.security.oidc import OidcUser
from huron.core.security.password import CredentialRecord
from huron.core.security.principals import PrincipalSubjectExists
from huron.core.security.sessions import SessionRecord
from huron.core.foundation.errors import ResourceNotFound
from huron.core.security.errors import PrincipalKindMismatch
from huron.core.foundation.identifiers import uuid7
from huron.core.metastore import (
    PostgresApiKeyStore,
    PostgresCredentialStore,
    PostgresPrincipalStore,
    PostgresSessionStore,
)

pytestmark = pytest.mark.contract

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"

VALID_HASH = "$argon2id$v=19$m=65536,t=3,p=4$c29tZXNhbHQ$aGFzaGVkcGFzc3dvcmQ"


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
        await _assert_credential_round_trip(pool)
        await _assert_credential_upsert_reports_a_missing_principal(pool)
        await _assert_credential_upsert_reports_a_service_account_as_kind_mismatch(pool)
        await _assert_local_credentials_kind_guard_rejects_a_service_account(pool)
        await _assert_local_credentials_check_rejects_a_non_argon2id_hash(pool)
        await _assert_session_round_trip_touch_and_revoke(pool)
        await _assert_sessions_check_rejects_a_malformed_secret_hash(pool)
        await _assert_revoke_all_for_touches_only_the_subjects_active_rows(pool)
        await _assert_api_key_revoke_all_for_ignores_owner_kind(pool)
        await _assert_upsert_oidc_user_creates_then_updates_without_duplicating(pool)
        await _assert_upsert_oidc_user_refuses_a_subject_a_password_user_holds(pool)
        await _assert_get_user_by_subject_hides_missing_disabled_and_service_accounts(pool)
        await _assert_create_user_inserts_a_password_user(pool)
        await _assert_create_user_refuses_a_subject_another_principal_holds(pool)
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


def _session_record(
    *, subject: str, now: datetime, revoked_at: datetime | None = None
) -> SessionRecord:
    """Builds a SessionRecord fixture for ``subject``, idle-expiring one hour after ``now``."""
    return SessionRecord(
        id=uuid4(),
        secret_sha256=hashlib.sha256(str(uuid4()).encode()).hexdigest(),
        csrf_token=f"csrf-{uuid4()}",
        subject=subject,
        groups=frozenset({"physics"}),
        authentication_method="password",
        created_at=now,
        last_seen_at=now,
        idle_expires_at=now + timedelta(hours=1),
        absolute_expires_at=now + timedelta(days=1),
        revoked_at=revoked_at,
    )


# -- local_credentials ---------------------------------------------------------


async def _assert_credential_round_trip(pool: asyncpg.Pool) -> None:
    """A missing credential reads as None, and upserting again replaces the stored hash in place."""
    store = PostgresCredentialStore(pool)
    principal_id = await _insert_user_principal(pool, subject="contract-user-credentials")
    assert await store.get(principal_id) is None

    record = CredentialRecord(
        principal_id=principal_id,
        password_hash=VALID_HASH,
        updated_at=datetime.now(UTC),
        updated_by="admin",
    )
    await store.upsert(record)
    assert await store.get(principal_id) == record

    replaced = CredentialRecord(
        principal_id=principal_id,
        password_hash=VALID_HASH + "-changed",
        updated_at=datetime.now(UTC),
        updated_by="admin-again",
    )
    await store.upsert(replaced)
    assert await store.get(principal_id) == replaced


async def _assert_credential_upsert_reports_a_missing_principal(pool: asyncpg.Pool) -> None:
    """``upsert()`` reports a nonexistent principal_id as ResourceNotFound, not a raw trigger error.

    The kind-guard trigger looks the principal up itself and fires before
    the foreign key ever gets checked, so a nonexistent principal_id must
    still surface through the store as ResourceNotFound, not a raw
    asyncpg.exceptions.RaiseError leaking out of upsert().
    """
    store = PostgresCredentialStore(pool)
    record = CredentialRecord(
        principal_id=uuid7(),
        password_hash=VALID_HASH,
        updated_at=datetime.now(UTC),
        updated_by="admin",
    )
    with pytest.raises(ResourceNotFound):
        await store.upsert(record)


async def _assert_credential_upsert_reports_a_service_account_as_kind_mismatch(
    pool: asyncpg.Pool,
) -> None:
    """``upsert()`` reports an existing service account as PrincipalKindMismatch, not not-found.

    The guard trigger raises the same generic message whether
    ``principal_id`` names nothing at all or a real service account; the
    store must tell the two apart rather than reporting both as
    ResourceNotFound.
    """
    store = PostgresCredentialStore(pool)
    principal_id = await _insert_service_account_principal(
        pool, subject="contract-sa-upsert-kind-mismatch"
    )
    record = CredentialRecord(
        principal_id=principal_id,
        password_hash=VALID_HASH,
        updated_at=datetime.now(UTC),
        updated_by="admin",
    )
    with pytest.raises(PrincipalKindMismatch):
        await store.upsert(record)


async def _assert_local_credentials_kind_guard_rejects_a_service_account(
    pool: asyncpg.Pool,
) -> None:
    """A ``local_credentials`` row for a non-'user' principal is refused, even written directly.

    The trigger backstop: a row written outside the store must still be
    refused for a principal that isn't kind 'user'.
    """
    principal_id = await _insert_service_account_principal(pool, subject="contract-sa-credentials")
    with pytest.raises(asyncpg.exceptions.RaiseError):
        await pool.execute(
            """
            INSERT INTO local_credentials (principal_id, password_hash, updated_at, updated_by)
            VALUES ($1, $2, now(), 'trigger-test')
            """,
            principal_id,
            VALID_HASH,
        )


async def _assert_local_credentials_check_rejects_a_non_argon2id_hash(pool: asyncpg.Pool) -> None:
    """Isolated from the kind guard: a valid user principal, an invalid hash."""
    principal_id = await _insert_user_principal(pool, subject="contract-user-badhash")
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        await pool.execute(
            """
            INSERT INTO local_credentials (principal_id, password_hash, updated_at, updated_by)
            VALUES ($1, 'not-an-argon2-hash', now(), 'trigger-test')
            """,
            principal_id,
        )


# -- sessions -------------------------------------------------------------------


async def _assert_session_round_trip_touch_and_revoke(pool: asyncpg.Pool) -> None:
    """A stored session round-trips, ``touch`` updates its activity window, and revoke sticks."""
    store = PostgresSessionStore(pool)
    now = datetime.now(UTC)
    record = _session_record(subject="contract-user-session", now=now)

    assert await store.get(record.id) is None
    await store.add(record)
    assert await store.get(record.id) == record

    touched_last_seen = now + timedelta(minutes=10)
    touched_idle = touched_last_seen + timedelta(hours=1)
    await store.touch(record.id, touched_last_seen, touched_idle)
    after_touch = await store.get(record.id)
    assert after_touch is not None
    assert after_touch.last_seen_at == touched_last_seen
    assert after_touch.idle_expires_at == touched_idle

    revoked_at = now + timedelta(hours=2)
    await store.revoke(record.id, revoked_at)
    after_revoke = await store.get(record.id)
    assert after_revoke is not None
    assert after_revoke.revoked_at == revoked_at


async def _assert_sessions_check_rejects_a_malformed_secret_hash(pool: asyncpg.Pool) -> None:
    """A ``sessions`` row whose ``secret_sha256`` is not a hex digest is refused by its CHECK."""
    now = datetime.now(UTC)
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        await pool.execute(
            """
            INSERT INTO sessions
                (id, secret_sha256, csrf_token, subject, authentication_method,
                 created_at, last_seen_at, idle_expires_at, absolute_expires_at)
            VALUES ($1, 'not-a-hex-digest', 'csrf', 'contract-user-badsecret', 'password',
                    $2::timestamptz, $2::timestamptz,
                    $2::timestamptz + interval '1 hour', $2::timestamptz + interval '1 day')
            """,
            uuid7(),
            now,
        )


async def _assert_revoke_all_for_touches_only_the_subjects_active_rows(pool: asyncpg.Pool) -> None:
    """``revoke_all_for`` revokes only its subject's active row, sparing an already-revoked one."""
    store = PostgresSessionStore(pool)
    now = datetime.now(UTC)
    subject, other_subject = "contract-user-revoke-all", "contract-user-untouched"

    active = _session_record(subject=subject, now=now)
    already_revoked = _session_record(subject=subject, now=now, revoked_at=now)
    other = _session_record(subject=other_subject, now=now)
    for record in (active, already_revoked, other):
        await store.add(record)

    revoked_at = now + timedelta(hours=1)
    count = await store.revoke_all_for(subject, revoked_at)
    assert count == 1

    active_after = await store.get(active.id)
    already_revoked_after = await store.get(already_revoked.id)
    other_after = await store.get(other.id)
    assert active_after is not None and active_after.revoked_at == revoked_at
    assert already_revoked_after is not None and already_revoked_after.revoked_at == now
    assert other_after is not None and other_after.revoked_at is None


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


# -- principals: upsert-on-login, admin provisioning, and lookup ------------


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


async def _assert_upsert_oidc_user_refuses_a_subject_a_password_user_holds(
    pool: asyncpg.Pool,
) -> None:
    """A first-ever OIDC login is refused, not auto-linked, when its subject is a local username."""
    store = PostgresPrincipalStore(pool)
    await store.create_user(subject="contract-collide-s", display_name="Password User")

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


async def _assert_get_user_by_subject_hides_missing_disabled_and_service_accounts(
    pool: asyncpg.Pool,
) -> None:
    """``get_user_by_subject`` hides an unknown, disabled, or service-account subject as None."""
    store = PostgresPrincipalStore(pool)
    assert await store.get_user_by_subject("contract-nobody") is None

    active_id = await _insert_user_principal(pool, subject="contract-active-user")
    found = await store.get_user_by_subject("contract-active-user")
    assert found is not None
    assert found.id == active_id

    await _insert_user_principal(pool, subject="contract-disabled-user", disabled=True)
    assert await store.get_user_by_subject("contract-disabled-user") is None

    await _insert_service_account_principal(pool, subject="contract-sa-lookup")
    assert await store.get_user_by_subject("contract-sa-lookup") is None


async def _assert_create_user_inserts_a_password_user(pool: asyncpg.Pool) -> None:
    """``create_user`` inserts a password user whose row matches what ``get_by_id`` returns."""
    store = PostgresPrincipalStore(pool)
    created = await store.create_user(subject="contract-create-user", display_name="Contract User")
    assert created.kind == "user"
    assert created.subject == "contract-create-user"
    assert created.display_name == "Contract User"
    assert created.idp_subject is None
    assert created.disabled_at is None
    assert created.created_at is not None

    # Re-SELECT by the returned id: proves the RETURNING column list the
    # store's INSERT names actually matches what a plain read produces.
    reread = await store.get_by_id(created.id)
    assert reread == created


async def _assert_create_user_refuses_a_subject_another_principal_holds(
    pool: asyncpg.Pool,
) -> None:
    """``create_user`` refuses a subject already held by a password, OIDC, or service principal.

    ``subject`` is UNIQUE across every principal (0002) regardless of how
    it was created - a password user, an OIDC login, or a service account
    all trigger the same ``UniqueViolationError`` -> ``PrincipalSubjectExists``
    translation.
    """
    store = PostgresPrincipalStore(pool)

    await store.create_user(subject="contract-dup-password", display_name="First")
    with pytest.raises(PrincipalSubjectExists):
        await store.create_user(subject="contract-dup-password", display_name="Second")

    await store.upsert_oidc_user(
        OidcUser(
            idp_subject="contract-dup-oidc",
            display_name="Oidc User",
            email=None,
            groups=frozenset(),
        )
    )
    with pytest.raises(PrincipalSubjectExists):
        await store.create_user(subject="contract-dup-oidc", display_name="Impostor")

    await _insert_service_account_principal(pool, subject="contract-dup-sa")
    with pytest.raises(PrincipalSubjectExists):
        await store.create_user(subject="contract-dup-sa", display_name="Impostor SA")


async def _assert_disable_sets_disabled_at_and_returns_none_for_an_unknown_id(
    pool: asyncpg.Pool,
) -> None:
    """``disable`` stamps ``disabled_at`` and hides the user, returning None for an unknown id."""
    store = PostgresPrincipalStore(pool)
    created = await store.create_user(subject="contract-disable-me", display_name="Disable Me")

    moment = datetime.now(UTC)
    updated = await store.disable(created.id, disabled_at=moment)
    assert updated is not None
    assert updated.disabled_at == moment

    reread = await store.get_by_id(created.id)
    assert reread is not None
    assert reread.disabled_at == moment
    assert await store.get_user_by_subject("contract-disable-me") is None

    # The zero-row UPDATE ... RETURNING path - what users.py's disable_user
    # route relies on to turn an unknown id into a 404 rather than a crash.
    assert await store.disable(uuid7(), disabled_at=moment) is None


async def _assert_get_by_id_returns_every_kind_and_none_when_absent(pool: asyncpg.Pool) -> None:
    """``get_by_id`` returns a user or a service-account row alike, and None for an unknown id.

    ``get_by_id`` deliberately does not filter on kind - the
    ``_existing_user`` guard in ``routes/v1/endpoints/users.py`` depends on
    seeing a service-account row back so it can refuse it explicitly.
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
