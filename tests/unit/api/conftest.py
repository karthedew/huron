"""Fixtures for API tests."""

from collections.abc import AsyncIterator

import pytest

from tests.support.api import Service, service


@pytest.fixture
async def api() -> AsyncIterator[Service]:
    """An in-process service over an empty in-memory store."""
    async with service() as running:
        yield running


@pytest.fixture
async def seeded_api(api: Service) -> Service:
    """The helio organization, catalog, grants and the solar-wind namespace, through the API."""
    c = api.client
    alice = await api.headers("alice")
    bob = await api.headers("bob")
    carol = await api.headers("carol")
    assert (
        await c.post("/api/v1/organizations", json={"name": "helio"}, headers=alice)
    ).status_code == 201
    await c.put(
        "/api/v1/organizations/helio/grants/org_admin",
        json={"ldap_groups": ["helio-org-admins"]},
        headers=alice,
    )
    assert (
        await c.post(
            "/api/v1/organizations/helio/catalogs", json={"name": "heliophysics"}, headers=bob
        )
    ).status_code == 201
    await c.put(
        "/api/v1/catalogs/heliophysics/grants/catalog_admin",
        json={"ldap_groups": ["helio-catalog-admins"]},
        headers=bob,
    )
    for role, group in (("contributor", "helio-contributors"), ("reader", "helio-readers")):
        await c.put(
            f"/api/v1/catalogs/heliophysics/grants/{role}",
            json={"ldap_groups": [group]},
            headers=carol,
        )
    created = await c.post(
        "/api/v1/catalogs/heliophysics/namespaces",
        json={"name": "solar-wind", "collections_allowed": True},
        headers=carol,
    )
    assert created.status_code == 201, created.text
    return api
