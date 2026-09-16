"""The read surface over organizations, projects and datasets, plus two dataset write routes.

Drives the FastAPI app through a TestClient over an in-memory
``HierarchyStore`` with dev-header auth and ``root`` bootstrapped as
platform owner. Covers list and get-by-id for all three hierarchy levels,
plus the two dataset write routes exercised nowhere else: patching a
dataset, and creating a release once a revision has been committed
directly through the hierarchy store's writer (``POST .../releases``
cannot drive ingest itself - there is no HTTP route that commits a
revision yet). Also covers, at the HTTP boundary, that reusing an
``Idempotency-Key`` for a changed request is refused on every creation
route, and that a patch naming no field is a no-op that writes nothing new.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from huron.applications.api.app import create_app
from huron.applications.api.settings import ApiSettings, ClassificationValue
from huron.core.catalog.paths import dataset_dir
from tests.hierarchy_contract import committed_revision
from tests.unit.support import memory_stores

if TYPE_CHECKING:
    from collections.abc import Iterator

    from huron.applications.api.runtime import ApiStores

pytestmark = pytest.mark.unit

_ORGANIZATION_KEYS = {"id", "slug", "title", "description", "version", "created_at"}
_PROJECT_KEYS = {
    "id",
    "organization_id",
    "slug",
    "title",
    "description",
    "data_classification",
    "version",
    "created_at",
}
_DATASET_KEYS = {
    "id",
    "project_id",
    "slug",
    "title",
    "description",
    "profile_name",
    "profile_version",
    "entry_layer",
    "lifecycle_state",
    "version",
    "created_at",
}


def _headers(subject: str = "root") -> dict[str, str]:
    """Dev-header credentials for ``subject``, paired with a fresh idempotency key."""
    return {"X-Huron-Subject": subject, "Idempotency-Key": str(uuid4())}


@pytest.fixture
def stores() -> ApiStores:
    """A fresh in-memory store bundle, held so a test can seed its hierarchy store directly."""
    return memory_stores()


@pytest.fixture
def client(tmp_path: Path, stores: ApiStores) -> Iterator[TestClient]:
    """A dev-header TestClient over a freshly wired in-memory repository, ``root`` bootstrapped."""
    settings = ApiSettings(
        env="development",
        auth_mode="dev-headers",
        data_root=str(tmp_path / "data"),
        database_url="postgresql://unused",
        classification_vocabulary=[ClassificationValue(code="open", order=0, discoverable=True)],
        bootstrap_platform_owner="root",
    )
    with TestClient(create_app(settings=settings, stores=stores)) as client:
        yield client


def _organization(client: TestClient, slug: str = "astro") -> str:
    """Creates an organization with ``slug`` and returns its id."""
    response = client.post(
        "/api/v1/organizations", json={"slug": slug, "title": slug.title()}, headers=_headers()
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _project(client: TestClient, organization_id: str, slug: str = "sims") -> str:
    """Creates a project with ``slug`` under ``organization_id`` and returns its id."""
    response = client.post(
        f"/api/v1/organizations/{organization_id}/projects",
        json={"slug": slug, "title": slug.title(), "data_classification": "open"},
        headers=_headers(),
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _dataset(client: TestClient, project_id: str, slug: str = "run-0001") -> str:
    """Creates a dataset with ``slug`` under ``project_id`` and returns its id."""
    response = client.post(
        f"/api/v1/projects/{project_id}/datasets",
        json={
            "slug": slug,
            "title": slug.title(),
            "profile_name": "mcnp-run",
            "profile_version": "1.0",
        },
        headers=_headers(),
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def _commit_revision(
    stores: ApiStores, dataset_id: str, *, manifest_sha256: str, number: int = 1
) -> None:
    """Commit a revision directly through the injected hierarchy store's writer."""
    async with stores.hierarchy.transaction() as writer:
        await writer.insert_revision(
            committed_revision(UUID(dataset_id), number, manifest_sha256=manifest_sha256)
        )


@dataclasses.dataclass(frozen=True)
class _Ref:
    """The id and slug a path constructor from ``huron.core.catalog.paths`` needs."""

    id: UUID
    slug: str


def _generation_files(entity_dir: PurePosixPath) -> list[Path]:
    """List the generation documents written under a hierarchy entity's directory."""
    return sorted((Path(str(entity_dir)) / "generations").glob("*.json"))


# -- organizations ------------------------------------------------------


def test_list_organizations_orders_by_slug_within_the_paginated_envelope(
    client: TestClient,
) -> None:
    """Listed organizations are ordered by slug, and each item has exactly the documented fields."""
    zeta_id = _organization(client, "zeta")
    astro_id = _organization(client, "astro")

    response = client.get("/api/v1/organizations", headers=_headers())
    assert response.status_code == 200
    body = response.json()
    assert body.keys() == {"items", "next_cursor"}
    assert body["next_cursor"] is None

    ids = [item["id"] for item in body["items"]]
    assert ids.index(astro_id) < ids.index(zeta_id)
    (item,) = [entry for entry in body["items"] if entry["id"] == astro_id]
    assert item.keys() == _ORGANIZATION_KEYS


def test_list_organizations_returns_the_empty_list_when_none_exist(client: TestClient) -> None:
    """An empty organizations collection returns an empty ``items`` list and a null cursor."""
    response = client.get("/api/v1/organizations", headers=_headers())
    assert response.status_code == 200
    assert response.json() == {"items": [], "next_cursor": None}


def test_list_organizations_cursor_walk_visits_every_item_exactly_once(
    client: TestClient,
) -> None:
    """A cursor walk with ``limit=1`` visits every organization exactly once, in slug order."""
    slugs = ["zeta", "astro", "mid", "beta"]
    ids_by_slug = {slug: _organization(client, slug) for slug in slugs}

    seen: list[str] = []
    cursor: str | None = None
    for _ in range(len(slugs) + 1):
        params = {"limit": 1} | ({"after": cursor} if cursor is not None else {})
        response = client.get("/api/v1/organizations", params=params, headers=_headers())
        assert response.status_code == 200
        body = response.json()
        assert len(body["items"]) == 1
        seen.append(body["items"][0]["id"])
        cursor = body["next_cursor"]
        if cursor is None:
            break
    else:
        pytest.fail("cursor walk did not terminate within the expected number of pages")

    assert seen == [ids_by_slug[slug] for slug in sorted(slugs)]
    assert len(seen) == len(set(seen))


@pytest.mark.parametrize("limit", [0, 201, -3])
def test_list_organizations_rejects_an_out_of_range_limit(client: TestClient, limit: int) -> None:
    """Listing organizations with an out-of-range limit is rejected with 422."""
    response = client.get("/api/v1/organizations", params={"limit": limit}, headers=_headers())
    assert response.status_code == 422


def test_list_organizations_rejects_a_malformed_cursor(client: TestClient) -> None:
    """Listing organizations with a malformed cursor is rejected with 422."""
    response = client.get(
        "/api/v1/organizations", params={"after": "not-a-cursor"}, headers=_headers()
    )
    assert response.status_code == 422


def test_page_organization_view_is_a_distinct_openapi_component(client: TestClient) -> None:
    """The organizations list route publishes ``Page_OrganizationView_`` as its own schema."""
    schema = client.app.openapi()
    assert "Page_OrganizationView_" in schema["components"]["schemas"]
    operation = schema["paths"]["/api/v1/organizations"]["get"]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "Page_OrganizationView_"
    )


def test_get_organization_returns_the_created_organization(client: TestClient) -> None:
    """Getting an organization by id returns the organization that was created."""
    organization_id = _organization(client)
    response = client.get(f"/api/v1/organizations/{organization_id}", headers=_headers())
    assert response.status_code == 200
    assert response.json()["id"] == organization_id


def test_get_organization_404s_for_an_unknown_id(client: TestClient) -> None:
    """Getting an organization by an unknown id 404s."""
    response = client.get(f"/api/v1/organizations/{uuid4()}", headers=_headers())
    assert response.status_code == 404


def test_creating_an_organization_with_a_taken_slug_answers_a_named_code(
    client: TestClient,
) -> None:
    """Creating an organization with a taken slug 409s with the ``SLUG_EXISTS`` code."""
    _organization(client, "astro")
    response = client.post(
        "/api/v1/organizations", json={"slug": "astro", "title": "Astro Again"}, headers=_headers()
    )
    assert response.status_code == 409
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "SLUG_EXISTS"


# -- projects -------------------------------------------------------------


def test_list_projects_orders_by_slug_and_excludes_other_organizations(
    client: TestClient,
) -> None:
    """Listed projects are ordered by slug and exclude projects from other organizations."""
    organization_id = _organization(client)
    other_organization_id = _organization(client, "biolab")
    zeta_id = _project(client, organization_id, "zeta")
    astro_id = _project(client, organization_id, "astro")
    _project(client, other_organization_id, "other")

    response = client.get(f"/api/v1/organizations/{organization_id}/projects", headers=_headers())
    assert response.status_code == 200
    body = response.json()
    assert body.keys() == {"items", "next_cursor"}

    ids = [item["id"] for item in body["items"]]
    assert ids == [astro_id, zeta_id]
    (item,) = [entry for entry in body["items"] if entry["id"] == astro_id]
    assert item.keys() == _PROJECT_KEYS


def test_list_projects_cursor_walk_visits_every_item_exactly_once(client: TestClient) -> None:
    """A cursor walk with ``limit=1`` visits every project exactly once, in slug order."""
    organization_id = _organization(client)
    slugs = ["zeta", "astro", "mid", "beta"]
    ids_by_slug = {slug: _project(client, organization_id, slug) for slug in slugs}

    seen: list[str] = []
    cursor: str | None = None
    for _ in range(len(slugs) + 1):
        params = {"limit": 1} | ({"after": cursor} if cursor is not None else {})
        response = client.get(
            f"/api/v1/organizations/{organization_id}/projects", params=params, headers=_headers()
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body["items"]) == 1
        seen.append(body["items"][0]["id"])
        cursor = body["next_cursor"]
        if cursor is None:
            break
    else:
        pytest.fail("cursor walk did not terminate within the expected number of pages")

    assert seen == [ids_by_slug[slug] for slug in sorted(slugs)]
    assert len(seen) == len(set(seen))


def test_list_projects_returns_the_empty_list_when_the_organization_has_no_projects(
    client: TestClient,
) -> None:
    """An organization with no projects returns an empty ``items`` list."""
    organization_id = _organization(client)
    response = client.get(f"/api/v1/organizations/{organization_id}/projects", headers=_headers())
    assert response.status_code == 200
    assert response.json() == {"items": [], "next_cursor": None}


def test_list_projects_404s_for_an_unknown_organization(client: TestClient) -> None:
    """Listing projects under an unknown organization id 404s."""
    response = client.get(f"/api/v1/organizations/{uuid4()}/projects", headers=_headers())
    assert response.status_code == 404


@pytest.mark.parametrize("limit", [0, 201, -3])
def test_list_projects_rejects_an_out_of_range_limit(client: TestClient, limit: int) -> None:
    """Listing projects with an out-of-range limit is rejected with 422."""
    organization_id = _organization(client)
    response = client.get(
        f"/api/v1/organizations/{organization_id}/projects",
        params={"limit": limit},
        headers=_headers(),
    )
    assert response.status_code == 422


def test_list_projects_rejects_a_malformed_cursor(client: TestClient) -> None:
    """Listing projects with a malformed cursor is rejected with 422."""
    organization_id = _organization(client)
    response = client.get(
        f"/api/v1/organizations/{organization_id}/projects",
        params={"after": "not-a-cursor"},
        headers=_headers(),
    )
    assert response.status_code == 422


def test_get_project_returns_the_created_project(client: TestClient) -> None:
    """Getting a project by id returns the project that was created."""
    organization_id = _organization(client)
    project_id = _project(client, organization_id)
    response = client.get(f"/api/v1/projects/{project_id}", headers=_headers())
    assert response.status_code == 200
    assert response.json()["id"] == project_id


def test_get_project_404s_for_an_unknown_id(client: TestClient) -> None:
    """Getting a project by an unknown id 404s."""
    response = client.get(f"/api/v1/projects/{uuid4()}", headers=_headers())
    assert response.status_code == 404


def test_create_project_rejects_a_classification_outside_the_configured_vocabulary(
    client: TestClient,
) -> None:
    """Creating a project with an unconfigured classification 400s as ``CLASSIFICATION_UNKNOWN``."""
    organization_id = _organization(client)
    response = client.post(
        f"/api/v1/organizations/{organization_id}/projects",
        json={"slug": "sims", "title": "Sims", "data_classification": "top-secret"},
        headers=_headers(),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "CLASSIFICATION_UNKNOWN"


def test_create_project_replay_with_a_changed_classification_is_refused(tmp_path: Path) -> None:
    """Reusing an ``Idempotency-Key`` with a different ``data_classification`` 409s."""
    settings = ApiSettings(
        env="development",
        auth_mode="dev-headers",
        data_root=str(tmp_path / "data"),
        database_url="postgresql://unused",
        classification_vocabulary=[
            ClassificationValue(code="open", order=0, discoverable=True),
            ClassificationValue(code="restricted", order=1, discoverable=False),
        ],
        bootstrap_platform_owner="root",
    )
    with TestClient(create_app(settings=settings, stores=memory_stores())) as client:
        organization_id = _organization(client)
        headers = _headers()
        payload = {"slug": "sims", "title": "Sims", "data_classification": "open"}

        first = client.post(
            f"/api/v1/organizations/{organization_id}/projects", json=payload, headers=headers
        )
        assert first.status_code == 201

        second = client.post(
            f"/api/v1/organizations/{organization_id}/projects",
            json={**payload, "data_classification": "restricted"},
            headers=headers,
        )
        assert second.status_code == 409
        assert second.json()["code"] == "IDEMPOTENCY_KEY_REUSED"


# -- datasets ---------------------------------------------------------------


def test_list_datasets_orders_by_slug_and_excludes_other_projects(client: TestClient) -> None:
    """Listed datasets are ordered by slug and exclude datasets from other projects."""
    organization_id = _organization(client)
    project_id = _project(client, organization_id)
    other_project_id = _project(client, organization_id, "other-project")
    zeta_id = _dataset(client, project_id, "zeta")
    astro_id = _dataset(client, project_id, "astro")
    _dataset(client, other_project_id, "other-dataset")

    response = client.get(f"/api/v1/projects/{project_id}/datasets", headers=_headers())
    assert response.status_code == 200
    body = response.json()
    assert body.keys() == {"items", "next_cursor"}

    ids = [item["id"] for item in body["items"]]
    assert ids == [astro_id, zeta_id]
    (item,) = [entry for entry in body["items"] if entry["id"] == astro_id]
    assert item.keys() == _DATASET_KEYS


def test_list_datasets_cursor_walk_visits_every_item_exactly_once(client: TestClient) -> None:
    """A cursor walk with ``limit=1`` visits every dataset exactly once, in slug order."""
    organization_id = _organization(client)
    project_id = _project(client, organization_id)
    slugs = ["zeta", "astro", "mid", "beta"]
    ids_by_slug = {slug: _dataset(client, project_id, slug) for slug in slugs}

    seen: list[str] = []
    cursor: str | None = None
    for _ in range(len(slugs) + 1):
        params = {"limit": 1} | ({"after": cursor} if cursor is not None else {})
        response = client.get(
            f"/api/v1/projects/{project_id}/datasets", params=params, headers=_headers()
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body["items"]) == 1
        seen.append(body["items"][0]["id"])
        cursor = body["next_cursor"]
        if cursor is None:
            break
    else:
        pytest.fail("cursor walk did not terminate within the expected number of pages")

    assert seen == [ids_by_slug[slug] for slug in sorted(slugs)]
    assert len(seen) == len(set(seen))


def test_list_datasets_returns_the_empty_list_when_the_project_has_no_datasets(
    client: TestClient,
) -> None:
    """A project with no datasets returns an empty ``items`` list."""
    organization_id = _organization(client)
    project_id = _project(client, organization_id)
    response = client.get(f"/api/v1/projects/{project_id}/datasets", headers=_headers())
    assert response.status_code == 200
    assert response.json() == {"items": [], "next_cursor": None}


def test_list_datasets_404s_for_an_unknown_project(client: TestClient) -> None:
    """Listing datasets under an unknown project id 404s."""
    response = client.get(f"/api/v1/projects/{uuid4()}/datasets", headers=_headers())
    assert response.status_code == 404


@pytest.mark.parametrize("limit", [0, 201, -3])
def test_list_datasets_rejects_an_out_of_range_limit(client: TestClient, limit: int) -> None:
    """Listing datasets with an out-of-range limit is rejected with 422."""
    organization_id = _organization(client)
    project_id = _project(client, organization_id)
    response = client.get(
        f"/api/v1/projects/{project_id}/datasets", params={"limit": limit}, headers=_headers()
    )
    assert response.status_code == 422


def test_list_datasets_rejects_a_malformed_cursor(client: TestClient) -> None:
    """Listing datasets with a malformed cursor is rejected with 422."""
    organization_id = _organization(client)
    project_id = _project(client, organization_id)
    response = client.get(
        f"/api/v1/projects/{project_id}/datasets",
        params={"after": "not-a-cursor"},
        headers=_headers(),
    )
    assert response.status_code == 422


def test_create_dataset_replay_with_a_changed_description_is_refused(client: TestClient) -> None:
    """Reusing an ``Idempotency-Key`` for ``create_dataset`` with a different description 409s."""
    organization_id = _organization(client)
    project_id = _project(client, organization_id)
    headers = _headers()
    payload = {
        "slug": "run-0001",
        "title": "Run 1",
        "description": "first pass",
        "profile_name": "mcnp-run",
        "profile_version": "1.0",
    }

    first = client.post(f"/api/v1/projects/{project_id}/datasets", json=payload, headers=headers)
    assert first.status_code == 201

    second = client.post(
        f"/api/v1/projects/{project_id}/datasets",
        json={**payload, "description": "second pass"},
        headers=headers,
    )
    assert second.status_code == 409
    assert second.json()["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_get_dataset_returns_the_created_dataset(client: TestClient) -> None:
    """Getting a dataset by id returns the dataset that was created."""
    organization_id = _organization(client)
    project_id = _project(client, organization_id)
    dataset_id = _dataset(client, project_id)
    response = client.get(f"/api/v1/datasets/{dataset_id}", headers=_headers())
    assert response.status_code == 200
    assert response.json()["id"] == dataset_id


def test_get_dataset_404s_for_an_unknown_id(client: TestClient) -> None:
    """Getting a dataset by an unknown id 404s."""
    response = client.get(f"/api/v1/datasets/{uuid4()}", headers=_headers())
    assert response.status_code == 404


def test_patch_dataset_updates_title_and_description(client: TestClient) -> None:
    """Patching a dataset updates its title and description and bumps its version."""
    organization_id = _organization(client)
    project_id = _project(client, organization_id)
    dataset_id = _dataset(client, project_id)

    response = client.patch(
        f"/api/v1/datasets/{dataset_id}",
        json={"title": "Renamed Run", "description": "updated"},
        headers={**_headers(), "If-Match": "1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Renamed Run"
    assert body["description"] == "updated"
    assert body["version"] == 2


def test_patch_dataset_with_an_empty_body_is_a_no_op(client: TestClient, tmp_path: Path) -> None:
    """A PATCH naming no field returns 200 with the same version and writes no new generation."""
    organization_id = _organization(client, "astro")
    project_id = _project(client, organization_id, "sims")
    dataset_id = _dataset(client, project_id, "run-0001")
    entity_dir = dataset_dir(
        PurePosixPath(str(tmp_path / "data")),
        _Ref(id=UUID(organization_id), slug="astro"),
        _Ref(id=UUID(project_id), slug="sims"),
        _Ref(id=UUID(dataset_id), slug="run-0001"),
    )
    before = _generation_files(entity_dir)

    response = client.patch(
        f"/api/v1/datasets/{dataset_id}", json={}, headers={**_headers(), "If-Match": "1"}
    )
    assert response.status_code == 200
    assert response.json()["version"] == 1
    assert _generation_files(entity_dir) == before


def test_patch_dataset_rejects_a_malformed_if_match_header(client: TestClient) -> None:
    """Patching a dataset with an unparseable ``If-Match`` header 422s as ``REQUEST_INVALID``."""
    organization_id = _organization(client)
    project_id = _project(client, organization_id)
    dataset_id = _dataset(client, project_id)

    response = client.patch(
        f"/api/v1/datasets/{dataset_id}",
        json={"title": "Renamed Run"},
        headers={**_headers(), "If-Match": "not-an-integer"},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "REQUEST_INVALID"


# -- releases -----------------------------------------------------------


async def test_create_release_succeeds_once_a_revision_is_committed_directly(
    client: TestClient, stores: ApiStores
) -> None:
    """Creating a release succeeds once its revision is committed directly on the hierarchy store.

    ``insert_revision`` is called on the hierarchy store's writer directly -
    there is no HTTP route that commits a revision yet - the same seam a
    future ingest pipeline will drive through the store the lifespan wires.
    """
    organization_id = _organization(client)
    project_id = _project(client, organization_id)
    dataset_id = _dataset(client, project_id)
    await _commit_revision(stores, dataset_id, manifest_sha256="a" * 64)

    response = client.post(
        f"/api/v1/datasets/{dataset_id}/releases",
        json={"tag": "v1", "revision_number": 1},
        headers=_headers(),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["tag"] == "v1"
    assert body["revision_number"] == 1


def test_create_release_404s_without_a_registered_revision(client: TestClient) -> None:
    """Creating a release without a registered revision 404s."""
    organization_id = _organization(client)
    project_id = _project(client, organization_id)
    dataset_id = _dataset(client, project_id)

    response = client.post(
        f"/api/v1/datasets/{dataset_id}/releases",
        json={"tag": "v1", "revision_number": 1},
        headers=_headers(),
    )
    assert response.status_code == 404


async def test_create_release_replay_returns_the_identical_body_with_no_replay_indicator(
    client: TestClient, stores: ApiStores
) -> None:
    """Replaying a release creation with the same idempotency key returns an identical body."""
    organization_id = _organization(client)
    project_id = _project(client, organization_id)
    dataset_id = _dataset(client, project_id)
    await _commit_revision(stores, dataset_id, manifest_sha256="d" * 64)
    headers = _headers()
    payload = {"tag": "v1", "revision_number": 1}

    first = client.post(f"/api/v1/datasets/{dataset_id}/releases", json=payload, headers=headers)
    second = client.post(f"/api/v1/datasets/{dataset_id}/releases", json=payload, headers=headers)

    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    assert "replayed" not in second.json()


async def test_create_release_replay_with_a_changed_title_is_refused(
    client: TestClient, stores: ApiStores
) -> None:
    """Reusing an ``Idempotency-Key`` for ``create_release`` with a different title 409s."""
    organization_id = _organization(client)
    project_id = _project(client, organization_id)
    dataset_id = _dataset(client, project_id)
    await _commit_revision(stores, dataset_id, manifest_sha256="9" * 64)
    headers = _headers()
    payload = {"tag": "v1", "revision_number": 1, "title": "First"}

    first = client.post(f"/api/v1/datasets/{dataset_id}/releases", json=payload, headers=headers)
    assert first.status_code == 201

    second = client.post(
        f"/api/v1/datasets/{dataset_id}/releases",
        json={**payload, "title": "Second"},
        headers=headers,
    )
    assert second.status_code == 409
    assert second.json()["code"] == "IDEMPOTENCY_KEY_REUSED"


async def test_dataset_and_release_responses_carry_no_etag_header(
    client: TestClient, stores: ApiStores
) -> None:
    """No ``ETag`` header appears on either response, and the dataset's version stays 1."""
    organization_id = _organization(client)
    project_id = _project(client, organization_id)
    dataset_id = _dataset(client, project_id)
    await _commit_revision(stores, dataset_id, manifest_sha256="e" * 64)

    release = client.post(
        f"/api/v1/datasets/{dataset_id}/releases",
        json={"tag": "v1", "revision_number": 1},
        headers=_headers(),
    )
    assert release.status_code == 201
    assert "etag" not in release.headers

    dataset_response = client.get(f"/api/v1/datasets/{dataset_id}", headers=_headers())
    assert "etag" not in dataset_response.headers
    assert dataset_response.json()["version"] == 1


async def test_list_releases_and_resolve_release_return_what_was_created(
    client: TestClient, stores: ApiStores
) -> None:
    """Listing and resolving releases both return the release with its full documented shape."""
    organization_id = _organization(client)
    project_id = _project(client, organization_id)
    dataset_id = _dataset(client, project_id)
    await _commit_revision(stores, dataset_id, manifest_sha256="b" * 64)
    created = client.post(
        f"/api/v1/datasets/{dataset_id}/releases",
        json={"tag": "v1", "revision_number": 1},
        headers=_headers(),
    )
    assert created.status_code == 201

    expected_keys = {
        "id",
        "dataset_id",
        "tag",
        "revision_id",
        "revision_number",
        "title",
        "created_by",
        "created_at",
    }

    listed = client.get(f"/api/v1/datasets/{dataset_id}/releases", headers=_headers())
    assert listed.status_code == 200
    assert listed.json().keys() == {"items", "next_cursor"}
    items = listed.json()["items"]
    assert [item["tag"] for item in items] == ["v1"]
    assert items[0].keys() == expected_keys

    resolved = client.get(f"/api/v1/datasets/{dataset_id}/releases/v1", headers=_headers())
    assert resolved.status_code == 200
    assert resolved.json()["tag"] == "v1"
    assert resolved.json().keys() == expected_keys


async def test_list_releases_orders_by_tag(client: TestClient, stores: ApiStores) -> None:
    """Listed releases are ordered by tag rather than creation order."""
    organization_id = _organization(client)
    project_id = _project(client, organization_id)
    dataset_id = _dataset(client, project_id)
    await _commit_revision(stores, dataset_id, manifest_sha256="c" * 64)
    for tag in ("v2", "v1"):
        response = client.post(
            f"/api/v1/datasets/{dataset_id}/releases",
            json={"tag": tag, "revision_number": 1},
            headers=_headers(),
        )
        assert response.status_code == 201

    listed = client.get(f"/api/v1/datasets/{dataset_id}/releases", headers=_headers())
    assert listed.status_code == 200
    assert [item["tag"] for item in listed.json()["items"]] == ["v1", "v2"]


async def test_list_releases_cursor_walk_visits_every_item_exactly_once(
    client: TestClient, stores: ApiStores
) -> None:
    """A cursor walk with ``limit=1`` visits every release exactly once, in tag order."""
    organization_id = _organization(client)
    project_id = _project(client, organization_id)
    dataset_id = _dataset(client, project_id)
    await _commit_revision(stores, dataset_id, manifest_sha256="f" * 64)
    tags = ["zeta", "astro", "mid", "beta"]
    for tag in tags:
        response = client.post(
            f"/api/v1/datasets/{dataset_id}/releases",
            json={"tag": tag, "revision_number": 1},
            headers=_headers(),
        )
        assert response.status_code == 201

    seen: list[str] = []
    cursor: str | None = None
    for _ in range(len(tags) + 1):
        params = {"limit": 1} | ({"after": cursor} if cursor is not None else {})
        response = client.get(
            f"/api/v1/datasets/{dataset_id}/releases", params=params, headers=_headers()
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body["items"]) == 1
        seen.append(body["items"][0]["tag"])
        cursor = body["next_cursor"]
        if cursor is None:
            break
    else:
        pytest.fail("cursor walk did not terminate within the expected number of pages")

    assert seen == sorted(tags)
    assert len(seen) == len(set(seen))


@pytest.mark.parametrize("limit", [0, 201, -3])
def test_list_releases_rejects_an_out_of_range_limit(client: TestClient, limit: int) -> None:
    """Listing releases with an out-of-range limit is rejected with 422."""
    organization_id = _organization(client)
    project_id = _project(client, organization_id)
    dataset_id = _dataset(client, project_id)
    response = client.get(
        f"/api/v1/datasets/{dataset_id}/releases", params={"limit": limit}, headers=_headers()
    )
    assert response.status_code == 422


def test_list_releases_rejects_a_malformed_cursor(client: TestClient) -> None:
    """Listing releases with a malformed cursor is rejected with 422."""
    organization_id = _organization(client)
    project_id = _project(client, organization_id)
    dataset_id = _dataset(client, project_id)
    response = client.get(
        f"/api/v1/datasets/{dataset_id}/releases",
        params={"after": "not-a-cursor"},
        headers=_headers(),
    )
    assert response.status_code == 422


def test_list_releases_returns_the_empty_list_when_the_dataset_has_no_releases(
    client: TestClient,
) -> None:
    """A dataset with no releases returns an empty ``items`` list."""
    organization_id = _organization(client)
    project_id = _project(client, organization_id)
    dataset_id = _dataset(client, project_id)
    response = client.get(f"/api/v1/datasets/{dataset_id}/releases", headers=_headers())
    assert response.status_code == 200
    assert response.json() == {"items": [], "next_cursor": None}


def test_list_releases_404s_for_an_unknown_dataset(client: TestClient) -> None:
    """Listing releases under an unknown dataset id 404s."""
    response = client.get(f"/api/v1/datasets/{uuid4()}/releases", headers=_headers())
    assert response.status_code == 404


def test_resolve_release_404s_for_an_unknown_tag(client: TestClient) -> None:
    """Resolving a release by an unknown tag 404s."""
    organization_id = _organization(client)
    project_id = _project(client, organization_id)
    dataset_id = _dataset(client, project_id)

    response = client.get(
        f"/api/v1/datasets/{dataset_id}/releases/does-not-exist", headers=_headers()
    )
    assert response.status_code == 404


# -- layers -----------------------------------------------------------------


def test_list_layers_annotates_what_the_caller_may_do_at_each_layer(client: TestClient) -> None:
    """A platform owner's layer listing shows raw as the entry layer with read but not write."""
    organization_id = _organization(client)
    project_id = _project(client, organization_id)
    dataset_id = _dataset(client, project_id)

    response = client.get(f"/api/v1/datasets/{dataset_id}/layers", headers=_headers())
    assert response.status_code == 200
    layers = {item["layer"]: item for item in response.json()}
    assert layers["raw"]["is_entry_layer"] is True
    # platform_owner carries data.read everywhere but deliberately no
    # data.write - administration and data production are separate roles.
    assert layers["raw"]["caller_may"]["read"] is True
    assert layers["raw"]["caller_may"]["write"] is False


def test_list_layers_marks_write_true_only_for_the_layers_a_binding_covers(
    client: TestClient,
) -> None:
    """A developer's binding grants write on raw and bronze only, with read everywhere."""
    organization_id = _organization(client)
    project_id = _project(client, organization_id)
    dataset_id = _dataset(client, project_id)

    binding = client.post(
        f"/api/v1/projects/{project_id}/bindings",
        json={"principal": "user:bob", "role": "developer"},
        headers=_headers(),
    )
    assert binding.status_code == 201

    response = client.get(f"/api/v1/datasets/{dataset_id}/layers", headers=_headers("bob"))
    assert response.status_code == 200
    layers = {item["layer"]: item for item in response.json()}
    # developer carries data.write on raw and bronze only, and data.read
    # everywhere - silver and gold are produced, not principal-written.
    assert layers["raw"]["caller_may"] == {"read": True, "write": True}
    assert layers["bronze"]["caller_may"] == {"read": True, "write": True}
    assert layers["silver"]["caller_may"] == {"read": True, "write": False}
    assert layers["gold"]["caller_may"] == {"read": True, "write": False}
