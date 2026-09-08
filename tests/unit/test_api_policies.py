"""Policy routes not already exercised by the RBAC delegation scenario.

Beyond ``test_api_rbac.py::test_policy_attachment_requires_the_scoped_capability``,
this covers listing the catalog, attaching a policy to a project or a
dataset rather than an organization, the ordering and pagination of the
listing, and the ``spec`` byte ceiling enforced on creation alone.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from huron.applications.api.app import create_app
from huron.applications.api.routes.v1.schema.policies import MAX_POLICY_SPEC_BYTES
from huron.applications.api.settings import ApiSettings, ClassificationValue
from huron.pkg.catalog.manifest import MAX_SAFE_INT, canonical_bytes
from huron.pkg.metastore import InMemoryRbacStore
from tests.unit.support import memory_stores

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from fastapi import FastAPI

    from huron.core._catalog import HierarchyRepository
    from huron.pkg.catalog.records import Policy

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
def app(tmp_path: Path) -> FastAPI:
    """The FastAPI app wired to a fresh in-memory store set."""
    return create_app(settings=_settings(tmp_path), stores=memory_stores())


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """A TestClient over `app`, for tests that only need to drive the HTTP surface."""
    with TestClient(app) as client:
        yield client


@pytest.fixture
def repository(client: TestClient) -> HierarchyRepository:
    """The repository the running app's lifespan built, reachable for direct seeding."""
    return client.app.state.runtime.repository


def _headers(subject: str) -> dict[str, str]:
    """Auth and idempotency headers for `subject`, with a fresh Idempotency-Key each call."""
    return {"X-Huron-Subject": subject, "Idempotency-Key": str(uuid4())}


def _create_policy(client: TestClient, *, name: str = "raw-90d") -> str:
    """Creates a retention policy named `name` and returns its id, failing loudly if refused."""
    response = client.post(
        "/api/v1/policies",
        json={"policy_type": "retention", "name": name, "spec": {"days": 90}},
        headers=_headers("root"),
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _spec_padded_to(size: int) -> dict[str, object]:
    """A spec whose RFC 8785 canonical form is exactly ``size`` bytes.

    Built by measuring an unpadded spec and growing one string field by
    exactly the shortfall - the same measure the request-side ceiling
    itself uses, so the boundary in the test is exact rather than
    approximate.
    """
    spec: dict[str, object] = {"pad": ""}
    base = len(canonical_bytes(spec))
    spec["pad"] = "a" * (size - base)
    assert len(canonical_bytes(spec)) == size
    return spec


def test_policies_can_be_listed_by_any_authenticated_caller(client: TestClient) -> None:
    """Any authenticated caller can list policies, seeing the ones already created."""
    _create_policy(client)
    response = client.get("/api/v1/policies", headers=_headers("anyone"))
    assert response.status_code == 200
    body = response.json()
    assert body["next_cursor"] is None
    names = {item["name"] for item in body["items"]}
    assert "raw-90d" in names


def test_created_policy_response_publishes_exactly_the_declared_fields(
    client: TestClient,
) -> None:
    """A created policy's response body publishes exactly its declared fields, nothing more."""
    response = client.post(
        "/api/v1/policies",
        json={"policy_type": "retention", "name": "raw-90d", "spec": {"days": 90}},
        headers=_headers("root"),
    )
    assert response.status_code == 201
    assert set(response.json()) == {
        "id",
        "policy_type",
        "name",
        "spec",
        "created_by",
        "created_at",
    }


def test_policy_spec_publishes_as_an_inline_schema_not_a_named_component(
    app: FastAPI,
) -> None:
    """``spec`` publishes as an inline object schema, not a named ``PolicySpec`` component.

    ``spec`` is opaque caller JSON with no fields of its own; the OpenAPI
    document must describe it inline on ``CreatePolicy`` and ``PolicyView``
    rather than factoring it into a ``PolicySpec`` component that implies a
    shape the service does not actually constrain.
    """
    schema = app.openapi()
    assert "PolicySpec" not in schema["components"]["schemas"]
    inline_spec_schema = {"type": "object", "additionalProperties": True, "title": "Spec"}
    create_policy = schema["components"]["schemas"]["CreatePolicy"]
    policy_view = schema["components"]["schemas"]["PolicyView"]
    assert create_policy["properties"]["spec"] == inline_spec_schema
    assert policy_view["properties"]["spec"] == inline_spec_schema


def test_policies_are_ordered_by_name(client: TestClient) -> None:
    """Policies list in name order regardless of the order they were created in."""
    for name in ["charlie", "alpha", "bravo"]:
        _create_policy(client, name=name)
    response = client.get("/api/v1/policies", headers=_headers("root"))
    assert response.status_code == 200
    names = [item["name"] for item in response.json()["items"]]
    assert names == sorted(names)


def test_policies_rejects_an_out_of_range_limit(client: TestClient) -> None:
    """A limit outside the allowed range is rejected with 422."""
    response = client.get("/api/v1/policies", params={"limit": 5000}, headers=_headers("root"))
    assert response.status_code == 422


class _ReversedOrderRbacStore(InMemoryRbacStore):
    """A store that hands policies back in the opposite of its own order.

    Stands in for any future ``RbacStore`` whose ``ORDER BY`` disagrees with
    ``(name, str(id))``; the list handler must re-sort what it is given
    rather than trust the store's ordering.
    """

    async def list_policies(self) -> list[Policy]:
        """The base store's policies, reversed, to prove the caller does not trust store order."""
        return list(reversed(await super().list_policies()))


async def test_the_boundary_orders_policies_whatever_order_the_store_returns(
    tmp_path: Path,
) -> None:
    """The route re-sorts by name whatever order the RBAC store hands its policies back in."""
    settings = _settings(tmp_path)
    stores = dataclasses.replace(memory_stores(), rbac=_ReversedOrderRbacStore())
    with TestClient(create_app(settings=settings, stores=stores)) as client:
        for name in ["charlie", "alpha", "bravo"]:
            _create_policy(client, name=name)
        response = client.get("/api/v1/policies", headers=_headers("root"))
        assert response.status_code == 200
        names = [item["name"] for item in response.json()["items"]]
        assert names == sorted(names)


def test_a_spec_at_the_byte_ceiling_is_accepted(client: TestClient) -> None:
    """A spec exactly at the byte ceiling is accepted."""
    spec = _spec_padded_to(MAX_POLICY_SPEC_BYTES)
    response = client.post(
        "/api/v1/policies",
        json={"policy_type": "retention", "name": "at-ceiling", "spec": spec},
        headers=_headers("root"),
    )
    assert response.status_code == 201, response.text


def test_a_spec_one_byte_over_the_ceiling_is_rejected(client: TestClient) -> None:
    """A spec one byte over the byte ceiling is rejected with 422."""
    spec = _spec_padded_to(MAX_POLICY_SPEC_BYTES + 1)
    response = client.post(
        "/api/v1/policies",
        json={"policy_type": "retention", "name": "over-ceiling", "spec": spec},
        headers=_headers("root"),
    )
    assert response.status_code == 422


async def test_a_spec_that_reached_storage_over_the_ceiling_is_still_read_back_whole(
    repository: HierarchyRepository, client: TestClient
) -> None:
    """The ceiling binds ``CreatePolicy`` alone.

    A spec already in storage - seeded directly here, standing in for
    anything that reached storage some other way than this route - is
    still returned in full by ``GET /policies``, unbounded and untruncated.
    """
    oversized = _spec_padded_to(MAX_POLICY_SPEC_BYTES + 1)
    await repository.create_policy(
        policy_type="retention", name="grandfathered", spec=oversized, created_by="root"
    )
    response = client.get("/api/v1/policies", headers=_headers("root"))
    assert response.status_code == 200
    (item,) = [entry for entry in response.json()["items"] if entry["name"] == "grandfathered"]
    assert len(canonical_bytes(item["spec"])) == MAX_POLICY_SPEC_BYTES + 1


def test_a_spec_with_an_integer_outside_the_canonicalization_range_is_rejected(
    client: TestClient,
) -> None:
    """A spec that fails to canonicalize is rejected the same way as one that is merely too large.

    A spec that cannot be canonicalized at all fails for the same reason -
    and on the same path - as one that canonicalizes but is too large.
    """
    response = client.post(
        "/api/v1/policies",
        json={
            "policy_type": "retention",
            "name": "unsafe-int",
            "spec": {"count": MAX_SAFE_INT + 1},
        },
        headers=_headers("root"),
    )
    assert response.status_code == 422


def _create_organization(client: TestClient) -> str:
    """Creates an organization and returns its id, failing loudly if refused."""
    response = client.post(
        "/api/v1/organizations",
        json={"slug": "geo-org", "title": "Geo"},
        headers=_headers("root"),
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _create_project(client: TestClient, organization_id: str) -> str:
    """Creates a project under `organization_id` and returns its id, failing loudly if refused."""
    response = client.post(
        f"/api/v1/organizations/{organization_id}/projects",
        json={"slug": "sims-proj", "title": "Sims", "data_classification": "open"},
        headers=_headers("root"),
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _create_dataset(client: TestClient, project_id: str) -> str:
    """Creates a dataset under `project_id` and returns its id, failing loudly if refused."""
    response = client.post(
        f"/api/v1/projects/{project_id}/datasets",
        json={"slug": "run-0001", "title": "Run", "profile_name": "p", "profile_version": "1"},
        headers=_headers("root"),
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def test_attaching_to_an_organization_with_a_malformed_policy_id_is_rejected_as_invalid(
    client: TestClient,
) -> None:
    """A malformed ``policy_id`` is a schema violation (422), never an internal error."""
    organization_id = _create_organization(client)
    response = client.post(
        f"/api/v1/organizations/{organization_id}/policy-attachments",
        json={"policy_id": "not-a-uuid"},
        headers=_headers("root"),
    )
    assert response.status_code == 422
    assert response.json()["code"] == "REQUEST_INVALID"


def test_attaching_to_a_project_with_a_malformed_policy_id_is_rejected_as_invalid(
    client: TestClient,
) -> None:
    """A malformed ``policy_id`` is a schema violation (422), never an internal error."""
    organization_id = _create_organization(client)
    project_id = _create_project(client, organization_id)
    response = client.post(
        f"/api/v1/projects/{project_id}/policy-attachments",
        json={"policy_id": "not-a-uuid"},
        headers=_headers("root"),
    )
    assert response.status_code == 422
    assert response.json()["code"] == "REQUEST_INVALID"


def test_attaching_to_a_dataset_with_a_malformed_policy_id_is_rejected_as_invalid(
    client: TestClient,
) -> None:
    """A malformed ``policy_id`` is a schema violation (422), never an internal error."""
    organization_id = _create_organization(client)
    project_id = _create_project(client, organization_id)
    dataset_id = _create_dataset(client, project_id)
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/policy-attachments",
        json={"policy_id": "not-a-uuid"},
        headers=_headers("root"),
    )
    assert response.status_code == 422
    assert response.json()["code"] == "REQUEST_INVALID"


def test_a_policy_can_be_attached_to_a_project(client: TestClient) -> None:
    """Attaching a policy to a project needs the capability and reports scope_type PROJECT."""
    organization_id = _create_organization(client)
    project_id = _create_project(client, organization_id)
    policy_id = _create_policy(client)

    # mallory holds no bindings anywhere, so the project is outside her
    # visibility too: 404, not 403.
    denied = client.post(
        f"/api/v1/projects/{project_id}/policy-attachments",
        json={"policy_id": policy_id},
        headers=_headers("mallory"),
    )
    assert denied.status_code == 404

    attached = client.post(
        f"/api/v1/projects/{project_id}/policy-attachments",
        json={"policy_id": policy_id},
        headers=_headers("root"),
    )
    assert attached.status_code == 201
    body = attached.json()
    assert body["scope_type"] == "PROJECT"
    assert set(body) == {"policy_id", "scope_type", "scope_id", "attached_by", "attached_at"}


def test_a_policy_can_be_attached_to_a_dataset(client: TestClient) -> None:
    """Attaching a policy to a dataset needs the capability and reports scope_type DATASET."""
    organization_id = _create_organization(client)
    project_id = _create_project(client, organization_id)
    dataset_id = _create_dataset(client, project_id)
    policy_id = _create_policy(client)

    # mallory holds no bindings anywhere, so the dataset is outside her
    # visibility too: 404, not 403.
    denied = client.post(
        f"/api/v1/datasets/{dataset_id}/policy-attachments",
        json={"policy_id": policy_id},
        headers=_headers("mallory"),
    )
    assert denied.status_code == 404

    attached = client.post(
        f"/api/v1/datasets/{dataset_id}/policy-attachments",
        json={"policy_id": policy_id},
        headers=_headers("root"),
    )
    assert attached.status_code == 201
    body = attached.json()
    assert body["scope_type"] == "DATASET"
    assert set(body) == {"policy_id", "scope_type", "scope_id", "attached_by", "attached_at"}
