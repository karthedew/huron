"""Service-account routes and error paths not already exercised by the RBAC scenario.

Beyond ``test_api_rbac.py``'s pipeline-service-account scenario, covers
listing service accounts, the ordering and pagination of that list, the
two refusals ``issue_service_account_key`` and ``disable_service_account``
share - a principal that belongs to a different organization, and (for
key issuance) one that is already disabled - and the shape of a freshly
minted key.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from huron.applications.api.app import create_app
from huron.applications.api.routes.v1.schema.service_accounts import IssuedServiceAccountKey
from huron.applications.api.settings import ApiSettings, ClassificationValue
from huron.pkg.auth.apikeys import ApiKeyRecord, MemoryApiKeyStore
from huron.pkg.metastore import InMemoryRbacStore
from tests.unit.support import memory_stores

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path
    from uuid import UUID

    from huron.pkg.catalog.records import ServiceAccount

pytestmark = pytest.mark.unit


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
def client(tmp_path: Path) -> Iterator[TestClient]:
    """A TestClient with root bootstrapped as platform owner, backed by a fresh repository."""
    settings = _settings(tmp_path)
    with TestClient(create_app(settings=settings, stores=memory_stores())) as client:
        yield client


def _headers(subject: str) -> dict[str, str]:
    """Auth and idempotency headers for `subject`, with a fresh Idempotency-Key each call."""
    return {"X-Huron-Subject": subject, "Idempotency-Key": str(uuid4())}


def _organization(client: TestClient, slug: str) -> str:
    """The id of a newly created organization with the given slug, created as root."""
    return client.post(
        "/api/v1/organizations", json={"slug": slug, "title": slug}, headers=_headers("root")
    ).json()["id"]


def test_service_accounts_can_be_listed(client: TestClient) -> None:
    """A newly created service account appears in that organization's listing."""
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
    """Service accounts list in name order regardless of the order they were created in."""
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
    """A limit outside the allowed range is rejected with 422."""
    organization_id = _organization(client, "astro-org")
    response = client.get(
        f"/api/v1/organizations/{organization_id}/service-accounts",
        params={"limit": 5000},
        headers=_headers("root"),
    )
    assert response.status_code == 422


class _ReversedOrderRbacStore(InMemoryRbacStore):
    """A store that hands service accounts back in the opposite of its own order.

    Stands in for any future ``RbacStore`` whose ``ORDER BY`` disagrees with
    ``(name,)``; the list handler must re-sort what it is given rather than
    trust the store's ordering.
    """

    async def list_service_accounts(self, organization_id: UUID) -> list[ServiceAccount]:
        """The base store's accounts, reversed, to prove the route doesn't trust store order."""
        return list(reversed(await super().list_service_accounts(organization_id)))


def test_the_boundary_orders_service_accounts_whatever_order_the_store_returns(
    tmp_path: Path,
) -> None:
    """The route re-sorts by name whatever order the RBAC store returns its accounts in."""
    settings = _settings(tmp_path)
    stores = dataclasses.replace(memory_stores(), rbac=_ReversedOrderRbacStore())
    with TestClient(create_app(settings=settings, stores=stores)) as client:
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
    """Issuing a key via the wrong organization's path for the account is refused with 404."""
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
    assert response.status_code == 404


def test_issuing_a_key_refuses_a_disabled_service_account(client: TestClient) -> None:
    """Issuing a key for an already-disabled service account is refused with 403."""
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
    """Disabling a service account through the wrong organization's path is refused with 404."""
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
    assert response.status_code == 404


def test_disabling_a_service_account_twice_keeps_the_original_disabled_at(
    client: TestClient,
) -> None:
    """A second disable call reports the timestamp of the first, not a later one."""
    organization_id = _organization(client, "astro-org")
    account = client.post(
        f"/api/v1/organizations/{organization_id}/service-accounts",
        json={"name": "pipeline"},
        headers=_headers("root"),
    ).json()

    first = client.post(
        f"/api/v1/organizations/{organization_id}/service-accounts/"
        f"{account['principal_id']}/disable",
        headers=_headers("root"),
    )
    second = client.post(
        f"/api/v1/organizations/{organization_id}/service-accounts/"
        f"{account['principal_id']}/disable",
        headers=_headers("root"),
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["disabled_at"] == second.json()["disabled_at"]


class _CountingApiKeyStore(MemoryApiKeyStore):
    """A ``MemoryApiKeyStore`` that counts how many times revocation is called."""

    def __init__(self) -> None:
        """Start with no keys and no recorded revocation calls."""
        super().__init__()
        self.revoke_calls = 0

    async def revoke_all_for(self, subject: str, revoked_at: datetime) -> int:
        """Record the call, then revoke as the base store would."""
        self.revoke_calls += 1
        return await super().revoke_all_for(subject, revoked_at)


def test_disabling_an_already_disabled_service_account_does_not_revoke_keys_again(
    tmp_path: Path,
) -> None:
    """A second disable call skips revocation - the account's keys were revoked at the first."""
    settings = _settings(tmp_path)
    api_keys = _CountingApiKeyStore()
    stores = dataclasses.replace(memory_stores(), api_keys=api_keys)
    with TestClient(create_app(settings=settings, stores=stores)) as client:
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
        client.post(
            f"/api/v1/organizations/{organization_id}/service-accounts/"
            f"{account['principal_id']}/disable",
            headers=_headers("root"),
        )
        assert api_keys.revoke_calls == 1


def test_an_issued_service_account_key_carries_scopes_and_the_accounts_subject(
    client: TestClient,
) -> None:
    """An issued service-account key carries its scopes, a future expiry, and the subject."""
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
    """Filling ``IssuedServiceAccountKey`` from a stored ``ApiKeyRecord`` fails outright.

    ``ApiKeyRecord`` carries ``secret_sha256`` and no plaintext secret - the
    shape a future author might reach for if they forgot the rule. Filling
    ``IssuedServiceAccountKey`` from it must fail before any field is even
    inspected, because the model declares no ``from_attributes`` config.
    """
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
