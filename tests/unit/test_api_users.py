"""Authorized human identity disablement and API-key revocation through HTTP."""

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


def test_user_manage_is_denied_to_an_organization_admin(client: TestClient) -> None:
    """An organization admin, lacking user.manage, is denied disabling a user with 403."""
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

    denied = client.post(f"/api/v1/users/{uuid4()}/disable", headers=_headers("mallory"))
    assert denied.status_code == 403


def _mint_api_key(client: TestClient, *, subject: str) -> str:
    """Mints an API key for `subject` via dev-header self-service and returns its secret."""
    issued = client.post(
        "/api/v1/auth/api-keys", json={"name": "laptop"}, headers=_headers(subject)
    )
    assert issued.status_code == 201, issued.text
    return str(issued.json()["secret"])


def test_disable_revokes_every_api_key_the_user_holds(
    app: FastAPI, client: TestClient, stores: ApiStores
) -> None:
    """Disabling a user revokes the API keys they minted, and returns their disabled identity."""
    user = PrincipalRecord(uuid4(), "user", "alice", "Alice", None, None, datetime.now(UTC))
    stores.principals.records[user.id] = user
    principal_id = user.id
    key_client = TestClient(app)
    secret = _mint_api_key(key_client, subject="alice")
    assert (
        key_client.get(
            "/api/v1/organizations", headers={"Authorization": f"Bearer {secret}"}
        ).status_code
        == 200
    )

    disabled = client.post(f"/api/v1/users/{principal_id}/disable", headers=_headers("root"))
    assert disabled.status_code == 200
    assert disabled.json()["disabled_at"] is not None
    assert set(disabled.json()) == {"id", "subject", "display_name", "disabled_at", "created_at"}

    revoked = key_client.get("/api/v1/organizations", headers={"Authorization": f"Bearer {secret}"})
    assert revoked.status_code == 401
    assert revoked.json()["code"] == "APIKEY_REVOKED"


def test_disable_refuses_a_service_account_id(client: TestClient, stores: ApiStores) -> None:
    """A service-account identity is refused with a kind conflict and remains enabled."""
    account = PrincipalRecord(
        uuid4(), "service_account", "astro/pipeline", "Pipeline", None, None, datetime.now(UTC)
    )
    stores.principals.records[account.id] = account

    response = client.post(f"/api/v1/users/{account.id}/disable", headers=_headers("root"))

    assert response.status_code == 409
    assert response.json()["code"] == "PRINCIPAL_KIND_MISMATCH"
    assert stores.principals.records[account.id] == account


def test_disable_404s_for_an_unknown_principal_id(client: TestClient) -> None:
    """Disabling an unknown principal id 404s."""
    response = client.post(f"/api/v1/users/{uuid4()}/disable", headers=_headers("root"))
    assert response.status_code == 404


class _VanishingPrincipalStore(MemoryPrincipalStore):
    """A principal store whose disable() always reports hitting no row.

    Stands in for the principal disappearing between the identity service's
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
