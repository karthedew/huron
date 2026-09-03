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
    """A TestClient with root bootstrapped as platform owner, its lifespan startup already run."""
    settings = ApiSettings(
        env="development",
        auth_mode="dev-headers",
        data_root=str(tmp_path / "data"),
        database_url="postgresql://unused",
        classification_vocabulary=[ClassificationValue(code="open", order=0, discoverable=True)],
        bootstrap_platform_owner="root",
    )
    repository = HierarchyRepository(
        PosixRawStore(settings.data_root),
        classification_vocabulary=tuple(value.code for value in settings.classification_vocabulary),
    )
    # Entered as a context manager so the ASGI lifespan actually runs and
    # performs the one-time bootstrap grant below - a TestClient built
    # without ``with`` never fires startup/shutdown events at all.
    with TestClient(create_app(settings=settings, repository=repository)) as client:
        yield client


def _headers(subject: str, groups: str = "") -> dict[str, str]:
    """Auth headers for `subject` with a fresh Idempotency-Key, plus X-Huron-Groups when given."""
    headers = {"X-Huron-Subject": subject, "Idempotency-Key": str(uuid4())}
    if groups:
        headers["X-Huron-Groups"] = groups
    return headers


def test_rbac_delegation_and_layer_writes(client: TestClient) -> None:
    """Delegation gates each step; a developer writes raw/bronze, a service account silver/gold."""
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

    # alice creates the pipeline service account and mints its key.
    account = client.post(
        f"/api/v1/organizations/{organization_id}/service-accounts",
        json={"name": "canonicalizer"},
        headers=_headers("alice"),
    )
    assert account.status_code == 201
    subject = account.json()["subject"]
    principal_id = account.json()["principal_id"]
    key = client.post(
        f"/api/v1/organizations/{organization_id}/service-accounts/{principal_id}/api-keys",
        json={"name": "ci"},
        headers=_headers("alice"),
    )
    assert key.status_code == 201
    token = key.json()["secret"]

    # Service accounts hold no roles: binding one is refused outright.
    assert (
        client.post(
            f"/api/v1/projects/{project_id}/bindings",
            json={"principal": f"sa:{subject}", "role": "reader"},
            headers=_headers("alice"),
        ).status_code
        == 422
    )

    # Its authority is intrinsic - no binding step. Silver and gold only:
    # raw and bronze are the human contribution surface.
    service_headers = {"Authorization": f"Bearer {token}"}
    session_info = client.get("/auth/session", headers=service_headers)
    assert session_info.json()["kind"] == "service_account"
    for layer, expected in (("silver", 201), ("gold", 201), ("bronze", 403), ("raw", 403)):
        response = client.post(
            f"/api/v1/datasets/{dataset_id}/layers/{layer}/write-intents",
            headers=service_headers,
        )
        assert response.status_code == expected, layer

    # Dataset CRUD is part of that intrinsic authority (direct entry mints
    # the dataset a feed is about to fill) - org-wide, so this project too.
    assert (
        client.post(
            f"/api/v1/projects/{project_id}/datasets",
            json={
                "slug": "feed-0001",
                "title": "Feed 1",
                "profile_name": "neutron-monitor",
                "profile_version": "2.1",
                "entry_layer": "silver",
            },
            headers={**service_headers, "Idempotency-Key": str(uuid4())},
        ).status_code
        == 201
    )

    disabled = client.post(
        f"/api/v1/organizations/{organization_id}/service-accounts/{principal_id}/disable",
        headers=_headers("alice"),
    )
    assert disabled.status_code == 200
    assert disabled.json()["disabled_at"] is not None
    assert client.get("/auth/session", headers=service_headers).status_code == 401


def test_policy_attachment_requires_the_scoped_capability(client: TestClient) -> None:
    """A caller is denied unless bound, and only the platform owner may attach an org policy."""
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


def test_issuing_an_api_key_requires_an_idempotency_key(client: TestClient) -> None:
    """Minting an API key requires a present, non-empty Idempotency-Key header."""
    headers = _headers("root")
    del headers["Idempotency-Key"]
    missing = client.post("/api/v1/auth/api-keys", json={"name": "laptop"}, headers=headers)
    assert missing.status_code == 422

    empty = client.post(
        "/api/v1/auth/api-keys",
        json={"name": "laptop"},
        headers={**headers, "Idempotency-Key": ""},
    )
    assert empty.status_code == 422


def test_api_keys_inherit_the_callers_identity(client: TestClient) -> None:
    """An issued API key resolves back to the issuing user's own identity and SYSTEM-scope roles."""
    issued = client.post(
        "/api/v1/auth/api-keys",
        json={"name": "laptop"},
        headers=_headers("root"),
    )
    assert issued.status_code == 201
    token = issued.json()["secret"]
    info = client.get("/auth/session", headers={"Authorization": f"Bearer {token}"}).json()
    identity = {key: value for key, value in info.items() if key != "effective_roles"}
    assert identity == {
        "subject": "root",
        "kind": "user",
        "groups": [],
        "authentication_method": "api-key",
        "csrf_token": None,
        "expires_at": None,
    }
    # A bearer credential resolves the same binding set a cookie session
    # would - the bootstrap platform owner's one SYSTEM-scope grant.
    assert [entry["scope_type"] for entry in info["effective_roles"]] == ["SYSTEM"]


def test_slugs_are_immutable_at_every_level_for_every_role(client: TestClient) -> None:
    """A slug never changes once created, not for an organization admin nor the platform owner.

    A slug is baked into the storage path, so it never changes - not for an
    organization admin, and not for the platform owner either.
    """
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
