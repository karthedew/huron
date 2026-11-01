"""Managed mode through the API: declared organizations, their 409s and the share roots."""

import logging
from collections.abc import AsyncIterator

import pytest

from huron.core.lake.organizations.declarations import UNMANAGED
from huron.core.metastore.store import MemoryStore
from tests.support.api import Service, service

DECLARED = [
    {
        "name": "helio",
        "display_name": "Heliophysics",
        "groups": {"org_admin": ["helio-org-admins"], "reader": ["helio-everyone"]},
        "root": "/data1/huron",
        "export": "nfs1:/export/helio",
    },
    {"name": "geo", "display_name": "Geoscience", "groups": {"org_admin": ["geo-org-admins"]}},
]


@pytest.fixture
async def managed() -> AsyncIterator[Service]:
    """A service whose configuration declares helio (rooted) and geo (unrooted)."""
    async with service(organizations=DECLARED) as running:
        yield running


async def test_declared_organizations_exist_with_their_configuration(managed: Service) -> None:
    alice = await managed.headers("alice")
    page = (await managed.client.get("/api/v1/organizations", headers=alice)).json()
    rows = {row["name"]: row for row in page["items"]}
    assert rows["helio"]["display_name"] == "Heliophysics"
    assert rows["helio"]["created_by"] == "huron-bootstrap"
    assert (rows["helio"]["declared"], rows["helio"]["root"], rows["helio"]["path"]) == (
        True,
        "/data1/huron",
        "/data1/huron/helio",
    )
    assert rows["helio"]["export"] == "nfs1:/export/helio"
    assert (rows["geo"]["declared"], rows["geo"]["root"], rows["geo"]["path"]) == (
        True,
        None,
        None,
    )
    assert rows["geo"]["export"] is None
    grants = await managed.client.get("/api/v1/organizations/helio/grants", headers=alice)
    assert grants.json() == {
        "org_admin": ["helio-org-admins"],
        "catalog_admin": [],
        "contributor": [],
        "reader": ["helio-everyone"],
    }
    bob = await managed.headers("bob")
    one = (await managed.client.get("/api/v1/organizations/helio", headers=bob)).json()
    assert one["path"] == "/data1/huron/helio"


async def test_health_says_the_organizations_are_managed(managed: Service) -> None:
    assert (await managed.client.get("/healthz")).json()["organizations_managed"] is True
    async with service(organizations=[]) as empty:
        assert (await empty.client.get("/healthz")).json()["organizations_managed"] is True


async def test_managed_mode_refuses_to_create_organizations(managed: Service) -> None:
    alice = await managed.headers("alice")
    response = await managed.client.post(
        "/api/v1/organizations", json={"name": "astro"}, headers=alice
    )
    assert response.status_code == 409
    assert response.json()["code"] == "ORGANIZATIONS_MANAGED"
    bob = await managed.headers("bob")
    refused = await managed.client.post(
        "/api/v1/organizations", json={"name": "astro"}, headers=bob
    )
    assert refused.status_code == 403


async def test_declared_organizations_cannot_be_deleted_or_regranted(managed: Service) -> None:
    alice = await managed.headers("alice")
    deleted = await managed.client.delete("/api/v1/organizations/geo", headers=alice)
    assert deleted.status_code == 409
    assert deleted.json()["code"] == "ORGANIZATION_DECLARED"
    assert deleted.json()["context"] == {"organization": "geo"}
    for role in ("org_admin", "catalog_admin", "contributor", "reader"):
        regranted = await managed.client.put(
            f"/api/v1/organizations/helio/grants/{role}",
            json={"ldap_groups": ["someone-else"]},
            headers=alice,
        )
        assert regranted.status_code == 409
        assert regranted.json()["code"] == "ORGANIZATION_DECLARED"
        assert f"groups.{role}" in regranted.json()["detail"]
    bob = await managed.headers("bob")
    by_org_admin = await managed.client.put(
        "/api/v1/organizations/helio/grants/reader", json={"ldap_groups": []}, headers=bob
    )
    assert by_org_admin.status_code == 409


async def test_every_catalog_inherits_the_declared_reader_groups(managed: Service) -> None:
    c = managed.client
    bob = await managed.headers("bob")
    await c.post("/api/v1/organizations/helio/catalogs", json={"name": "sun"}, headers=bob)
    await c.put("/api/v1/catalogs/sun/grants/reader", json={"ldap_groups": ["guests"]}, headers=bob)
    effective = (await c.get("/api/v1/catalogs/sun/grants", headers=bob)).json()
    assert effective["reader"] == ["guests", "helio-everyone"]
    sources = (await c.get("/api/v1/catalogs/sun/grants/sources", headers=bob)).json()
    readers = [row for row in sources["items"] if row["role"] == "reader"]
    assert readers == [
        {"role": "reader", "group": "guests", "scope": "catalog"},
        {"role": "reader", "group": "helio-everyone", "scope": "organization"},
    ]


async def test_share_root_follows_the_owning_organization(managed: Service) -> None:
    c = managed.client
    bob = await managed.headers("bob")
    created = await c.post(
        "/api/v1/organizations/helio/catalogs", json={"name": "sun"}, headers=bob
    )
    assert created.status_code == 201, created.text
    assert created.json()["share_root"] == "/data1/huron"
    assert (await c.get("/api/v1/catalogs/sun", headers=bob)).json()["share_root"] == (
        "/data1/huron"
    )
    listed = (await c.get("/api/v1/catalogs", headers=bob)).json()["items"]
    assert [row["share_root"] for row in listed] == ["/data1/huron"]
    await c.put(
        "/api/v1/catalogs/sun/grants/contributor",
        json={"ldap_groups": ["helio-contributors"]},
        headers=bob,
    )
    namespace = await c.post(
        "/api/v1/catalogs/sun/namespaces",
        json={"name": "wind", "collections_allowed": True},
        headers=bob,
    )
    assert namespace.json()["share_root"] == "/data1/huron"
    for url in ("/api/v1/catalogs/sun/namespaces", "/api/v1/catalogs/sun/namespaces/wind"):
        body = (await c.get(url, headers=bob)).json()
        rows = body.get("items", [body])
        assert {row["share_root"] for row in rows} == {"/data1/huron"}
    dave = await managed.headers("dave")
    draft = await c.post(
        "/api/v1/catalogs/sun/namespaces/wind/collections", json={"name": "run1"}, headers=dave
    )
    assert draft.json()["share_root"] == "/data1/huron"
    cid = draft.json()["id"]
    for url in (
        f"/api/v1/collections/{cid}",
        "/api/v1/catalogs/sun/collections/wind.run1",
    ):
        assert (await c.get(url, headers=dave)).json()["share_root"] == "/data1/huron"
    listed_collections = await c.get(
        "/api/v1/catalogs/sun/namespaces/wind/collections", headers=dave
    )
    assert listed_collections.json()["items"][0]["share_root"] == "/data1/huron"


async def test_unrooted_organizations_have_no_share_root(managed: Service) -> None:
    alice = await managed.headers("alice")
    created = await managed.client.post(
        "/api/v1/organizations/geo/catalogs", json={"name": "rocks"}, headers=alice
    )
    assert created.status_code == 201, created.text
    assert created.json()["share_root"] is None


async def test_unmanaged_services_create_organizations_without_roots(api: Service) -> None:
    alice = await api.headers("alice")
    created = await api.client.post("/api/v1/organizations", json={"name": "astro"}, headers=alice)
    assert created.status_code == 201
    body = created.json()
    assert (body["declared"], body["root"], body["path"], body["export"]) == (
        False,
        None,
        None,
        None,
    )
    assert api.runtime.declarations == UNMANAGED


async def test_startup_warns_about_undeclared_organizations(
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = MemoryStore()
    async with service(store=store) as first:
        alice = await first.headers("alice")
        await first.client.post("/api/v1/organizations", json={"name": "old"}, headers=alice)
    caplog.set_level(logging.INFO, logger="huron.api.bootstrap")
    async with service(store=store, organizations=DECLARED):
        pass
    renamed = [{**DECLARED[0], "display_name": "Helio"}, DECLARED[1]]
    async with service(store=store, organizations=renamed):
        pass
    messages = [r.getMessage() for r in caplog.records if r.name == "huron.api.bootstrap"]
    assert any("organization old (0 catalogs) is not declared" in m for m in messages)
    assert any("created declared organization helio" in m for m in messages)
    assert any("replaced the role groups of declared organization geo" in m for m in messages)
    assert any("updated declared organization helio" in m for m in messages)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 2
