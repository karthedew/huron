"""End-to-end authorization through the HTTP surface.

Exercises the whole chain: dev-header / API-key credential -> principal ->
role bindings -> capability decision -> route. The scenario is the one the
platform is built around: a platform owner seeds an organization, delegates
to an organization admin, who delegates to a developer and creates the
pipeline service account that alone may write silver and gold.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from huron.pkg.rawstore import PosixRawStore
from huron.service.api.app import create_app
from huron.service.api.repository import HierarchyRepository
from huron.service.api.settings import ApiSettings, ClassificationValue

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = pytest.mark.unit


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    settings = ApiSettings(
        env="development",
        auth_mode="dev-headers",
        data_root=str(tmp_path / "data"),
        database_url="postgresql://unused",
        classification_vocabulary=[ClassificationValue(code="open", order=0, discoverable=True)],
        bootstrap_platform_owner="root",
    )
    repository = HierarchyRepository(PosixRawStore(settings.data_root))
    # Entered as a context manager so the ASGI lifespan actually runs and
    # performs the one-time bootstrap grant below - a TestClient built
    # without ``with`` never fires startup/shutdown events at all.
    with TestClient(create_app(settings=settings, repository=repository)) as client:
        yield client


def _headers(subject: str, groups: str = "") -> dict[str, str]:
    headers = {"X-Huron-Subject": subject, "Idempotency-Key": str(uuid4())}
    if groups:
        headers["X-Huron-Groups"] = groups
    return headers


def test_rbac_delegation_and_layer_writes(client: TestClient) -> None:
    # Unbound users can authenticate but not act.
    denied = client.post(
        "/api/v1/organizations",
        json={"slug": "astro", "title": "Astro"},
        headers=_headers("alice"),
    )
    assert denied.status_code == 403

    # The bootstrap platform owner creates the organization...
    created = client.post(
        "/api/v1/organizations",
        json={"slug": "astro", "title": "Astro"},
        headers=_headers("root"),
    )
    assert created.status_code == 201
    organization_id = created.json()["id"]

    # ...and delegates its administration to alice.
    bound = client.post(
        f"/api/v1/organizations/{organization_id}/bindings",
        json={"principal": "user:alice", "role": "organization_admin"},
        headers=_headers("root"),
    )
    assert bound.status_code == 201

    # alice can now create a project; bob (unbound) cannot.
    project = client.post(
        f"/api/v1/organizations/{organization_id}/projects",
        json={"slug": "sims", "title": "Simulations", "data_classification": "open"},
        headers=_headers("alice"),
    )
    assert project.status_code == 201
    project_id = project.json()["id"]
    assert (
        client.post(
            f"/api/v1/organizations/{organization_id}/projects",
            json={"slug": "nope", "title": "Nope", "data_classification": "open"},
            headers=_headers("bob"),
        ).status_code
        == 403
    )

    # alice grants bob developer on the project; bob creates a dataset.
    assert (
        client.post(
            f"/api/v1/projects/{project_id}/bindings",
            json={"principal": "user:bob", "role": "developer"},
            headers=_headers("alice"),
        ).status_code
        == 201
    )
    dataset = client.post(
        f"/api/v1/projects/{project_id}/datasets",
        json={
            "slug": "run-0042",
            "title": "Run 42",
            "profile_name": "mcnp-run",
            "profile_version": "1.0",
        },
        headers=_headers("bob"),
    )
    assert dataset.status_code == 201
    dataset_id = dataset.json()["id"]

    # bob may commit to raw and bronze, and to nothing above them.
    for layer, expected in (("raw", 201), ("bronze", 201), ("silver", 403), ("gold", 403)):
        response = client.post(
            f"/api/v1/datasets/{dataset_id}/layers/{layer}/write-intents",
            headers=_headers("bob"),
        )
        assert response.status_code == expected, layer

    # alice administers the org but holds no write anywhere.
    assert (
        client.post(
            f"/api/v1/datasets/{dataset_id}/layers/raw/write-intents",
            headers=_headers("alice"),
        ).status_code
        == 403
    )

    # The pipeline role refuses human principals outright.
    assert (
        client.post(
            f"/api/v1/projects/{project_id}/bindings",
            json={"principal": "user:bob", "role": "pipeline"},
            headers=_headers("alice"),
        ).status_code
        == 422
    )

    # alice creates the pipeline service account and mints its key.
    account = client.post(
        f"/api/v1/organizations/{organization_id}/service-accounts",
        json={"name": "canonicalizer"},
        headers=_headers("alice"),
    )
    assert account.status_code == 201
    principal_id = account.json()["principal_id"]
    subject = account.json()["subject"]
    key = client.post(
        f"/api/v1/organizations/{organization_id}/service-accounts/{principal_id}/api-keys",
        json={"name": "ci"},
        headers=_headers("alice"),
    )
    assert key.status_code == 201
    token = key.json()["secret"]

    # Bind pipeline to the service account at project scope.
    pipeline_binding = client.post(
        f"/api/v1/projects/{project_id}/bindings",
        json={"principal": f"sa:{subject}", "role": "pipeline"},
        headers=_headers("alice"),
    )
    assert pipeline_binding.status_code == 201
    binding_id = pipeline_binding.json()["id"]

    # The service account writes silver and gold - and not raw.
    service_headers = {"Authorization": f"Bearer {token}"}
    session_info = client.get("/auth/session", headers=service_headers)
    assert session_info.json()["kind"] == "service_account"
    for layer, expected in (("silver", 201), ("gold", 201), ("bronze", 201), ("raw", 403)):
        response = client.post(
            f"/api/v1/datasets/{dataset_id}/layers/{layer}/write-intents",
            headers=service_headers,
        )
        assert response.status_code == expected, layer

    # Revoking the binding removes the access.
    assert (
        client.delete(f"/api/v1/bindings/{binding_id}", headers=_headers("alice")).status_code
        == 204
    )
    assert (
        client.post(
            f"/api/v1/datasets/{dataset_id}/layers/silver/write-intents",
            headers=service_headers,
        ).status_code
        == 403
    )


def test_policy_attachment_requires_the_scoped_capability(client: TestClient) -> None:
    organization = client.post(
        "/api/v1/organizations",
        json={"slug": "geo", "title": "Geo"},
        headers=_headers("root"),
    )
    organization_id = organization.json()["id"]
    policy = client.post(
        "/api/v1/policies",
        json={"policy_type": "retention", "name": "raw-90d", "spec": {"days": 90}},
        headers=_headers("root"),
    )
    assert policy.status_code == 201
    policy_id = policy.json()["id"]

    # A random authenticated user cannot attach; the platform owner can.
    assert (
        client.post(
            f"/api/v1/organizations/{organization_id}/policy-attachments",
            json={"policy_id": policy_id},
            headers=_headers("mallory"),
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/organizations/{organization_id}/policy-attachments",
            json={"policy_id": policy_id},
            headers=_headers("root"),
        ).status_code
        == 201
    )


def test_api_keys_inherit_the_callers_identity(client: TestClient) -> None:
    issued = client.post(
        "/api/v1/auth/api-keys",
        json={"name": "laptop"},
        headers=_headers("root"),
    )
    assert issued.status_code == 201
    token = issued.json()["secret"]
    session_info = client.get("/auth/session", headers={"Authorization": f"Bearer {token}"})
    assert session_info.json() == {
        "subject": "root",
        "kind": "user",
        "groups": [],
        "authentication_method": "api-key",
        "csrf_token": None,
        "expires_at": None,
    }


def test_slugs_are_immutable_at_every_level_for_every_role(client: TestClient) -> None:
    """A slug is baked into the storage path, so it never changes - not for an
    organization admin, and not for the platform owner either."""
    organization = client.post(
        "/api/v1/organizations",
        json={"slug": "immutable-org", "title": "Immutable"},
        headers=_headers("root"),
    )
    organization_id = organization.json()["id"]
    project = client.post(
        f"/api/v1/organizations/{organization_id}/projects",
        json={"slug": "sims", "title": "Simulations", "data_classification": "open"},
        headers=_headers("root"),
    )
    project_id = project.json()["id"]

    # The platform owner holds every administrative capability there is, and
    # still cannot move a slug.
    refused = client.patch(
        f"/api/v1/organizations/{organization_id}",
        json={"slug": "renamed-org"},
        headers={**_headers("root"), "If-Match": "1"},
    )
    assert refused.status_code == 409
    assert refused.json()["code"] == "SLUG_IMMUTABLE"

    assert (
        client.patch(
            f"/api/v1/projects/{project_id}",
            json={"slug": "renamed-project"},
            headers={**_headers("root"), "If-Match": "1"},
        ).status_code
        == 409
    )

    # Sending the slug it already has is not a change, so the rest of the
    # patch applies normally.
    accepted = client.patch(
        f"/api/v1/organizations/{organization_id}",
        json={"slug": "immutable-org", "title": "Renamed Title"},
        headers={**_headers("root"), "If-Match": "1"},
    )
    assert accepted.status_code == 200
    assert accepted.json()["title"] == "Renamed Title"
    assert accepted.json()["slug"] == "immutable-org"
