"""Service-account routes and error paths not already exercised by
``test_api_rbac.py``'s pipeline-service-account scenario: listing service
accounts, the ordering and pagination of that list, the two refusals
``issue_service_account_key`` and ``disable_service_account`` share - a
principal that belongs to a different organization, and (for key issuance)
one that is already disabled - and the shape of a freshly minted key."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from huron.pkg.auth.apikeys import ApiKeyRecord
from huron.pkg.rawstore import PosixRawStore
from huron.service.api.app import create_app
from huron.service.api.repository import HierarchyRepository
from huron.service.api.routes.v1.schema.service_accounts import IssuedServiceAccountKey
from huron.service.api.settings import ApiSettings, ClassificationValue
from huron.service.api.stores import InMemoryRbacStore

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path
    from uuid import UUID

    from huron.service.api.records import ServiceAccount

pytestmark = pytest.mark.unit


def _settings(tmp_path: Path) -> ApiSettings:
    return ApiSettings(
        env="development",
        auth_mode="dev-headers",
        data_root=str(tmp_path / "data"),
        database_url="postgresql://unused",
        classification_vocabulary=[ClassificationValue(code="open", order=0, discoverable=True)],
        bootstrap_platform_owner="root",
    )


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    settings = _settings(tmp_path)
    repository = HierarchyRepository(
        PosixRawStore(settings.data_root),
        classification_vocabulary=tuple(value.code for value in settings.classification_vocabulary),
    )
    with TestClient(create_app(settings=settings, repository=repository)) as client:
        yield client


def _headers(subject: str) -> dict[str, str]:
    return {"X-Huron-Subject": subject, "Idempotency-Key": str(uuid4())}


def _organization(client: TestClient, slug: str) -> str:
    return client.post(
        "/api/v1/organizations", json={"slug": slug, "title": slug}, headers=_headers("root")
    ).json()["id"]


def test_service_accounts_can_be_listed(client: TestClient) -> None:
    organization_id = _organization(client, "astro-org")
    client.post(
        f"/api/v1/organizations/{organization_id}/service-accounts",
        json={"name": "pipeline"},
        headers=_headers("root"),
    )
    response = client.get(
        f"/api/v1/organizations/{organization_id}/service-accounts", headers=_headers("root")
    )
    assert response.status_code == 200
    body = response.json()
    assert body["next_cursor"] is None
    names = {item["name"] for item in body["items"]}
    assert "pipeline" in names


def test_service_accounts_are_ordered_by_name(client: TestClient) -> None:
    organization_id = _organization(client, "astro-org")
    for name in ["charlie", "alpha", "bravo"]:
        client.post(
            f"/api/v1/organizations/{organization_id}/service-accounts",
            json={"name": name},
            headers=_headers("root"),
        )
    response = client.get(
        f"/api/v1/organizations/{organization_id}/service-accounts", headers=_headers("root")
    )
    assert response.status_code == 200
    names = [item["name"] for item in response.json()["items"]]
    assert names == sorted(names)


def test_service_accounts_rejects_an_out_of_range_limit(client: TestClient) -> None:
    organization_id = _organization(client, "astro-org")
    response = client.get(
        f"/api/v1/organizations/{organization_id}/service-accounts",
        params={"limit": 5000},
        headers=_headers("root"),
    )
    assert response.status_code == 422


class _ReversedOrderRbacStore(InMemoryRbacStore):
    """A store that hands service accounts back in the opposite of its own
    order - stands in for any future ``RbacStore`` whose ``ORDER BY``
    disagrees with ``(name,)``; the list handler must re-sort what it is
    given rather than trust the store's ordering."""

    async def list_service_accounts(self, organization_id: UUID) -> list[ServiceAccount]:
        return list(reversed(await super().list_service_accounts(organization_id)))


def test_the_boundary_orders_service_accounts_whatever_order_the_store_returns(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    repository = HierarchyRepository(
        PosixRawStore(settings.data_root),
        classification_vocabulary=tuple(value.code for value in settings.classification_vocabulary),
        rbac_store=_ReversedOrderRbacStore(),
    )
    with TestClient(create_app(settings=settings, repository=repository)) as client:
        organization_id = _organization(client, "astro-org")
        for name in ["charlie", "alpha", "bravo"]:
            response = client.post(
                f"/api/v1/organizations/{organization_id}/service-accounts",
                json={"name": name},
                headers=_headers("root"),
            )
            assert response.status_code == 201

        response = client.get(
            f"/api/v1/organizations/{organization_id}/service-accounts", headers=_headers("root")
        )
        assert response.status_code == 200
        names = [item["name"] for item in response.json()["items"]]
        assert names == sorted(names)


def test_issuing_a_key_refuses_a_service_account_from_a_different_organization(
    client: TestClient,
) -> None:
    home_organization_id = _organization(client, "astro-org")
    other_organization_id = _organization(client, "geo-org")
    account = client.post(
        f"/api/v1/organizations/{home_organization_id}/service-accounts",
        json={"name": "pipeline"},
        headers=_headers("root"),
    ).json()

    response = client.post(
        f"/api/v1/organizations/{other_organization_id}/"
        f"service-accounts/{account['principal_id']}/api-keys",
        json={"name": "ci"},
        headers=_headers("root"),
    )
    assert response.status_code == 403


def test_issuing_a_key_refuses_a_disabled_service_account(client: TestClient) -> None:
    organization_id = _organization(client, "astro-org")
    account = client.post(
        f"/api/v1/organizations/{organization_id}/service-accounts",
        json={"name": "pipeline"},
        headers=_headers("root"),
    ).json()
    client.post(
        f"/api/v1/organizations/{organization_id}/service-accounts/"
        f"{account['principal_id']}/disable",
        headers=_headers("root"),
    )

    response = client.post(
        f"/api/v1/organizations/{organization_id}/service-accounts/"
        f"{account['principal_id']}/api-keys",
        json={"name": "ci"},
        headers=_headers("root"),
    )
    assert response.status_code == 403


def test_disabling_a_service_account_refuses_one_from_a_different_organization(
    client: TestClient,
) -> None:
    home_organization_id = _organization(client, "astro-org")
    other_organization_id = _organization(client, "geo-org")
    account = client.post(
        f"/api/v1/organizations/{home_organization_id}/service-accounts",
        json={"name": "pipeline"},
        headers=_headers("root"),
    ).json()

    response = client.post(
        f"/api/v1/organizations/{other_organization_id}/"
        f"service-accounts/{account['principal_id']}/disable",
        headers=_headers("root"),
    )
    assert response.status_code == 403


def test_an_issued_service_account_key_carries_scopes_and_the_accounts_subject(
    client: TestClient,
) -> None:
    organization_id = _organization(client, "astro-org")
    account = client.post(
        f"/api/v1/organizations/{organization_id}/service-accounts",
        json={"name": "pipeline"},
        headers=_headers("root"),
    ).json()

    response = client.post(
        f"/api/v1/organizations/{organization_id}/service-accounts/"
        f"{account['principal_id']}/api-keys",
        json={"name": "ci", "scopes": ["read", "write"]},
        headers=_headers("root"),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["subject"] == account["subject"]
    assert body["scopes"] == ["read", "write"]
    assert datetime.fromisoformat(body["expires_at"]) > datetime.now(UTC)
    assert set(body) == {"id", "name", "scopes", "expires_at", "secret", "subject"}


# -- the show-once rule is structural, not a convention -----------------


def test_issued_service_account_key_cannot_be_filled_from_a_stored_record() -> None:
    """``ApiKeyRecord`` carries ``secret_sha256`` and no plaintext secret - the
    shape a future author might reach for if they forgot the rule. Filling
    ``IssuedServiceAccountKey`` from it must fail before any field is even
    inspected, because the model declares no ``from_attributes`` config."""
    record = ApiKeyRecord(
        key_id="abc123",
        subject="astro-org/pipeline",
        name="ci",
        secret_sha256="0" * 64,
        scopes=frozenset({"read"}),
        project_id=None,
        expires_at=datetime.now(UTC),
    )
    with pytest.raises(ValidationError) as excinfo:
        IssuedServiceAccountKey.model_validate(record)
    (error,) = excinfo.value.errors()
    assert error["type"] == "model_type"
    assert error["loc"] == ()
