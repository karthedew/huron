"""Visibility filters listings and gates point reads, patches and creates alike, over HTTP.

Every list, cursor and point read is computed from the caller's
``Visibility`` rather than post-filtered, and a resource outside it answers
404 from every route that names it - a read, a patch, or a create under an
invisible parent - never 403. The fixture below gives one principal,
``alice``, a project-scoped grant that makes exactly one branch of a larger
hierarchy discoverable to her, and proves the rest of it stays invisible
from every angle: listings, cursors and direct ids alike. A second
principal, ``bob``, holds an organization-scope grant instead, one that
reaches every project under it; his test pins the classification gate
itself - a sibling project stays hidden even though the binding that would
otherwise reveal it already covers it, because its classification is not
discoverable.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from huron.applications.api.app import create_app
from huron.applications.api.routes.v1.pagination import decode_cursor
from huron.applications.api.settings import ApiSettings, ClassificationValue
from tests.unit.support import memory_stores

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = pytest.mark.unit


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    """A dev-header TestClient, ``root`` bootstrapped, with an open and a hidden classification."""
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
        yield client


def _headers(subject: str) -> dict[str, str]:
    """Dev-header credentials for ``subject``, paired with a fresh idempotency key."""
    return {"X-Huron-Subject": subject, "Idempotency-Key": str(uuid4())}


def _organization(client: TestClient, slug: str) -> str:
    """Creates an organization with ``slug`` as root and returns its id."""
    response = client.post(
        "/api/v1/organizations",
        json={"slug": slug, "title": slug.title()},
        headers=_headers("root"),
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _project(client: TestClient, organization_id: str, slug: str, *, classification: str) -> str:
    """Creates a project with ``slug`` and ``classification`` under ``organization_id`` as root."""
    response = client.post(
        f"/api/v1/organizations/{organization_id}/projects",
        json={"slug": slug, "title": slug.title(), "data_classification": classification},
        headers=_headers("root"),
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _dataset(client: TestClient, project_id: str, slug: str) -> str:
    """Creates a dataset with ``slug`` under ``project_id`` as root."""
    response = client.post(
        f"/api/v1/projects/{project_id}/datasets",
        json={
            "slug": slug,
            "title": slug.title(),
            "profile_name": "mcnp-run",
            "profile_version": "1.0",
        },
        headers=_headers("root"),
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


@dataclasses.dataclass(frozen=True)
class _Fixture:
    """Every id in the two-organization hierarchy :func:`_seed` builds."""

    organization_a: str
    organization_b: str
    project_a1: str
    project_a2: str
    project_b1: str
    datasets_a1: tuple[str, ...]
    dataset_a2: str
    dataset_b1: str


def _seed(client: TestClient) -> _Fixture:
    """Build organizations A and B, A1/A2 under A and B1 under B, and bind alice to A1 only.

    A1 is ``open`` (discoverable) and holds three datasets; A2 is
    ``restricted`` (not discoverable) and B1 is ``open`` but under the
    other organization. ``user:alice`` is granted ``reader`` at A1 alone -
    no organization-scope grant, and no grant at all on A2 or B.
    """
    organization_a = _organization(client, "astro")
    organization_b = _organization(client, "biolab")
    project_a1 = _project(client, organization_a, "sims", classification="open")
    project_a2 = _project(client, organization_a, "sealed-sims", classification="restricted")
    project_b1 = _project(client, organization_b, "genomes", classification="open")
    datasets_a1 = tuple(_dataset(client, project_a1, slug) for slug in ("zeta", "astro", "mid"))
    dataset_a2 = _dataset(client, project_a2, "hidden-run")
    dataset_b1 = _dataset(client, project_b1, "other-run")

    bound = client.post(
        f"/api/v1/projects/{project_a1}/bindings",
        json={"principal": "user:alice", "role": "reader"},
        headers=_headers("root"),
    )
    assert bound.status_code == 201, bound.text

    return _Fixture(
        organization_a=organization_a,
        organization_b=organization_b,
        project_a1=project_a1,
        project_a2=project_a2,
        project_b1=project_b1,
        datasets_a1=datasets_a1,
        dataset_a2=dataset_a2,
        dataset_b1=dataset_b1,
    )


def test_organization_listing_shows_only_the_organization_alice_can_discover(
    client: TestClient,
) -> None:
    """A tight page over organizations returns only A, exhausted after the one alice can see."""
    fixture = _seed(client)

    response = client.get("/api/v1/organizations", params={"limit": 1}, headers=_headers("alice"))
    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body["items"]] == [fixture.organization_a]
    assert body["next_cursor"] is None


def test_project_listing_excludes_a_sibling_alice_holds_no_binding_on(client: TestClient) -> None:
    """A tight page over A's projects shows only A1, alice's grant, exhausted after it."""
    fixture = _seed(client)

    response = client.get(
        f"/api/v1/organizations/{fixture.organization_a}/projects",
        params={"limit": 1},
        headers=_headers("alice"),
    )
    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body["items"]] == [fixture.project_a1]
    assert body["next_cursor"] is None


def test_project_listing_excludes_a_sibling_hidden_by_classification(client: TestClient) -> None:
    """An organization-scope grant reaches both of A's projects, yet A2 stays hidden.

    Unlike alice's project-scope grant, bob's organization-scope ``reader``
    binding at A covers ``dataset.discover`` for every project beneath it -
    A1 and A2 alike - so the binding's reach is not what excludes A2. A1 is
    listed because ``open`` is discoverable; A2 is not, because
    ``restricted`` is not, which is the classification gate itself doing
    the work.
    """
    fixture = _seed(client)

    bound = client.post(
        f"/api/v1/organizations/{fixture.organization_a}/bindings",
        json={"principal": "user:bob", "role": "reader"},
        headers=_headers("root"),
    )
    assert bound.status_code == 201, bound.text

    response = client.get(
        f"/api/v1/organizations/{fixture.organization_a}/projects", headers=_headers("bob")
    )
    assert response.status_code == 200
    ids = [item["id"] for item in response.json()["items"]]
    assert ids == [fixture.project_a1]


def test_dataset_cursor_walk_never_surfaces_another_organizations_id(client: TestClient) -> None:
    """A `limit=1` walk over A1's datasets visits each once; no id or cursor names B's dataset."""
    fixture = _seed(client)
    forbidden_ids = {fixture.dataset_a2, fixture.dataset_b1}

    seen: list[str] = []
    cursor: str | None = None
    for _ in range(len(fixture.datasets_a1) + 1):
        params = {"limit": 1} | ({"after": cursor} if cursor is not None else {})
        response = client.get(
            f"/api/v1/projects/{fixture.project_a1}/datasets",
            params=params,
            headers=_headers("alice"),
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body["items"]) == 1
        item_id = body["items"][0]["id"]
        assert item_id not in forbidden_ids
        seen.append(item_id)
        cursor = body["next_cursor"]
        if cursor is not None:
            assert decode_cursor(cursor)[-1] not in forbidden_ids
        else:
            break
    else:
        pytest.fail("cursor walk did not terminate within the expected number of pages")

    assert sorted(seen) == sorted(fixture.datasets_a1)
    assert len(seen) == len(set(seen))


def test_reads_of_invisible_resources_answer_not_found(client: TestClient) -> None:
    """Every read naming a resource outside alice's visibility answers 404, never 403."""
    fixture = _seed(client)
    headers = _headers("alice")

    paths = [
        f"/api/v1/organizations/{fixture.organization_b}",
        f"/api/v1/projects/{fixture.project_b1}",
        f"/api/v1/datasets/{fixture.dataset_b1}",
        f"/api/v1/projects/{fixture.project_a2}",
        f"/api/v1/datasets/{fixture.datasets_a1[0]}/releases/does-not-exist",
        f"/api/v1/datasets/{fixture.dataset_b1}/layers",
    ]
    for path in paths:
        response = client.get(path, headers=headers)
        assert response.status_code == 404, (path, response.text)
        assert response.json()["code"] == "NOT_FOUND"


def test_patching_a_project_outside_visibility_answers_not_found(client: TestClient) -> None:
    """Patching a project alice cannot discover answers 404, not 403, even with a fresh If-Match."""
    fixture = _seed(client)

    response = client.patch(
        f"/api/v1/projects/{fixture.project_b1}",
        json={"title": "Renamed"},
        headers={**_headers("alice"), "If-Match": "1"},
    )
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


def test_creating_under_an_invisible_organization_answers_not_found(client: TestClient) -> None:
    """Creating a project under an organization alice cannot discover answers 404."""
    fixture = _seed(client)

    response = client.post(
        f"/api/v1/organizations/{fixture.organization_b}/projects",
        json={"slug": "nope", "title": "Nope", "data_classification": "open"},
        headers=_headers("alice"),
    )
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


def test_a_principal_with_no_bindings_sees_nothing(client: TestClient) -> None:
    """An unbound principal gets an empty organizations page and 404 for every id in the fixture."""
    fixture = _seed(client)
    headers = _headers("mallory")

    listing = client.get("/api/v1/organizations", headers=headers)
    assert listing.status_code == 200
    assert listing.json() == {"items": [], "next_cursor": None}

    invisible_paths = [
        f"/api/v1/organizations/{fixture.organization_a}",
        f"/api/v1/organizations/{fixture.organization_b}",
        f"/api/v1/organizations/{fixture.organization_a}/projects",
        f"/api/v1/organizations/{fixture.organization_b}/projects",
        f"/api/v1/projects/{fixture.project_a1}",
        f"/api/v1/projects/{fixture.project_a2}",
        f"/api/v1/projects/{fixture.project_b1}",
        f"/api/v1/projects/{fixture.project_a1}/datasets",
        f"/api/v1/projects/{fixture.project_b1}/datasets",
        f"/api/v1/datasets/{fixture.datasets_a1[0]}",
        f"/api/v1/datasets/{fixture.dataset_a2}",
        f"/api/v1/datasets/{fixture.dataset_b1}",
        f"/api/v1/datasets/{fixture.datasets_a1[0]}/releases",
        f"/api/v1/datasets/{fixture.datasets_a1[0]}/layers",
    ]
    for path in invisible_paths:
        response = client.get(path, headers=headers)
        assert response.status_code == 404, (path, response.text)
        assert response.json()["code"] == "NOT_FOUND"
