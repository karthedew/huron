"""``POST /auth/login`` and ``POST /auth/logout`` through the HTTP surface:
the cookie a successful login sets, the CSRF rule that gated write governs,
the generic refusal a wrong credential gets, and the two kind guards a
password login must honor (disabled, service account) exactly as the
password-lookup seam already enforces at the store level."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from huron.pkg.auth import PrincipalRecord, make_credential
from huron.pkg.rawstore import PosixRawStore
from huron.service.api.app import create_app
from huron.service.api.repository import HierarchyRepository
from huron.service.api.settings import ApiSettings, ClassificationValue, OidcSettings

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = pytest.mark.unit

PASSWORD = "correct-horse-battery-staple"


def _settings(tmp_path: Path, *, password_login_enabled: bool = True) -> ApiSettings:
    return ApiSettings(
        env="development",
        auth_mode="dev-headers",
        data_root=str(tmp_path / "data"),
        database_url="postgresql://unused",
        classification_vocabulary=[ClassificationValue(code="open", order=0, discoverable=True)],
        password_login_enabled=password_login_enabled,
    )


def _repository(settings: ApiSettings) -> HierarchyRepository:
    return HierarchyRepository(PosixRawStore(settings.data_root))


def _seed_user(
    repository: HierarchyRepository,
    *,
    subject: str,
    password: str,
    kind: str = "user",
    disabled: bool = False,
) -> PrincipalRecord:
    """Populate the memory stores directly - the same seam
    ``test_auth_principals.py`` pre-seeds through - so a login test can set
    up a principal without going through the (separately tested) admin
    provisioning routes."""
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
    repository.principals.records[record.id] = record
    repository.credentials.records[record.id] = make_credential(
        record.id, password, updated_by="test-setup"
    )
    return record


@pytest.fixture
def repository(tmp_path: Path) -> HierarchyRepository:
    return _repository(_settings(tmp_path))


@pytest.fixture
def client(tmp_path: Path, repository: HierarchyRepository) -> Iterator[TestClient]:
    settings = _settings(tmp_path)
    with TestClient(create_app(settings=settings, repository=repository)) as client:
        yield client


# -- password login: happy path and the session it starts -------------------


def test_password_login_sets_a_cookie_and_the_session_resolves_on_the_next_request(
    client: TestClient, repository: HierarchyRepository
) -> None:
    _seed_user(repository, subject="alice", password=PASSWORD)

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


def test_password_login_rejects_the_wrong_password_with_a_generic_message(
    client: TestClient, repository: HierarchyRepository
) -> None:
    _seed_user(repository, subject="alice", password=PASSWORD)
    response = client.post("/auth/login", json={"username": "alice", "password": "nope"})
    assert response.status_code == 401
    assert response.json()["detail"] == "invalid username or password"


def test_password_login_rejects_an_unknown_username_with_the_same_generic_message(
    client: TestClient,
) -> None:
    response = client.post("/auth/login", json={"username": "nobody", "password": PASSWORD})
    assert response.status_code == 401
    assert response.json()["detail"] == "invalid username or password"


def test_password_login_refuses_a_disabled_user(
    client: TestClient, repository: HierarchyRepository
) -> None:
    _seed_user(repository, subject="dana", password=PASSWORD, disabled=True)
    response = client.post("/auth/login", json={"username": "dana", "password": PASSWORD})
    assert response.status_code == 401


def test_password_login_cannot_reach_a_service_account_even_with_a_password_row(
    client: TestClient, repository: HierarchyRepository
) -> None:
    """A ``local_credentials`` row keyed to a service-account principal id
    should never exist (the kind guard on both stores refuses it), but if
    one did, the password-login lookup still cannot reach it: it filters on
    ``kind='user'`` before a hash is ever compared."""
    _seed_user(repository, subject="astro/pipeline", password=PASSWORD, kind="service_account")
    response = client.post("/auth/login", json={"username": "astro/pipeline", "password": PASSWORD})
    assert response.status_code == 401


def test_password_login_is_refused_outright_when_disabled_by_settings(tmp_path: Path) -> None:
    settings = _settings(tmp_path, password_login_enabled=False)
    repository = _repository(settings)
    _seed_user(repository, subject="alice", password=PASSWORD)
    with TestClient(create_app(settings=settings, repository=repository)) as client:
        response = client.post("/auth/login", json={"username": "alice", "password": PASSWORD})
    assert response.status_code == 401


# -- CSRF on the one session-authed write every caller can reach: logout ----


def test_logout_without_the_csrf_header_is_refused_for_a_session_authed_caller(
    client: TestClient, repository: HierarchyRepository
) -> None:
    _seed_user(repository, subject="alice", password=PASSWORD)
    client.post("/auth/login", json={"username": "alice", "password": PASSWORD})
    response = client.post("/auth/logout")
    assert response.status_code == 401


def test_logout_with_the_csrf_header_succeeds_and_revokes_the_session(
    client: TestClient, repository: HierarchyRepository
) -> None:
    _seed_user(repository, subject="alice", password=PASSWORD)
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


def test_logout_over_bearer_needs_no_csrf_header(
    tmp_path: Path, repository: HierarchyRepository
) -> None:
    settings = _settings(tmp_path)
    with TestClient(create_app(settings=settings, repository=repository)) as client:
        issued = client.post(
            "/api/v1/auth/api-keys",
            json={"name": "laptop"},
            headers={"X-Huron-Subject": "bob", "Idempotency-Key": str(uuid4())},
        )
        assert issued.status_code == 201
        token = issued.json()["secret"]

        response = client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200


# -- /auth/providers: unauthenticated, reflects settings ---------------------


def test_providers_reports_password_only_by_default(client: TestClient) -> None:
    response = client.get("/auth/providers")
    assert response.status_code == 200
    assert response.json() == {"password": True, "oidc": False, "oidc_start_url": None}


def test_providers_reports_password_disabled(tmp_path: Path) -> None:
    settings = _settings(tmp_path, password_login_enabled=False)
    with TestClient(create_app(settings=settings, repository=_repository(settings))) as client:
        response = client.get("/auth/providers")
    assert response.json() == {"password": False, "oidc": False, "oidc_start_url": None}


def test_providers_reports_oidc_enabled_when_configured(tmp_path: Path) -> None:
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
        repository=_repository(settings),
        oidc_verify=lambda _token: {"sub": "svc"},
    )
    with TestClient(app) as client:
        response = client.get("/auth/providers")
    assert response.json() == {
        "password": True,
        "oidc": True,
        "oidc_start_url": "/auth/oidc/start",
    }
