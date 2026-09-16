"""``POST /auth/login`` and ``POST /auth/logout``, driven through a TestClient.

Drives the FastAPI app through a TestClient over an in-memory
store set with dev-header auth, seeding principals and
credentials directly in the store rather than through the admin
provisioning routes. Proves the cookie a successful login sets, the CSRF
rule that gated write governs, the generic refusal a wrong credential
gets, and the two kind guards a password login must honor (disabled,
service account) exactly as the password-lookup seam already enforces at
the store level.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from pydantic import ValidationError

from huron.applications.api.app import create_app
from huron.core.security._impl.password_authentication import _password_hash_limiter
from huron.applications.api.routes.auth.schema.login import LoginResult, SignOut
from huron.applications.api.routes.auth.schema.session import ProviderInfo, ScopeRoles, SessionInfo
from huron.applications.api.settings import ApiSettings, ClassificationValue, OidcSettings
from huron.core.security.password import (
    CredentialRecord,
    make_credential,
    needs_rehash,
    verify_password,
)
from huron.core.metastore import MemoryCredentialStore
from huron.core.security.principals import PrincipalRecord
from huron.core.security.roles import ROLES
from huron.core.security.apikeys import create_api_key
from tests.unit.support import memory_stores

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from huron.applications.api.runtime import ApiStores

pytestmark = pytest.mark.unit

PASSWORD = "correct-horse-battery-staple"

#: Deliberately weaker than the module's live Argon2 parameters, so a hash
#: made with it is always reported stale by ``needs_rehash``.
_WEAK_HASHER = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)


def _settings(
    tmp_path: Path,
    *,
    password_login_enabled: bool = True,
    bootstrap_platform_owner: str | None = None,
) -> ApiSettings:
    """Dev-header settings with tunable password-login and bootstrap-owner flags."""
    return ApiSettings(
        env="development",
        auth_mode="dev-headers",
        data_root=str(tmp_path / "data"),
        database_url="postgresql://unused",
        classification_vocabulary=[ClassificationValue(code="open", order=0, discoverable=True)],
        password_login_enabled=password_login_enabled,
        bootstrap_platform_owner=bootstrap_platform_owner,
    )


def _dev_headers(subject: str) -> dict[str, str]:
    """Dev-header credentials for ``subject``, paired with a fresh idempotency key."""
    return {"X-Huron-Subject": subject, "Idempotency-Key": str(uuid4())}


def _seed_principal(
    stores: ApiStores, *, subject: str, kind: str = "user", disabled: bool = False
) -> PrincipalRecord:
    """Seed a bare principal directly into the injected store, with no credential.

    Populate the memory store directly - the same seam
    ``test_auth_principals.py`` pre-seeds through - so a login test can set
    up a principal without going through the (separately tested) admin
    provisioning routes.
    """
    now = datetime.now(UTC)
    record = PrincipalRecord(
        id=uuid4(),
        kind=kind,
        subject=subject,
        display_name=subject.title(),
        idp_subject=None,
        disabled_at=now if disabled else None,
        created_at=now,
    )
    stores.principals.records[record.id] = record
    return record


def _seed_user(
    stores: ApiStores,
    *,
    subject: str,
    password: str,
    kind: str = "user",
    disabled: bool = False,
) -> PrincipalRecord:
    """Seed a principal and a password credential hashed at the live parameters."""
    record = _seed_principal(stores, subject=subject, kind=kind, disabled=disabled)
    stores.credentials.records[record.id] = make_credential(
        record.id, password, updated_by="test-setup"
    )
    return record


def _seed_user_with_hash(stores: ApiStores, *, subject: str, password_hash: str) -> PrincipalRecord:
    """Seed a principal whose credential carries a hash chosen by the caller.

    Bypasses ``make_credential`` so a test can plant a hash from parameters
    other than the module's live ones - the only way to exercise
    ``needs_rehash`` returning true.
    """
    record = _seed_principal(stores, subject=subject)
    stores.credentials.records[record.id] = CredentialRecord(
        principal_id=record.id,
        password_hash=password_hash,
        updated_at=datetime.now(UTC),
        updated_by="test-setup",
    )
    return record


@pytest.fixture
def stores() -> ApiStores:
    """A fresh set of in-memory stores, seedable before the app's lifespan runs."""
    return memory_stores()


@pytest.fixture
def client(tmp_path: Path, stores: ApiStores) -> Iterator[TestClient]:
    """A dev-header TestClient wired to ``stores`` with default login settings."""
    settings = _settings(tmp_path)
    with TestClient(create_app(settings=settings, stores=stores)) as client:
        yield client


# -- password login: happy path and the session it starts -------------------


def test_password_login_sets_a_cookie_and_the_session_resolves_on_the_next_request(
    client: TestClient, stores: ApiStores
) -> None:
    """A successful password login sets a session cookie that resolves on the next request."""
    _seed_user(stores, subject="alice", password=PASSWORD)

    login = client.post("/auth/login", json={"username": "alice", "password": PASSWORD})
    assert login.status_code == 200
    body = login.json()
    assert body["subject"] == "alice"
    assert body["display_name"] == "Alice"
    assert isinstance(body["csrf_token"], str) and body["csrf_token"]
    assert "huron_session" in client.cookies

    session = client.get("/auth/session")
    assert session.status_code == 200
    info = session.json()
    assert info["subject"] == "alice"
    assert info["kind"] == "user"
    assert info["authentication_method"] == "session"
    assert info["csrf_token"] == body["csrf_token"]
    assert info["expires_at"] is not None
    assert info["effective_roles"] == []


@pytest.mark.parametrize("authorization", [" ", "Bearer ", "Basic invalid", "hk_bad"])
def test_nonempty_authorization_never_falls_back_to_a_valid_cookie(
    client: TestClient,
    stores: ApiStores,
    authorization: str,
) -> None:
    """A nonempty raw header wins even if the legacy parser yields an empty token."""
    _seed_user(stores, subject="alice", password=PASSWORD)
    login = client.post("/auth/login", json={"username": "alice", "password": PASSWORD})
    assert login.status_code == 200
    assert client.get("/auth/session").status_code == 200
    response = client.get("/auth/session", headers={"Authorization": authorization})
    assert response.status_code == 401


def test_empty_authorization_header_is_absent_and_allows_session_authentication(
    client: TestClient,
    stores: ApiStores,
) -> None:
    """An actually empty header retains the baseline cookie fallback."""
    _seed_user(stores, subject="alice", password=PASSWORD)
    login = client.post("/auth/login", json={"username": "alice", "password": PASSWORD})
    assert login.status_code == 200
    response = client.get("/auth/session", headers={"Authorization": ""})
    assert response.status_code == 200
    assert response.json()["authentication_method"] == "session"


@pytest.mark.parametrize("prefix", ["Bearer ", "", "  "])
def test_bearer_and_legacy_naked_keys_keep_priority_over_session_cookie(
    client: TestClient,
    stores: ApiStores,
    prefix: str,
) -> None:
    """The transport's unchanged removeprefix/strip parser accepts prefixed and naked keys."""
    _seed_user(stores, subject="alice", password=PASSWORD)
    login = client.post("/auth/login", json={"username": "alice", "password": PASSWORD})
    assert login.status_code == 200
    key, token = create_api_key("bob", name="laptop")
    stores.api_keys.records[key.key_id] = key
    response = client.get("/auth/session", headers={"Authorization": f"{prefix}{token}  "})
    assert response.status_code == 200
    assert response.json()["subject"] == "bob"
    assert response.json()["authentication_method"] == "api-key"
    assert response.json()["csrf_token"] is None
    assert stores.api_keys.touched == [key.key_id]


def test_password_login_rejects_the_wrong_password_with_a_generic_message(
    client: TestClient, stores: ApiStores
) -> None:
    """A wrong password is refused with 401 and a generic invalid-credentials message."""
    _seed_user(stores, subject="alice", password=PASSWORD)
    response = client.post("/auth/login", json={"username": "alice", "password": "nope"})
    assert response.status_code == 401
    assert response.json()["detail"] == "invalid username or password"


def test_password_login_rejects_an_unknown_username_with_the_same_generic_message(
    client: TestClient,
) -> None:
    """An unknown username is refused with the same generic message as a wrong password."""
    response = client.post("/auth/login", json={"username": "nobody", "password": PASSWORD})
    assert response.status_code == 401
    assert response.json()["detail"] == "invalid username or password"


def test_password_login_refuses_a_disabled_user(client: TestClient, stores: ApiStores) -> None:
    """A disabled user's password login is refused with 401."""
    _seed_user(stores, subject="dana", password=PASSWORD, disabled=True)
    response = client.post("/auth/login", json={"username": "dana", "password": PASSWORD})
    assert response.status_code == 401


def test_password_login_cannot_reach_a_service_account_even_with_a_password_row(
    client: TestClient, stores: ApiStores
) -> None:
    """A service-account principal cannot log in via password even with a stored credential row.

    A ``local_credentials`` row keyed to a service-account principal id
    should never exist (the kind guard on both stores refuses it), but if
    one did, the password-login lookup still cannot reach it: it filters
    on ``kind='user'`` before a hash is ever compared.
    """
    _seed_user(stores, subject="astro/pipeline", password=PASSWORD, kind="service_account")
    response = client.post("/auth/login", json={"username": "astro/pipeline", "password": PASSWORD})
    assert response.status_code == 401


def test_password_login_is_refused_outright_when_disabled_by_settings(tmp_path: Path) -> None:
    """Password login is refused with 401 outright when disabled by settings."""
    settings = _settings(tmp_path, password_login_enabled=False)
    stores = memory_stores()
    _seed_user(stores, subject="alice", password=PASSWORD)
    with TestClient(create_app(settings=settings, stores=stores)) as client:
        response = client.post("/auth/login", json={"username": "alice", "password": PASSWORD})
    assert response.status_code == 401


# -- password login: rehashing a credential left over from weaker cost ------


class _RaisingUpsertCredentialStore(MemoryCredentialStore):
    """A credential store whose upsert always raises, simulating a write outage."""

    async def upsert(self, record: CredentialRecord) -> None:
        """Always raises, as if the store were unreachable."""
        raise RuntimeError("credential store unavailable")


def test_password_login_rehashes_a_credential_stored_with_weaker_parameters(
    client: TestClient, stores: ApiStores
) -> None:
    """A credential hashed at weaker-than-live Argon2 parameters is replaced after login.

    The stored hash changes and still verifies against the same password
    the caller sent, while ``updated_by`` and ``updated_at`` stay exactly
    as they were - a login-time rehash is not the administrative act that
    set the password, so it must not be credited as one.
    """
    record = _seed_user_with_hash(
        stores, subject="alice", password_hash=_WEAK_HASHER.hash(PASSWORD)
    )
    original = stores.credentials.records[record.id]

    response = client.post("/auth/login", json={"username": "alice", "password": PASSWORD})

    assert response.status_code == 200
    rehashed = stores.credentials.records[record.id]
    assert rehashed.password_hash != original.password_hash
    assert rehashed.updated_by == original.updated_by
    assert rehashed.updated_at == original.updated_at
    assert not needs_rehash(rehashed)
    assert verify_password(rehashed, PASSWORD)


def test_password_login_leaves_a_credential_at_current_parameters_untouched(
    client: TestClient, stores: ApiStores
) -> None:
    """A credential already hashed at the live Argon2 parameters is not rewritten on login."""
    record = _seed_user(stores, subject="alice", password=PASSWORD)
    original = stores.credentials.records[record.id]
    assert not needs_rehash(original)

    response = client.post("/auth/login", json={"username": "alice", "password": PASSWORD})

    assert response.status_code == 200
    assert stores.credentials.records[record.id] is original


def test_password_login_succeeds_even_when_the_rehash_write_fails(tmp_path: Path) -> None:
    """A store failure while writing the rehashed credential still answers 200.

    The caller already proved they hold the password; a housekeeping write
    failing afterwards is not a reason to fail the login it follows.
    """
    settings = _settings(tmp_path)
    stores = memory_stores()
    record = _seed_user_with_hash(
        stores, subject="alice", password_hash=_WEAK_HASHER.hash(PASSWORD)
    )
    stores = dataclasses.replace(
        stores, credentials=_RaisingUpsertCredentialStore(stores.credentials.records)
    )

    with TestClient(create_app(settings=settings, stores=stores)) as client:
        response = client.post("/auth/login", json={"username": "alice", "password": PASSWORD})

    assert response.status_code == 200
    assert response.json()["subject"] == "alice"
    # The failed write left the outdated hash in place - proving the login
    # succeeded despite the rewrite failing, not because it silently didn't.
    assert needs_rehash(stores.credentials.records[record.id])


def test_password_hashing_has_its_own_four_token_capacity_limiter() -> None:
    """Password hashing queues on its own limiter, capped at 4 tokens.

    Pins the capacity decision in code: password hashing must queue on a
    dedicated limiter sized well below the shared 40-token threadpool
    limiter, so a burst of login attempts cannot reserve the memory an
    unbounded flood of Argon2id hashes would demand.
    """
    assert _password_hash_limiter.total_tokens == 4


# -- CSRF on the one session-authed write every caller can reach: logout ----


def test_logout_without_the_csrf_header_is_refused_for_a_session_authed_caller(
    client: TestClient, stores: ApiStores
) -> None:
    """Logging out without the CSRF header is refused with 401 for a session-authed caller."""
    _seed_user(stores, subject="alice", password=PASSWORD)
    client.post("/auth/login", json={"username": "alice", "password": PASSWORD})
    response = client.post("/auth/logout")
    assert response.status_code == 401


def test_logout_with_the_csrf_header_succeeds_and_revokes_the_session(
    client: TestClient, stores: ApiStores
) -> None:
    """Logging out with the CSRF header succeeds and revokes the session server-side."""
    _seed_user(stores, subject="alice", password=PASSWORD)
    login = client.post("/auth/login", json={"username": "alice", "password": PASSWORD})
    csrf_token = login.json()["csrf_token"]

    response = client.post("/auth/logout", headers={"X-Huron-CSRF": csrf_token})
    assert response.status_code == 200
    assert response.json() == {"status": "signed-out"}

    # The cookie is cleared, and even presenting the old value again is
    # refused - logout revoked the session server-side, not just client-side.
    stale_cookie = login.headers.get("set-cookie", "")
    token = stale_cookie.split("huron_session=", 1)[1].split(";", 1)[0]
    client.cookies.set("huron_session", token)
    denied = client.get("/auth/session", headers={"X-Huron-CSRF": csrf_token})
    assert denied.status_code == 401


def test_logout_over_bearer_needs_no_csrf_header(tmp_path: Path, stores: ApiStores) -> None:
    """Logging out over a bearer token succeeds without a CSRF header."""
    settings = _settings(tmp_path)
    with TestClient(create_app(settings=settings, stores=stores)) as client:
        issued = client.post(
            "/api/v1/auth/api-keys",
            json={"name": "laptop"},
            headers={"X-Huron-Subject": "bob", "Idempotency-Key": str(uuid4())},
        )
        assert issued.status_code == 201
        token = issued.json()["secret"]

        response = client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})
        still_valid = client.get("/auth/session", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert still_valid.status_code == 200


# -- /auth/providers: unauthenticated, reflects settings ---------------------


def test_providers_reports_password_only_by_default(client: TestClient) -> None:
    """``/auth/providers`` reports password enabled and OIDC disabled by default."""
    response = client.get("/auth/providers")
    assert response.status_code == 200
    assert response.json() == {"password": True, "oidc": False, "oidc_start_url": None}


def test_providers_reports_password_disabled(tmp_path: Path) -> None:
    """``/auth/providers`` reflects password login disabled by settings."""
    settings = _settings(tmp_path, password_login_enabled=False)
    with TestClient(create_app(settings=settings, stores=memory_stores())) as client:
        response = client.get("/auth/providers")
    assert response.json() == {"password": False, "oidc": False, "oidc_start_url": None}


def test_providers_reports_oidc_enabled_when_configured(tmp_path: Path) -> None:
    """``/auth/providers`` reports OIDC enabled with its start URL when configured."""
    settings = ApiSettings(
        env="production",
        auth_mode="oidc",
        data_root=str(tmp_path / "data"),
        database_url="postgresql://unused",
        classification_vocabulary=[ClassificationValue(code="open", order=0, discoverable=True)],
        login_flow_secret="flow-secret",
        oidc=OidcSettings(
            issuer="https://idp.example",
            client_id="huron-web",
            client_secret="shh",
            redirect_url="https://app.example/auth/oidc/callback",
        ),
    )
    # Injecting a verifier bypasses real discovery (test_api_app.py's seam)
    # while still exercising ``settings.oidc is not None``.
    app = create_app(
        settings=settings,
        stores=memory_stores(),
        oidc_verify=lambda _token: {"sub": "svc"},
    )
    with TestClient(app) as client:
        response = client.get("/auth/providers")
    assert response.json() == {
        "password": True,
        "oidc": True,
        "oidc_start_url": "/auth/oidc/start",
    }


# -- /auth/session: effective_roles ------------------------------------------


def test_session_reports_a_single_system_scope_entry_for_the_platform_owner(
    tmp_path: Path,
) -> None:
    """The bootstrap platform owner's session reports one SYSTEM-scope entry with all its roles."""
    settings = _settings(tmp_path, bootstrap_platform_owner="root")
    with TestClient(create_app(settings=settings, stores=memory_stores())) as client:
        response = client.get("/auth/session", headers=_dev_headers("root"))
    assert response.status_code == 200
    expected_roles = sorted(ROLES["platform_owner"].capabilities | {"data.read"})
    assert response.json()["effective_roles"] == [
        {"scope_type": "SYSTEM", "scope_id": None, "roles": expected_roles}
    ]


def test_session_orders_effective_roles_by_scope_type_then_scope_id_and_holds_on_repeat(
    tmp_path: Path,
) -> None:
    """Effective roles are ordered ``ORGANIZATION`` before ``PROJECT``, stably across requests.

    A caller administering one organization and developing on a project in
    another is told about both scopes, ``ORGANIZATION`` before ``PROJECT``
    - and asking again returns the identical order, not one recomputed
    from whatever order a set or dict happened to iterate in this time.
    """
    settings = _settings(tmp_path, bootstrap_platform_owner="root")
    with TestClient(create_app(settings=settings, stores=memory_stores())) as client:
        organization = client.post(
            "/api/v1/organizations",
            json={"slug": "astro", "title": "Astro"},
            headers=_dev_headers("root"),
        ).json()
        project = client.post(
            f"/api/v1/organizations/{organization['id']}/projects",
            json={"slug": "sims", "title": "Sims", "data_classification": "open"},
            headers=_dev_headers("root"),
        ).json()
        assert (
            client.post(
                f"/api/v1/organizations/{organization['id']}/bindings",
                json={"principal": "user:carol", "role": "organization_admin"},
                headers=_dev_headers("root"),
            ).status_code
            == 201
        )
        assert (
            client.post(
                f"/api/v1/projects/{project['id']}/bindings",
                json={"principal": "user:carol", "role": "developer"},
                headers=_dev_headers("root"),
            ).status_code
            == 201
        )

        first = client.get("/auth/session", headers=_dev_headers("carol")).json()
        second = client.get("/auth/session", headers=_dev_headers("carol")).json()

    expected_organization_roles = sorted(ROLES["organization_admin"].capabilities | {"data.read"})
    expected_project_roles = sorted(ROLES["developer"].capabilities | {"data.read", "data.write"})
    expected = [
        {
            "scope_type": "ORGANIZATION",
            "scope_id": organization["id"],
            "roles": expected_organization_roles,
        },
        {"scope_type": "PROJECT", "scope_id": project["id"], "roles": expected_project_roles},
    ]
    assert first["effective_roles"] == expected
    assert second["effective_roles"] == expected


def test_session_breaks_ties_between_same_type_scopes_by_scope_id(tmp_path: Path) -> None:
    """Two same-type scope entries in effective roles are ordered by ``scope_id`` alone.

    This proves the tie-break rather than relying on the scope-type
    ordering the other ordering test already covers.
    """
    settings = _settings(tmp_path, bootstrap_platform_owner="root")
    with TestClient(create_app(settings=settings, stores=memory_stores())) as client:
        first_org = client.post(
            "/api/v1/organizations",
            json={"slug": "astro", "title": "Astro"},
            headers=_dev_headers("root"),
        ).json()
        second_org = client.post(
            "/api/v1/organizations",
            json={"slug": "bio", "title": "Bio"},
            headers=_dev_headers("root"),
        ).json()
        for org in (first_org, second_org):
            assert (
                client.post(
                    f"/api/v1/organizations/{org['id']}/bindings",
                    json={"principal": "user:carol", "role": "organization_admin"},
                    headers=_dev_headers("root"),
                ).status_code
                == 201
            )
        response = client.get("/auth/session", headers=_dev_headers("carol"))

    scope_ids = [entry["scope_id"] for entry in response.json()["effective_roles"]]
    assert scope_ids == sorted([first_org["id"], second_org["id"]], key=str)


def test_session_reports_no_effective_roles_for_an_unbound_principal(tmp_path: Path) -> None:
    """An unbound principal's session reports an empty ``effective_roles`` list."""
    settings = _settings(tmp_path, bootstrap_platform_owner="root")
    with TestClient(create_app(settings=settings, stores=memory_stores())) as client:
        response = client.get("/auth/session", headers=_dev_headers("nobody"))
    assert response.status_code == 200
    assert response.json()["effective_roles"] == []


# -- unversioned models are hand-assembled, never validated from a record ---


def test_none_of_the_unversioned_auth_models_can_be_filled_from_a_bare_object() -> None:
    """None of the unversioned auth response models can be filled from a bare object.

    These responses are constructed field by field from live authorization
    or credential-minting state, never from a stored record - an object
    with matching attributes but no ``from_attributes`` config must still
    fail.
    """
    bare = SimpleNamespace(
        subject="alice",
        kind="user",
        groups=[],
        authentication_method="session",
        effective_roles=[],
        csrf_token=None,
        expires_at=None,
        scope_type="SYSTEM",
        scope_id=None,
        roles=[],
        display_name="Alice",
        status="signed-out",
        password=True,
        oidc=False,
        oidc_start_url=None,
    )
    for model in (SessionInfo, ScopeRoles, LoginResult, SignOut, ProviderInfo):
        with pytest.raises(ValidationError):
            model.model_validate(bare)
