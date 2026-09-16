"""Admin-provisioned password users through the HTTP surface.

Covers the ``user.manage`` guard, the duplicate-subject refusal shared by
memory and Postgres principal stores, the two write routes' session-revoking
side effects, and the exact field set the responses publish.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from huron.applications.api.app import create_app
from huron.applications.api.settings import ApiSettings, ClassificationValue
from huron.core.metastore import MemoryPrincipalStore
from huron.core.security.principals import PrincipalRecord
from tests.unit.support import memory_stores

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path
    from uuid import UUID

    from fastapi import FastAPI

    from huron.applications.api.runtime import ApiStores

pytestmark = pytest.mark.unit


def _headers(subject: str) -> dict[str, str]:
    """Auth and idempotency headers for `subject`, with a fresh Idempotency-Key each call."""
    return {"X-Huron-Subject": subject, "Idempotency-Key": str(uuid4())}


def _settings(tmp_path: Path) -> ApiSettings:
    """A development ApiSettings with dev-headers auth and root bootstrapped as platform owner."""
    return ApiSettings(
        env="development",
        auth_mode="dev-headers",
        data_root=str(tmp_path / "data"),
        database_url="postgresql://unused",
        classification_vocabulary=[ClassificationValue(code="open", order=0, discoverable=True)],
        bootstrap_platform_owner="root",
    )


@pytest.fixture
def stores() -> ApiStores:
    """A fresh set of in-memory stores, seedable before or after the app starts."""
    return memory_stores()


@pytest.fixture
def app(tmp_path: Path, stores: ApiStores) -> FastAPI:
    """The FastAPI app wired to `stores`, so tests can seed principals directly."""
    return create_app(settings=_settings(tmp_path), stores=stores)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """A TestClient over `app` with its lifespan run, so root is bootstrapped as platform owner."""
    # Entered as a context manager so the bootstrap grant actually runs -
    # see test_api_rbac.py's identical fixture for why.
    with TestClient(app) as client:
        yield client


def _create_user(client: TestClient, *, username: str, password: str = "a-strong-password") -> str:
    """Creates a password user named `username` as root and returns its principal id."""
    response = client.post(
        "/api/v1/users",
        json={"username": username, "display_name": username.title(), "password": password},
        headers=_headers("root"),
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def test_user_manage_is_denied_to_an_organization_admin(client: TestClient) -> None:
    """An organization admin, lacking user.manage, is denied creating a user with 403."""
    organization = client.post(
        "/api/v1/organizations",
        json={"slug": "astro", "title": "Astro"},
        headers=_headers("root"),
    )
    organization_id = organization.json()["id"]
    bound = client.post(
        f"/api/v1/organizations/{organization_id}/bindings",
        json={"principal": "user:mallory", "role": "organization_admin"},
        headers=_headers("root"),
    )
    assert bound.status_code == 201

    denied = client.post(
        "/api/v1/users",
        json={"username": "dana", "display_name": "Dana", "password": "a-strong-password"},
        headers=_headers("mallory"),
    )
    assert denied.status_code == 403


def test_user_manage_is_granted_to_the_platform_owner(client: TestClient) -> None:
    """The platform owner can create a user, whose response never leaks a password or its hash."""
    response = client.post(
        "/api/v1/users",
        json={"username": "dana", "display_name": "Dana", "password": "a-strong-password"},
        headers=_headers("root"),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["subject"] == "dana"
    assert body["disabled_at"] is None
    assert "password" not in body
    assert "password_hash" not in body


def test_created_user_response_publishes_exactly_the_declared_fields(client: TestClient) -> None:
    """A created user's response publishes exactly its declared fields, not kind or idp_subject.

    ``kind`` and ``idp_subject`` are on ``PrincipalRecord`` but neither is
    part of this contract: ``kind`` is constant "user" on every route that
    returns this model, and ``idp_subject`` is always null here - it is set
    only by the OIDC login path, which this surface never reaches.
    """
    response = client.post(
        "/api/v1/users",
        json={"username": "dana", "display_name": "Dana", "password": "a-strong-password"},
        headers=_headers("root"),
    )
    assert response.status_code == 201
    assert set(response.json()) == {
        "id",
        "subject",
        "display_name",
        "disabled_at",
        "created_at",
    }


def test_create_user_refuses_a_subject_that_already_exists(client: TestClient) -> None:
    """Creating a user with a subject that already exists is refused with 409 USERNAME_TAKEN."""
    _create_user(client, username="dana")
    conflict = client.post(
        "/api/v1/users",
        json={"username": "dana", "display_name": "Someone Else", "password": "another-password"},
        headers=_headers("root"),
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "USERNAME_TAKEN"
    assert "dana" in conflict.json()["detail"]


def test_set_password_refuses_a_service_account_id_with_an_honest_error(
    client: TestClient, stores: ApiStores
) -> None:
    """Setting a password for a service-account id fails with an honest kind mismatch, not 404.

    A service account can never legitimately reach this route - the
    kind guard here must say so plainly, not report "does not exist" the
    way the Postgres kind-guard trigger's generic RaiseError would if this
    route let a mismatched id fall all the way through to it. Service
    accounts live in ``rbac_store`` for the memory backend (there is no
    unified ``principals`` table the way Postgres has one), so the
    ``principals`` row is seeded directly here, the same seam
    ``test_api_login.py`` uses for its own service-account scenario.
    """
    account = PrincipalRecord(
        id=uuid4(),
        kind="service_account",
        subject="astro/pipeline",
        display_name="",
        idp_subject=None,
        disabled_at=None,
        created_at=datetime.now(UTC),
    )
    stores.principals.records[account.id] = account

    response = client.put(
        f"/api/v1/users/{account.id}/password",
        json={"password": "a-strong-password"},
        headers=_headers("root"),
    )
    assert response.status_code == 409
    assert response.json()["code"] == "PRINCIPAL_KIND_MISMATCH"
    assert "not a user" in response.json()["detail"]


def test_set_password_404s_for_an_unknown_principal_id(client: TestClient) -> None:
    """Setting a password for an unknown principal id 404s."""
    response = client.put(
        f"/api/v1/users/{uuid4()}/password",
        json={"password": "a-strong-password"},
        headers=_headers("root"),
    )
    assert response.status_code == 404


def test_password_reset_revokes_every_session_for_that_subject(
    app: FastAPI, client: TestClient
) -> None:
    """Resetting a password revokes the old session but a fresh login with the new one succeeds."""
    principal_id = _create_user(client, username="erin", password="erins-first-password")
    # A separate cookie jar against the same app - dev-header requests and a
    # session cookie must never share one TestClient (the cookie branch of
    # ``current_principal`` outranks dev headers, so they would collide).
    user_client = TestClient(app)
    login = user_client.post(
        "/auth/login", json={"username": "erin", "password": "erins-first-password"}
    )
    assert login.status_code == 200
    assert user_client.get("/auth/session").status_code == 200

    reset = client.put(
        f"/api/v1/users/{principal_id}/password",
        json={"password": "erins-second-password"},
        headers=_headers("root"),
    )
    assert reset.status_code == 200
    assert reset.json() == {"status": "password-reset"}

    assert user_client.get("/auth/session").status_code == 401
    relogin = user_client.post(
        "/auth/login", json={"username": "erin", "password": "erins-second-password"}
    )
    assert relogin.status_code == 200


def test_disable_sets_disabled_at_and_revokes_every_session(
    app: FastAPI, client: TestClient
) -> None:
    """Disabling a user sets disabled_at, revokes their session, and blocks any further login."""
    principal_id = _create_user(client, username="frank", password="franks-password")
    user_client = TestClient(app)
    login = user_client.post(
        "/auth/login", json={"username": "frank", "password": "franks-password"}
    )
    assert login.status_code == 200

    disabled = client.post(f"/api/v1/users/{principal_id}/disable", headers=_headers("root"))
    assert disabled.status_code == 200
    assert disabled.json()["disabled_at"] is not None

    assert user_client.get("/auth/session").status_code == 401
    relogin = user_client.post(
        "/auth/login", json={"username": "frank", "password": "franks-password"}
    )
    assert relogin.status_code == 401


def _mint_api_key(client: TestClient, *, subject: str) -> str:
    """Mints an API key for `subject` via dev-header self-service and returns its secret."""
    issued = client.post(
        "/api/v1/auth/api-keys", json={"name": "laptop"}, headers=_headers(subject)
    )
    assert issued.status_code == 201, issued.text
    return str(issued.json()["secret"])


def test_disable_revokes_every_api_key_the_user_holds(app: FastAPI, client: TestClient) -> None:
    """Disabling a user revokes the API keys they minted, not only their sessions."""
    principal_id = _create_user(client, username="alice")
    key_client = TestClient(app)
    secret = _mint_api_key(key_client, subject="alice")
    assert (
        key_client.get("/auth/session", headers={"Authorization": f"Bearer {secret}"}).status_code
        == 200
    )

    disabled = client.post(f"/api/v1/users/{principal_id}/disable", headers=_headers("root"))
    assert disabled.status_code == 200

    revoked = key_client.get("/auth/session", headers={"Authorization": f"Bearer {secret}"})
    assert revoked.status_code == 401
    assert revoked.json()["code"] == "APIKEY_REVOKED"


def test_set_password_revokes_every_api_key_the_user_holds(
    app: FastAPI, client: TestClient
) -> None:
    """Resetting a user's password revokes the API keys they minted, not only their sessions."""
    principal_id = _create_user(client, username="bob")
    key_client = TestClient(app)
    secret = _mint_api_key(key_client, subject="bob")
    assert (
        key_client.get("/auth/session", headers={"Authorization": f"Bearer {secret}"}).status_code
        == 200
    )

    reset = client.put(
        f"/api/v1/users/{principal_id}/password",
        json={"password": "bobs-second-password"},
        headers=_headers("root"),
    )
    assert reset.status_code == 200

    revoked = key_client.get("/auth/session", headers={"Authorization": f"Bearer {secret}"})
    assert revoked.status_code == 401
    assert revoked.json()["code"] == "APIKEY_REVOKED"


def test_disable_404s_for_an_unknown_principal_id(client: TestClient) -> None:
    """Disabling an unknown principal id 404s."""
    response = client.post(f"/api/v1/users/{uuid4()}/disable", headers=_headers("root"))
    assert response.status_code == 404


class _VanishingPrincipalStore(MemoryPrincipalStore):
    """A principal store whose disable() always reports hitting no row.

    Stands in for the principal disappearing between ``_existing_user``'s
    read and the write that follows it, two separate store round trips
    with no transaction across them. The existence check must not be
    trusted to still hold by the time the write runs.
    """

    async def disable(self, principal_id: UUID, *, disabled_at: datetime) -> PrincipalRecord | None:
        """Always reports no matching row, simulating the principal vanishing before the write."""
        return None


def test_disable_404s_when_the_principal_is_gone_by_the_time_the_write_runs(
    tmp_path: Path,
) -> None:
    """Disable still 404s when the principal vanishes between the existence check and the write."""
    account = PrincipalRecord(
        id=uuid4(),
        kind="user",
        subject="grace",
        display_name="Grace",
        idp_subject=None,
        disabled_at=None,
        created_at=datetime.now(UTC),
    )
    stores = dataclasses.replace(
        memory_stores(), principals=_VanishingPrincipalStore({account.id: account})
    )
    with TestClient(create_app(settings=_settings(tmp_path), stores=stores)) as client:
        response = client.post(f"/api/v1/users/{account.id}/disable", headers=_headers("root"))
    assert response.status_code == 404
