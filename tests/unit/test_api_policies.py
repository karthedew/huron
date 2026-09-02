"""Policy routes not already exercised by
``test_api_rbac.py::test_policy_attachment_requires_the_scoped_capability``:
listing the catalog, attaching a policy to a project or a dataset rather
than an organization, the ordering and pagination of the listing, and the
``spec`` byte ceiling enforced on creation alone."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from huron.pkg.catalog.manifest import MAX_SAFE_INT, canonical_bytes
from huron.pkg.rawstore import PosixRawStore
from huron.service.api.app import create_app
from huron.service.api.repository import HierarchyRepository
from huron.service.api.routes.v1.schema.policies import MAX_POLICY_SPEC_BYTES
from huron.service.api.settings import ApiSettings, ClassificationValue
from huron.service.api.stores import InMemoryRbacStore

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from fastapi import FastAPI

    from huron.service.api.records import Policy

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
def repository(tmp_path: Path) -> HierarchyRepository:
    settings = _settings(tmp_path)
    return HierarchyRepository(
        PosixRawStore(settings.data_root),
        classification_vocabulary=tuple(value.code for value in settings.classification_vocabulary),
    )


@pytest.fixture
def app(tmp_path: Path, repository: HierarchyRepository) -> FastAPI:
    return create_app(settings=_settings(tmp_path), repository=repository)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as client:
        yield client


def _headers(subject: str) -> dict[str, str]:
    return {"X-Huron-Subject": subject, "Idempotency-Key": str(uuid4())}


def _create_policy(client: TestClient, *, name: str = "raw-90d") -> str:
    response = client.post(
        "/api/v1/policies",
        json={"policy_type": "retention", "name": name, "spec": {"days": 90}},
        headers=_headers("root"),
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _spec_padded_to(size: int) -> dict[str, object]:
    """Build a spec whose RFC 8785 canonical form is exactly ``size`` bytes,
    by measuring an unpadded spec and growing one string field by exactly
    the shortfall - the same measure the request-side ceiling itself uses,
    so the boundary in the test is exact rather than approximate."""
    spec: dict[str, object] = {"pad": ""}
    base = len(canonical_bytes(spec))
    spec["pad"] = "a" * (size - base)
    assert len(canonical_bytes(spec)) == size
    return spec


def test_policies_can_be_listed_by_any_authenticated_caller(client: TestClient) -> None:
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
    """``spec`` is opaque caller JSON with no fields of its own; the OpenAPI
    document must describe it inline on ``CreatePolicy`` and ``PolicyView``
    rather than factoring it into a ``PolicySpec`` component that implies a
    shape the service does not actually constrain."""
    schema = app.openapi()
    assert "PolicySpec" not in schema["components"]["schemas"]
    inline_spec_schema = {"type": "object", "additionalProperties": True, "title": "Spec"}
    create_policy = schema["components"]["schemas"]["CreatePolicy"]
    policy_view = schema["components"]["schemas"]["PolicyView"]
    assert create_policy["properties"]["spec"] == inline_spec_schema
    assert policy_view["properties"]["spec"] == inline_spec_schema


def test_policies_are_ordered_by_name(client: TestClient) -> None:
    for name in ["charlie", "alpha", "bravo"]:
        _create_policy(client, name=name)
    response = client.get("/api/v1/policies", headers=_headers("root"))
    assert response.status_code == 200
    names = [item["name"] for item in response.json()["items"]]
    assert names == sorted(names)


def test_policies_rejects_an_out_of_range_limit(client: TestClient) -> None:
    response = client.get("/api/v1/policies", params={"limit": 5000}, headers=_headers("root"))
    assert response.status_code == 422


class _ReversedOrderRbacStore(InMemoryRbacStore):
    """A store that hands policies back in the opposite of its own order -
    stands in for any future ``RbacStore`` whose ``ORDER BY`` disagrees with
    ``(name, str(id))``; the list handler must re-sort what it is given
    rather than trust the store's ordering."""

    async def list_policies(self) -> list[Policy]:
        return list(reversed(await super().list_policies()))


async def test_the_boundary_orders_policies_whatever_order_the_store_returns(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    repository = HierarchyRepository(
        PosixRawStore(settings.data_root),
        classification_vocabulary=tuple(value.code for value in settings.classification_vocabulary),
        rbac_store=_ReversedOrderRbacStore(),
    )
    with TestClient(create_app(settings=settings, repository=repository)) as client:
        for name in ["charlie", "alpha", "bravo"]:
            _create_policy(client, name=name)
        response = client.get("/api/v1/policies", headers=_headers("root"))
        assert response.status_code == 200
        names = [item["name"] for item in response.json()["items"]]
        assert names == sorted(names)


def test_a_spec_at_the_byte_ceiling_is_accepted(client: TestClient) -> None:
    spec = _spec_padded_to(MAX_POLICY_SPEC_BYTES)
    response = client.post(
        "/api/v1/policies",
        json={"policy_type": "retention", "name": "at-ceiling", "spec": spec},
        headers=_headers("root"),
    )
    assert response.status_code == 201, response.text


def test_a_spec_one_byte_over_the_ceiling_is_rejected(client: TestClient) -> None:
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
    """The ceiling binds ``CreatePolicy`` alone. A spec already in storage -
    seeded directly here, standing in for anything that reached storage some
    other way than this route - is still returned in full by ``GET
    /policies``, unbounded and untruncated."""
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
    """A spec that cannot be canonicalized at all fails for the same reason
    - and on the same path - as one that canonicalizes but is too large."""
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


def test_a_policy_can_be_attached_to_a_project(client: TestClient) -> None:
    organization_id = client.post(
        "/api/v1/organizations", json={"slug": "geo-org", "title": "Geo"}, headers=_headers("root")
    ).json()["id"]
    project_id = client.post(
        f"/api/v1/organizations/{organization_id}/projects",
        json={"slug": "sims-proj", "title": "Sims", "data_classification": "open"},
        headers=_headers("root"),
    ).json()["id"]
    policy_id = _create_policy(client)

    denied = client.post(
        f"/api/v1/projects/{project_id}/policy-attachments",
        json={"policy_id": policy_id},
        headers=_headers("mallory"),
    )
    assert denied.status_code == 403

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
    organization_id = client.post(
        "/api/v1/organizations", json={"slug": "geo-org", "title": "Geo"}, headers=_headers("root")
    ).json()["id"]
    project_id = client.post(
        f"/api/v1/organizations/{organization_id}/projects",
        json={"slug": "sims-proj", "title": "Sims", "data_classification": "open"},
        headers=_headers("root"),
    ).json()["id"]
    dataset_id = client.post(
        f"/api/v1/projects/{project_id}/datasets",
        json={"slug": "run-0001", "title": "Run", "profile_name": "p", "profile_version": "1"},
        headers=_headers("root"),
    ).json()["id"]
    policy_id = _create_policy(client)

    denied = client.post(
        f"/api/v1/datasets/{dataset_id}/policy-attachments",
        json={"policy_id": policy_id},
        headers=_headers("mallory"),
    )
    assert denied.status_code == 403

    attached = client.post(
        f"/api/v1/datasets/{dataset_id}/policy-attachments",
        json={"policy_id": policy_id},
        headers=_headers("root"),
    )
    assert attached.status_code == 201
    body = attached.json()
    assert body["scope_type"] == "DATASET"
    assert set(body) == {"policy_id", "scope_type", "scope_id", "attached_by", "attached_at"}
