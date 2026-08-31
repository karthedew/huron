"""Admin-provisioned password users through the HTTP surface: the
``user.manage`` guard, the duplicate-subject refusal shared by memory and
Postgres principal stores, and the two write routes' session-revoking side
effects."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from huron.pkg.auth import PrincipalRecord
from huron.pkg.rawstore import PosixRawStore
from huron.service.api.app import create_app
from huron.service.api.repository import HierarchyRepository
from huron.service.api.settings import ApiSettings, ClassificationValue

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from fastapi import FastAPI

pytestmark = pytest.mark.unit


def _headers(subject: str) -> dict[str, str]:
    return {"X-Huron-Subject": subject, "Idempotency-Key": str(uuid4())}


@pytest.fixture
def repository(tmp_path: Path) -> HierarchyRepository:
    return HierarchyRepository(PosixRawStore(str(tmp_path / "data")))


@pytest.fixture
def app(tmp_path: Path, repository: HierarchyRepository) -> FastAPI:
    settings = ApiSettings(
        env="development",
        auth_mode="dev-headers",
        data_root=str(tmp_path / "data"),
        database_url="postgresql://unused",
        classification_vocabulary=[ClassificationValue(code="open", order=0, discoverable=True)],
        bootstrap_platform_owner="root",
    )
    return create_app(settings=settings, repository=repository)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    # Entered as a context manager so the bootstrap grant actually runs -
    # see test_api_rbac.py's identical fixture for why.
    with TestClient(app) as client:
        yield client


def _create_user(client: TestClient, *, username: str, password: str = "a-strong-password") -> str:
    response = client.post(
        "/api/v1/users",
        json={"username": username, "display_name": username.title(), "password": password},
        headers=_headers("root"),
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def test_user_manage_is_denied_to_an_organization_admin(client: TestClient) -> None:
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
    response = client.post(
        "/api/v1/users",
        json={"username": "dana", "display_name": "Dana", "password": "a-strong-password"},
        headers=_headers("root"),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["kind"] == "user"
    assert body["subject"] == "dana"
    assert body["idp_subject"] is None
    assert body["disabled_at"] is None
    assert "password" not in body
    assert "password_hash" not in body


def test_create_user_refuses_a_subject_that_already_exists(client: TestClient) -> None:
    _create_user(client, username="dana")
    conflict = client.post(
        "/api/v1/users",
        json={"username": "dana", "display_name": "Someone Else", "password": "another-password"},
        headers=_headers("root"),
    )
    assert conflict.status_code == 400
    assert "dana" in conflict.json()["detail"]


def test_set_password_refuses_a_service_account_id_with_an_honest_error(
    client: TestClient, repository: HierarchyRepository
) -> None:
    """A service account can never legitimately reach this route - the
    kind guard here must say so plainly, not report "does not exist" the
    way the Postgres kind-guard trigger's generic RaiseError would if this
    route let a mismatched id fall all the way through to it. Service
    accounts live in ``rbac_store`` for the memory backend (there is no
    unified ``principals`` table the way Postgres has one), so the
    ``principals`` row is seeded directly here, the same seam
    ``test_api_login.py`` uses for its own service-account scenario."""
    account = PrincipalRecord(
        id=uuid4(),
        kind="service_account",
        subject="astro/pipeline",
        display_name="",
        idp_subject=None,
        disabled_at=None,
        created_at=datetime.now(UTC),
    )
    repository.principals.records[account.id] = account

    response = client.put(
        f"/api/v1/users/{account.id}/password",
        json={"password": "a-strong-password"},
        headers=_headers("root"),
    )
    assert response.status_code == 400
    assert "not a user" in response.json()["detail"]


def test_set_password_404s_for_an_unknown_principal_id(client: TestClient) -> None:
    response = client.put(
        f"/api/v1/users/{uuid4()}/password",
        json={"password": "a-strong-password"},
        headers=_headers("root"),
    )
    assert response.status_code == 404


def test_password_reset_revokes_every_session_for_that_subject(
    app: FastAPI, client: TestClient
) -> None:
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


def test_disable_404s_for_an_unknown_principal_id(client: TestClient) -> None:
    response = client.post(f"/api/v1/users/{uuid4()}/disable", headers=_headers("root"))
    assert response.status_code == 404
