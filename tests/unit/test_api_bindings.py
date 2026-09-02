"""Role-binding routes not already exercised by the delegation scenario in
``test_api_rbac.py``: minting a SYSTEM-scope binding directly, listing
bindings at all four roots, scope inheritance into the dataset collection,
and revoking a binding at each of the four scopes it can live at."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from huron.pkg.rawstore import PosixRawStore
from huron.pkg.rbac import ScopeType
from huron.service.api.app import create_app
from huron.service.api.repository import HierarchyRepository
from huron.service.api.settings import ApiSettings, ClassificationValue
from huron.service.api.stores import InMemoryRbacStore

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from huron.service.api.records import RoleBindingRecord

pytestmark = pytest.mark.unit


@pytest.fixture
def repository(tmp_path: Path) -> HierarchyRepository:
    return HierarchyRepository(
        PosixRawStore(str(tmp_path / "data")),
        classification_vocabulary=("open",),
    )


@pytest.fixture
def client(tmp_path: Path, repository: HierarchyRepository) -> Iterator[TestClient]:
    settings = ApiSettings(
        env="development",
        auth_mode="dev-headers",
        data_root=str(tmp_path / "data"),
        database_url="postgresql://unused",
        classification_vocabulary=[ClassificationValue(code="open", order=0, discoverable=True)],
        bootstrap_platform_owner="root",
    )
    with TestClient(create_app(settings=settings, repository=repository)) as client:
        yield client


def _headers(subject: str) -> dict[str, str]:
    return {"X-Huron-Subject": subject, "Idempotency-Key": str(uuid4())}


def _hierarchy(client: TestClient) -> tuple[str, str, str]:
    """An organization, a project inside it, and a dataset inside that."""
    organization_id = client.post(
        "/api/v1/organizations",
        json={"slug": "astro-org", "title": "Astro"},
        headers=_headers("root"),
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
    return organization_id, project_id, dataset_id


def _sibling_organization(client: TestClient) -> str:
    """A second organization, unrelated to the one ``_hierarchy`` built."""
    return client.post(
        "/api/v1/organizations",
        json={"slug": "nebula-org", "title": "Nebula"},
        headers=_headers("root"),
    ).json()["id"]


def _sibling_project(client: TestClient, organization_id: str) -> str:
    """A second project in ``organization_id``, unrelated to ``_hierarchy``'s."""
    return client.post(
        f"/api/v1/organizations/{organization_id}/projects",
        json={"slug": "orbit-proj", "title": "Orbit", "data_classification": "open"},
        headers=_headers("root"),
    ).json()["id"]


#: A role bindable at each scope root, used wherever a test only needs *some*
#: binding to exist there and does not care which role it grants.
_ROOT_ROLE = {
    "system": "platform_owner",
    "organization": "organization_admin",
    "project": "developer",
    "dataset": "developer",
}


def _bindings_path(scope: str, organization_id: str, project_id: str, dataset_id: str) -> str:
    return {
        "system": "/api/v1/bindings",
        "organization": f"/api/v1/organizations/{organization_id}/bindings",
        "project": f"/api/v1/projects/{project_id}/bindings",
        "dataset": f"/api/v1/datasets/{dataset_id}/bindings",
    }[scope]


def _create_binding(
    client: TestClient, scope: str, organization_id: str, project_id: str, dataset_id: str
) -> tuple[str, dict[str, object]]:
    """Grant ``_ROOT_ROLE[scope]`` to ``user:temp`` at the named root, as ``root``."""
    path = _bindings_path(scope, organization_id, project_id, dataset_id)
    body = client.post(
        path,
        json={"principal": "user:temp", "role": _ROOT_ROLE[scope]},
        headers=_headers("root"),
    ).json()
    return path, body


def test_a_platform_owner_creates_a_system_scope_binding(client: TestClient) -> None:
    response = client.post(
        "/api/v1/bindings",
        json={"principal": "user:alice", "role": "platform_owner"},
        headers=_headers("root"),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["scope_type"] == "SYSTEM"
    assert body["scope_id"] is None
    assert body["expires_at"] is None


def test_a_binding_with_an_expiry_carries_it_forward(client: TestClient) -> None:
    response = client.post(
        "/api/v1/bindings",
        json={"principal": "user:temp", "role": "platform_owner", "expires_in_days": 30},
        headers=_headers("root"),
    )
    assert response.status_code == 201
    assert response.json()["expires_at"] is not None


def test_creating_a_system_scope_binding_is_denied_without_the_capability(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/v1/bindings",
        json={"principal": "user:alice", "role": "platform_owner"},
        headers=_headers("mallory"),
    )
    assert response.status_code == 403


def test_the_bootstrap_platform_owner_reads_the_system_bindings_roster(client: TestClient) -> None:
    response = client.get("/api/v1/bindings", headers=_headers("root"))
    assert response.status_code == 200
    principals = {item["principal"] for item in response.json()["items"]}
    assert "user:root" in principals


def test_system_bindings_are_denied_to_an_organization_admin(client: TestClient) -> None:
    organization_id, _project_id, _dataset_id = _hierarchy(client)
    client.post(
        f"/api/v1/organizations/{organization_id}/bindings",
        json={"principal": "user:alice", "role": "organization_admin"},
        headers=_headers("root"),
    )
    response = client.get("/api/v1/bindings", headers=_headers("alice"))
    assert response.status_code == 403


def test_system_bindings_are_denied_to_an_unbound_authenticated_caller(client: TestClient) -> None:
    response = client.get("/api/v1/bindings", headers=_headers("mallory"))
    assert response.status_code == 403


def test_organization_bindings_can_be_listed_by_someone_who_manages_them(
    client: TestClient,
) -> None:
    organization_id, _project_id, _dataset_id = _hierarchy(client)
    client.post(
        f"/api/v1/organizations/{organization_id}/bindings",
        json={"principal": "user:alice", "role": "organization_admin"},
        headers=_headers("root"),
    )
    response = client.get(
        f"/api/v1/organizations/{organization_id}/bindings", headers=_headers("root")
    )
    assert response.status_code == 200
    principals = {item["principal"] for item in response.json()["items"]}
    assert "user:alice" in principals


def test_organization_bindings_are_ordered_by_principal_then_role(client: TestClient) -> None:
    organization_id, _project_id, _dataset_id = _hierarchy(client)
    for principal, role in [
        ("user:carol", "organization_admin"),
        ("user:alice", "organization_admin"),
        ("user:alice", "developer"),
    ]:
        client.post(
            f"/api/v1/organizations/{organization_id}/bindings",
            json={"principal": principal, "role": role},
            headers=_headers("root"),
        )
    response = client.get(
        f"/api/v1/organizations/{organization_id}/bindings", headers=_headers("root")
    )
    assert response.status_code == 200
    keys = [(item["principal"], item["role_code"]) for item in response.json()["items"]]
    assert keys == sorted(keys)


class _ReversedOrderRbacStore(InMemoryRbacStore):
    """A store that hands bindings back in the opposite of its own order.

    Stands in for any future ``RbacStore`` whose ``ORDER BY`` disagrees with
    ``(principal, role_code)`` - the binding list handlers must re-sort what
    they're given rather than trust the store's ordering.
    """

    async def bindings_at(
        self, scope_type: ScopeType, scope_id: UUID | None
    ) -> list[RoleBindingRecord]:
        return list(reversed(await super().bindings_at(scope_type, scope_id)))


#: The bindings posted before the sort-order assertion, per scope: two
#: principals distinguishing on role where the role model allows it
#: (``platform_owner`` is the only role bindable at SYSTEM, so that case
#: distinguishes on principal alone).
_UNSORTED_BINDINGS = {
    "system": [
        ("user:carol", "platform_owner"),
        ("user:alice", "platform_owner"),
        ("user:bob", "platform_owner"),
    ],
    "organization": [
        ("user:carol", "developer"),
        ("user:alice", "developer"),
        ("user:alice", "reader"),
    ],
    "project": [
        ("user:carol", "developer"),
        ("user:alice", "developer"),
        ("user:alice", "reader"),
    ],
    "dataset": [
        ("user:carol", "developer"),
        ("user:alice", "developer"),
        ("user:alice", "reader"),
    ],
}


@pytest.mark.parametrize("scope", ["system", "organization", "project", "dataset"])
def test_the_boundary_orders_bindings_whatever_order_the_store_returns(
    tmp_path: Path, scope: str
) -> None:
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
        rbac_store=_ReversedOrderRbacStore(),
    )
    with TestClient(create_app(settings=settings, repository=repository)) as client:
        organization_id, project_id, dataset_id = _hierarchy(client)
        bindings_path = _bindings_path(scope, organization_id, project_id, dataset_id)
        for principal, role in _UNSORTED_BINDINGS[scope]:
            response = client.post(
                bindings_path, json={"principal": principal, "role": role}, headers=_headers("root")
            )
            assert response.status_code == 201

        response = client.get(bindings_path, headers=_headers("root"))
        assert response.status_code == 200
        keys = [(item["principal"], item["role_code"]) for item in response.json()["items"]]
        assert keys == sorted(keys)


def test_organization_bindings_rejects_an_out_of_range_limit(client: TestClient) -> None:
    organization_id, _project_id, _dataset_id = _hierarchy(client)
    response = client.get(
        f"/api/v1/organizations/{organization_id}/bindings",
        params={"limit": 5000},
        headers=_headers("root"),
    )
    assert response.status_code == 422


def test_project_bindings_rejects_an_out_of_range_limit(client: TestClient) -> None:
    organization_id, project_id, _dataset_id = _hierarchy(client)
    client.post(
        f"/api/v1/organizations/{organization_id}/bindings",
        json={"principal": "user:alice", "role": "organization_admin"},
        headers=_headers("root"),
    )
    response = client.get(
        f"/api/v1/projects/{project_id}/bindings",
        params={"limit": 5000},
        headers=_headers("alice"),
    )
    assert response.status_code == 422


@pytest.mark.parametrize("scope", ["system", "organization", "project", "dataset"])
def test_binding_scope_id_is_null_only_for_the_system_scope(client: TestClient, scope: str) -> None:
    organization_id, project_id, dataset_id = _hierarchy(client)
    _path, binding = _create_binding(client, scope, organization_id, project_id, dataset_id)

    assert binding["scope_type"] == scope.upper()
    if scope == "system":
        assert binding["scope_id"] is None
    else:
        assert binding["scope_id"] is not None


def test_project_bindings_can_be_listed_by_someone_who_manages_them(client: TestClient) -> None:
    organization_id, project_id, _dataset_id = _hierarchy(client)
    client.post(
        f"/api/v1/organizations/{organization_id}/bindings",
        json={"principal": "user:alice", "role": "organization_admin"},
        headers=_headers("root"),
    )
    client.post(
        f"/api/v1/projects/{project_id}/bindings",
        json={"principal": "user:bob", "role": "developer"},
        headers=_headers("alice"),
    )
    response = client.get(f"/api/v1/projects/{project_id}/bindings", headers=_headers("alice"))
    assert response.status_code == 200
    principals = {item["principal"] for item in response.json()["items"]}
    assert "user:bob" in principals


def test_dataset_bindings_are_readable_by_a_project_admin_bound_at_the_parent_project(
    client: TestClient,
) -> None:
    _organization_id, project_id, dataset_id = _hierarchy(client)
    client.post(
        f"/api/v1/projects/{project_id}/bindings",
        json={"principal": "user:alice", "role": "project_admin"},
        headers=_headers("root"),
    )
    response = client.get(f"/api/v1/datasets/{dataset_id}/bindings", headers=_headers("alice"))
    assert response.status_code == 200


def test_dataset_bindings_are_readable_by_an_organization_admin_at_the_grandparent(
    client: TestClient,
) -> None:
    organization_id, _project_id, dataset_id = _hierarchy(client)
    client.post(
        f"/api/v1/organizations/{organization_id}/bindings",
        json={"principal": "user:alice", "role": "organization_admin"},
        headers=_headers("root"),
    )
    response = client.get(f"/api/v1/datasets/{dataset_id}/bindings", headers=_headers("alice"))
    assert response.status_code == 200


def test_dataset_bindings_are_denied_to_a_reader_bound_at_that_dataset(client: TestClient) -> None:
    _organization_id, _project_id, dataset_id = _hierarchy(client)
    client.post(
        f"/api/v1/datasets/{dataset_id}/bindings",
        json={"principal": "user:alice", "role": "reader"},
        headers=_headers("root"),
    )
    response = client.get(f"/api/v1/datasets/{dataset_id}/bindings", headers=_headers("alice"))
    assert response.status_code == 403


def test_dataset_bindings_404_for_an_unknown_dataset(client: TestClient) -> None:
    response = client.get(f"/api/v1/datasets/{uuid4()}/bindings", headers=_headers("root"))
    assert response.status_code == 404


@pytest.mark.parametrize("path", ["/api/v1/bindings", "/api/v1/datasets/{dataset_id}/bindings"])
def test_a_cursor_walk_visits_every_binding_at_the_root_exactly_once(
    client: TestClient, path: str
) -> None:
    _organization_id, _project_id, dataset_id = _hierarchy(client)
    bindings_path = path.format(dataset_id=dataset_id)
    scope = "system" if path == "/api/v1/bindings" else "dataset"
    role = _ROOT_ROLE[scope]
    for principal in ["user:carol", "user:alice", "user:mallory"]:
        response = client.post(
            bindings_path, json={"principal": principal, "role": role}, headers=_headers("root")
        )
        assert response.status_code == 201

    total = len(client.get(bindings_path, headers=_headers("root")).json()["items"])

    seen: list[str] = []
    cursor: str | None = None
    for _ in range(total + 1):
        params = {"limit": 1} | ({"after": cursor} if cursor is not None else {})
        response = client.get(bindings_path, params=params, headers=_headers("root"))
        assert response.status_code == 200
        body = response.json()
        assert len(body["items"]) == 1
        seen.append(body["items"][0]["id"])
        cursor = body["next_cursor"]
        if cursor is None:
            break
    else:
        pytest.fail("cursor walk did not terminate within the expected number of pages")

    assert len(seen) == total
    assert len(seen) == len(set(seen))


@pytest.mark.parametrize("path", ["/api/v1/bindings", "/api/v1/datasets/{dataset_id}/bindings"])
async def test_a_lapsed_grant_still_appears_in_the_listing(
    client: TestClient, repository: HierarchyRepository, path: str
) -> None:
    """The binding collections are a roster of grants, not of grants still in force.

    ``bindings_at`` carries no expiry predicate, so a binding whose
    ``expires_at`` has already passed is exactly as much a member of the
    collection as one that never expires.
    """
    _organization_id, _project_id, dataset_id = _hierarchy(client)
    bindings_path = path.format(dataset_id=dataset_id)
    scope_type = ScopeType.SYSTEM if path == "/api/v1/bindings" else ScopeType.DATASET
    scope_id = None if scope_type is ScopeType.SYSTEM else UUID(dataset_id)
    role = _ROOT_ROLE["system" if scope_type is ScopeType.SYSTEM else "dataset"]

    lapsed = await repository.grant_role(
        principal="user:lapsed",
        role_code=role,
        scope_type=scope_type,
        scope_id=scope_id,
        created_by="root",
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )

    response = client.get(bindings_path, headers=_headers("root"))
    assert response.status_code == 200
    ids = {item["id"] for item in response.json()["items"]}
    assert str(lapsed.id) in ids


@pytest.mark.parametrize("scope", ["system", "organization", "project", "dataset"])
def test_revoking_a_binding_at_its_own_root_succeeds_with_an_empty_body(
    client: TestClient, scope: str
) -> None:
    organization_id, project_id, dataset_id = _hierarchy(client)
    path, binding = _create_binding(client, scope, organization_id, project_id, dataset_id)

    response = client.delete(f"{path}/{binding['id']}", headers=_headers("root"))
    assert response.status_code == 204
    assert response.content == b""


@pytest.mark.parametrize("scope", ["system", "organization", "project", "dataset"])
def test_revoking_a_binding_removes_it_from_that_roots_listing(
    client: TestClient, scope: str
) -> None:
    organization_id, project_id, dataset_id = _hierarchy(client)
    path, binding = _create_binding(client, scope, organization_id, project_id, dataset_id)

    client.delete(f"{path}/{binding['id']}", headers=_headers("root"))

    remaining = client.get(path, headers=_headers("root")).json()["items"]
    assert binding["id"] not in {item["id"] for item in remaining}


@pytest.mark.parametrize(
    "scope,role,grantee",
    [
        ("system", "platform_owner", "alice"),
        ("organization", "organization_admin", "alice"),
        ("project", "project_admin", "bob"),
    ],
)
def test_revoking_a_binding_immediately_removes_the_capability_it_granted(
    client: TestClient, scope: str, role: str, grantee: str
) -> None:
    organization_id, project_id, dataset_id = _hierarchy(client)
    path = _bindings_path(scope, organization_id, project_id, dataset_id)
    grant = client.post(
        path, json={"principal": f"user:{grantee}", "role": role}, headers=_headers("root")
    ).json()

    reachable = client.post(
        path, json={"principal": "user:probe", "role": role}, headers=_headers(grantee)
    )
    assert reachable.status_code == 201

    revoked = client.delete(f"{path}/{grant['id']}", headers=_headers("root"))
    assert revoked.status_code == 204

    blocked = client.post(
        path, json={"principal": "user:probe-2", "role": role}, headers=_headers(grantee)
    )
    assert blocked.status_code == 403


def test_an_organization_binding_named_under_the_system_root_404s(client: TestClient) -> None:
    organization_id, project_id, dataset_id = _hierarchy(client)
    _path, binding = _create_binding(
        client, "organization", organization_id, project_id, dataset_id
    )

    response = client.delete(f"/api/v1/bindings/{binding['id']}", headers=_headers("root"))
    assert response.status_code == 404


def test_a_dataset_binding_named_under_the_organization_root_404s(client: TestClient) -> None:
    organization_id, project_id, dataset_id = _hierarchy(client)
    _path, binding = _create_binding(client, "dataset", organization_id, project_id, dataset_id)

    response = client.delete(
        f"/api/v1/organizations/{organization_id}/bindings/{binding['id']}",
        headers=_headers("root"),
    )
    assert response.status_code == 404


@pytest.mark.parametrize("scope", ["organization", "project"])
def test_a_binding_named_under_a_sibling_scope_of_the_same_kind_404s(
    client: TestClient, scope: str
) -> None:
    organization_id, project_id, dataset_id = _hierarchy(client)
    path, binding = _create_binding(client, scope, organization_id, project_id, dataset_id)

    if scope == "organization":
        sibling_path = f"/api/v1/organizations/{_sibling_organization(client)}/bindings"
    else:
        sibling_path = f"/api/v1/projects/{_sibling_project(client, organization_id)}/bindings"

    response = client.delete(f"{sibling_path}/{binding['id']}", headers=_headers("root"))
    assert response.status_code == 404

    remaining = client.get(path, headers=_headers("root")).json()["items"]
    assert binding["id"] in {item["id"] for item in remaining}


@pytest.mark.parametrize("scope", ["system", "organization", "project", "dataset"])
def test_revoking_an_unknown_binding_404s(client: TestClient, scope: str) -> None:
    organization_id, project_id, dataset_id = _hierarchy(client)
    path = _bindings_path(scope, organization_id, project_id, dataset_id)

    response = client.delete(f"{path}/{uuid4()}", headers=_headers("root"))
    assert response.status_code == 404


@pytest.mark.parametrize("scope", ["system", "organization", "project", "dataset"])
def test_revoking_the_same_binding_twice_404s_the_second_time(
    client: TestClient, scope: str
) -> None:
    organization_id, project_id, dataset_id = _hierarchy(client)
    path, binding = _create_binding(client, scope, organization_id, project_id, dataset_id)
    binding_path = f"{path}/{binding['id']}"

    client.delete(binding_path, headers=_headers("root"))
    response = client.delete(binding_path, headers=_headers("root"))
    assert response.status_code == 404


@pytest.mark.parametrize("scope", ["system", "organization", "project", "dataset"])
def test_revoking_a_binding_is_denied_without_the_capability_at_its_scope(
    client: TestClient, scope: str
) -> None:
    organization_id, project_id, dataset_id = _hierarchy(client)
    path, binding = _create_binding(client, scope, organization_id, project_id, dataset_id)

    response = client.delete(f"{path}/{binding['id']}", headers=_headers("mallory"))
    assert response.status_code == 403


@pytest.mark.parametrize(
    "path_template",
    [
        "/api/v1/organizations/{}/bindings/{}",
        "/api/v1/projects/{}/bindings/{}",
        "/api/v1/datasets/{}/bindings/{}",
    ],
)
def test_revoking_at_a_nonexistent_scope_404s_before_checking_the_capability(
    client: TestClient, path_template: str
) -> None:
    path = path_template.format(uuid4(), uuid4())
    response = client.delete(path, headers=_headers("mallory"))
    assert response.status_code == 404
