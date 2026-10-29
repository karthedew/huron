"""Organizations, grants, schemas, catalogs and signing keys over HTTP."""

from datetime import timedelta

from tests.support.api import Service


async def test_organizations_lifecycle(api: Service) -> None:
    alice = await api.headers("alice")
    c = api.client
    created = await c.post(
        "/api/v1/organizations", json={"name": "helio", "description": "d"}, headers=alice
    )
    assert created.status_code == 201 and created.json()["catalog_count"] == 0
    await c.post("/api/v1/organizations", json={"name": "geo"}, headers=alice)
    page = (await c.get("/api/v1/organizations?limit=1", headers=alice)).json()
    assert [o["name"] for o in page["items"]] == ["geo"]
    rest = (
        await c.get(f"/api/v1/organizations?cursor={page['next_cursor']}", headers=alice)
    ).json()
    assert [o["name"] for o in rest["items"]] == ["helio"]
    assert (await c.get("/api/v1/organizations/helio", headers=alice)).json()["name"] == "helio"
    hidden = await c.get("/api/v1/organizations/helio", headers=await api.headers("erin"))
    assert hidden.status_code == 404
    taken = await c.post("/api/v1/organizations", json={"name": "geo"}, headers=alice)
    assert taken.status_code == 409 and taken.json()["code"] == "NAME_TAKEN"
    assert (await c.delete("/api/v1/organizations/geo", headers=alice)).status_code == 204
    forbidden = await c.post(
        "/api/v1/organizations", json={"name": "x"}, headers=await api.headers("bob")
    )
    assert forbidden.status_code == 403


async def test_platform_and_organization_grants(seeded_api: Service) -> None:
    alice = await seeded_api.headers("alice")
    c = seeded_api.client
    assert (await c.get("/api/v1/platform/grants", headers=alice)).json()["ldap_groups"] == [
        "huron-platform-admins"
    ]
    refused = await c.put(
        "/api/v1/platform/grants/platform_admin", json={"ldap_groups": []}, headers=alice
    )
    assert refused.status_code == 422
    change = await c.put(
        "/api/v1/platform/grants/platform_admin",
        json={"ldap_groups": ["huron-platform-admins", "ops"]},
        headers=alice,
    )
    assert change.json()["added"] == ["ops"]
    org = (await c.get("/api/v1/organizations/helio/grants", headers=alice)).json()
    assert org == {"role": "org_admin", "ldap_groups": ["helio-org-admins"]}
    effective = (
        await c.get(
            "/api/v1/catalogs/heliophysics/grants", headers=await seeded_api.headers("erin")
        )
    ).json()
    assert effective["contributor"] == ["helio-contributors"]
    assert effective["platform_admin"] == ["huron-platform-admins", "ops"]
    bad_role = await c.put(
        "/api/v1/catalogs/heliophysics/grants/org_admin", json={"ldap_groups": []}, headers=alice
    )
    assert bad_role.status_code == 422


async def test_schemas_and_assignment(seeded_api: Service) -> None:
    c = seeded_api.client
    bob = await seeded_api.headers("bob")
    carol = await seeded_api.headers("carol")
    erin = await seeded_api.headers("erin")
    platform = (await c.get("/api/v1/platform/schemas", headers=erin)).json()["items"]
    base = platform[0]
    assert base["name"] == "huron-base"
    resolved = (await c.get(f"/api/v1/schemas/{base['id']}/resolved", headers=erin)).json()
    assert resolved["required"] == ["title", "description"]
    assert (await c.get(f"/api/v1/schemas/{base['id']}", headers=erin)).json()["version"] == 1
    document = {
        "type": "object",
        "properties": {"mission": {"type": "string"}},
        "required": ["mission"],
    }
    published = await c.post(
        "/api/v1/organizations/helio/schemas",
        json={"name": "helio", "extends_id": base["id"], "document": document},
        headers=bob,
    )
    assert published.status_code == 201, published.text
    listed = (await c.get("/api/v1/organizations/helio/schemas", headers=erin)).json()
    assert [e["name"] for e in listed["items"]] == ["helio"]
    assigned = await c.put(
        "/api/v1/catalogs/heliophysics/schema",
        json={"schema_id": published.json()["id"]},
        headers=carol,
    )
    assert assigned.json()["recompute"] == {"active": 0, "incomplete": 0, "changed": 0}
    assert assigned.json()["assigned"]["schema"]["name"] == "helio"
    schema = (await c.get("/api/v1/catalogs/heliophysics/schema", headers=erin)).json()
    assert "mission" in schema["required"]
    invalid = await c.post(
        "/api/v1/organizations/helio/schemas",
        json={"name": "x", "extends_id": base["id"], "document": {"type": "array"}},
        headers=bob,
    )
    assert invalid.json()["code"] == "SCHEMA_INVALID"
    platform_publish = await c.post(
        "/api/v1/platform/schemas",
        json={"name": "huron-base", "document": document},
        headers=await seeded_api.headers("alice"),
    )
    assert platform_publish.json()["version"] == 2


async def test_catalogs(seeded_api: Service) -> None:
    c = seeded_api.client
    bob = await seeded_api.headers("bob")
    erin = await seeded_api.headers("erin")
    created = await c.post(
        "/api/v1/organizations/helio/catalogs", json={"name": "aurora"}, headers=bob
    )
    assert created.json()["schema"]["name"] == "huron-base"
    names = [x["name"] for x in (await c.get("/api/v1/catalogs", headers=bob)).json()["items"]]
    assert names == ["aurora", "heliophysics"]
    scoped = await c.get("/api/v1/catalogs?organization=helio", headers=erin)
    assert [x["name"] for x in scoped.json()["items"]] == ["heliophysics"]
    assert (await c.get("/api/v1/catalogs/heliophysics", headers=erin)).json()[
        "namespace_count"
    ] == 1
    not_empty = await c.delete("/api/v1/catalogs/heliophysics", headers=bob)
    assert not_empty.status_code == 409 and not_empty.json()["code"] == "CATALOG_NOT_EMPTY"
    assert (await c.delete("/api/v1/catalogs/aurora", headers=bob)).status_code == 204
    log = (await c.get("/api/v1/catalogs/heliophysics/log?limit=500", headers=erin)).json()
    assert log["items"][0]["action"] == "namespace.create"


async def test_signing_key_rotation_shows_in_jwks(api: Service) -> None:
    alice = await api.headers("alice")
    before = {k["kid"] for k in (await api.client.get("/jwks.json")).json()["keys"]}
    api.clock.advance(timedelta(seconds=1))
    rotated = await api.client.post("/api/v1/admin/signing-keys/rotate", headers=alice)
    assert rotated.status_code == 201
    after = {k["kid"] for k in (await api.client.get("/jwks.json")).json()["keys"]}
    assert rotated.json()["kid"] in after and before <= after
    keys = (await api.client.get("/api/v1/admin/signing-keys", headers=alice)).json()
    assert keys[0]["kid"] == rotated.json()["kid"] and "private_pem" not in keys[0]
    denied = await api.client.get("/api/v1/admin/signing-keys", headers=await api.headers("erin"))
    assert denied.status_code == 403
