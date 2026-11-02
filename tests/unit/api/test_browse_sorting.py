"""Global browse sorting, cursor isolation and visibility through the HTTP API."""

from dataclasses import replace
from datetime import timedelta

import pytest

from huron.core.lake.collections.models import State
from huron.core.security.rbac import Role, Scope
from tests.contract.suite import catalog, collection, namespace, organization
from tests.support.api import Service
from tests.support.clock import START

PATHS = {
    "catalogs": "/api/v1/catalogs?organization=browse",
    "namespaces": "/api/v1/catalogs/heliophysics/namespaces?parent=children",
    "collections": "/api/v1/catalogs/heliophysics/namespaces/solar-wind/collections?",
}
EXPECTED = {
    "name": ["alpha", "bravo", "charlie", "delta"],
    "created_by": ["bravo", "charlie", "alpha", "delta"],
    "created_at": ["bravo", "charlie", "delta", "alpha"],
}


@pytest.fixture
async def browse_api(api: Service) -> Service:
    """Four browse records with distinct ordering and ties, plus a hidden draft."""
    async with api.runtime.store.transaction() as tx:
        base = await tx.schemas.latest(None, "huron-base")
        assert base is not None
        owner = organization()
        cat = catalog(owner, base.id)
        ns = namespace(cat, "solar-wind")
        await tx.organizations.insert(owner)
        await tx.catalogs.insert(cat)
        await tx.namespaces.insert(ns)
    org = organization("browse")
    parent = namespace(cat, "children")
    async with api.runtime.store.transaction() as tx:
        await tx.organizations.insert(org)
        await tx.namespaces.insert(parent)
        await tx.grants.replace(Scope.catalog(cat.id), Role.READER, ["helio-readers"], "test")
        for name, creator, day in [
            ("alpha", "zoe", 3),
            ("bravo", "alice", 1),
            ("charlie", "alice", 1),
            ("delta", "éclair", 2),
        ]:
            made = replace(
                catalog(org, cat.schema_id, name),
                created_by=creator,
                created_at=START + timedelta(days=day),
            )
            await tx.catalogs.insert(made)
            if name in ("bravo", "charlie"):
                await tx.grants.replace(
                    Scope.catalog(made.id), Role.READER, ["helio-readers"], "test"
                )
            await tx.namespaces.insert(
                replace(
                    namespace(cat, f"children.{name}", parent),
                    created_by=creator,
                    created_at=START + timedelta(days=day),
                )
            )
            await tx.collections.insert(
                replace(
                    collection(cat, ns, name),
                    created_by=creator,
                    created_at=START + timedelta(days=day),
                )
            )
    return api


@pytest.mark.parametrize("family", list(PATHS))
@pytest.mark.parametrize("sort", list(EXPECTED))
@pytest.mark.parametrize("order", ["asc", "desc"])
async def test_sorting_is_global_across_pages_and_preserves_name_ties(
    browse_api: Service, family: str, sort: str, order: str
) -> None:
    headers = await browse_api.headers("alice")
    url = f"{PATHS[family]}&sort={sort}&order={order}&limit=1"
    names: list[str] = []
    cursor = None
    for _ in range(4):
        response = await browse_api.client.get(
            url + (f"&cursor={cursor}" if cursor else ""), headers=headers
        )
        assert response.status_code == 200, response.text
        page = response.json()
        names.extend(row["name"] for row in page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert names == (EXPECTED[sort] if order == "asc" else list(reversed(EXPECTED[sort])))
    assert cursor is None


@pytest.mark.parametrize("family", list(PATHS))
async def test_cursors_cannot_be_carried_to_a_different_sort(
    browse_api: Service, family: str
) -> None:
    headers = await browse_api.headers("alice")
    first = await browse_api.client.get(f"{PATHS[family]}&sort=created_at&limit=1", headers=headers)
    cursor = first.json()["next_cursor"]
    for query in ("sort=created_at&order=desc", "sort=created_by", "sort=name"):
        response = await browse_api.client.get(
            f"{PATHS[family]}&{query}&cursor={cursor}", headers=headers
        )
        assert response.status_code == 400, response.text
        assert response.json()["code"] == "INVALID_CURSOR"


@pytest.mark.parametrize("family", list(PATHS))
@pytest.mark.parametrize("query", ["sort=owner", "order=sideways", "sort=name%3Bdrop"])
async def test_unknown_sort_parameters_are_rejected(
    browse_api: Service, family: str, query: str
) -> None:
    response = await browse_api.client.get(
        f"{PATHS[family]}&{query}", headers=await browse_api.headers("alice")
    )
    assert response.status_code == 422
    assert response.json()["code"] == "REQUEST_INVALID"


@pytest.mark.parametrize("sort", list(EXPECTED))
async def test_sorting_filters_invisible_catalogs_and_drafts_before_the_limit(
    browse_api: Service, sort: str
) -> None:
    headers = await browse_api.headers("erin")
    response = await browse_api.client.get(
        f"{PATHS['catalogs']}&sort={sort}&limit=1", headers=headers
    )
    assert [row["name"] for row in response.json()["items"]] == ["bravo"]
    second = await browse_api.client.get(
        f"{PATHS['catalogs']}&sort={sort}&limit=1&cursor={response.json()['next_cursor']}",
        headers=headers,
    )
    assert [row["name"] for row in second.json()["items"]] == ["charlie"]
    assert second.json()["next_cursor"] is None
    async with browse_api.runtime.store.transaction() as tx:
        cat = await tx.catalogs.get_by_name("heliophysics")
        assert cat is not None
        ns = await tx.namespaces.get_by_path(cat.id, "solar-wind")
        assert ns is not None
        await tx.collections.insert(
            replace(
                collection(cat, ns, "aaa-hidden", state=State.DRAFT),
                created_by="aaa",
                created_at=START - timedelta(days=1),
            )
        )
    response = await browse_api.client.get(
        f"{PATHS['collections']}&sort={sort}&limit=1", headers=headers
    )
    assert [row["name"] for row in response.json()["items"]] == [EXPECTED[sort][0]]


@pytest.mark.parametrize("family", ["namespaces", "collections"])
async def test_sorting_does_not_reveal_inaccessible_catalog_contents(
    browse_api: Service, family: str
) -> None:
    response = await browse_api.client.get(
        f"{PATHS[family]}&sort=created_by&order=desc", headers=await browse_api.headers("mallory")
    )
    assert response.status_code == 404
