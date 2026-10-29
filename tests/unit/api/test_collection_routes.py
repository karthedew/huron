"""Namespaces, collections, commits, files, search and logs over HTTP."""

import httpx

from tests.support.api import Service

META = {"title": "Run 7", "description": "Solar wind run seven", "labels": {"site": "a"}}
SHA = "c" * 64


async def draft(api: Service, name: str = "run7", metadata: dict | None = None) -> httpx.Response:  # type: ignore[type-arg]
    return await api.client.post(
        "/api/v1/catalogs/heliophysics/namespaces/solar-wind/collections",
        json={"name": name, "metadata": metadata},
        headers=await api.headers("dave"),
    )


async def active(api: Service, name: str = "run7") -> dict:  # type: ignore[type-arg]
    created = (await draft(api, name, META)).json()
    response = await api.client.post(
        f"/api/v1/collections/{created['id']}/activate",
        headers=await api.headers("dave", **{"If-Match": '"1"'}),
    )
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


async def test_namespaces(seeded_api: Service) -> None:
    c = seeded_api.client
    carol = await seeded_api.headers("carol")
    erin = await seeded_api.headers("erin")
    parent = "solar-wind"
    for depth in range(11):
        made = await c.post(
            "/api/v1/catalogs/heliophysics/namespaces",
            json={"parent": parent, "name": f"l{depth}"},
            headers=carol,
        )
        assert made.status_code == 201, made.text
        parent = made.json()["path"]
    deep = await c.get(f"/api/v1/catalogs/heliophysics/namespaces/{parent}", headers=erin)
    assert deep.json()["identifier"] == f"heliophysics.{parent}"
    children = await c.get(
        "/api/v1/catalogs/heliophysics/namespaces?parent=solar-wind", headers=erin
    )
    assert [n["name"] for n in children.json()["items"]] == ["l0"]
    missing = await c.post(
        "/api/v1/catalogs/heliophysics/namespaces",
        json={"parent": "nope", "name": "x"},
        headers=carol,
    )
    assert missing.status_code == 404
    bad = await c.post(
        "/api/v1/catalogs/heliophysics/namespaces", json={"name": "Bad"}, headers=carol
    )
    assert bad.json()["code"] == "NAME_INVALID"
    configured = await c.patch(
        "/api/v1/catalogs/heliophysics/namespaces/solar-wind.l0",
        json={"collections_allowed": True},
        headers=carol,
    )
    assert configured.json()["collections_allowed"] is True
    busy = await c.delete("/api/v1/catalogs/heliophysics/namespaces/solar-wind", headers=carol)
    assert busy.json()["code"] == "NAMESPACE_NOT_EMPTY"
    leaf = await c.delete(f"/api/v1/catalogs/heliophysics/namespaces/{parent}", headers=carol)
    assert leaf.status_code == 204


async def test_collection_lifecycle_with_etags(seeded_api: Service) -> None:
    c = seeded_api.client
    created = await draft(seeded_api)
    assert created.status_code == 201 and created.headers["ETag"] == '"1"'
    body = created.json()
    assert body["state"] == "draft" and body["problems"] and body["path"] is None
    cid = body["id"]
    no_match = await c.patch(
        f"/api/v1/collections/{cid}",
        json={"metadata": META},
        headers=await seeded_api.headers("dave"),
    )
    assert no_match.status_code == 428 and no_match.json()["code"] == "PRECONDITION_REQUIRED"
    malformed = await c.patch(
        f"/api/v1/collections/{cid}",
        json={"metadata": META},
        headers=await seeded_api.headers("dave", **{"If-Match": "1"}),
    )
    assert malformed.status_code == 428
    patched = await c.patch(
        f"/api/v1/collections/{cid}",
        json={"metadata": META},
        headers=await seeded_api.headers("dave", **{"If-Match": '"1"'}),
    )
    assert patched.status_code == 200 and patched.headers["ETag"] == '"2"'
    stale = await c.post(
        f"/api/v1/collections/{cid}/activate",
        headers=await seeded_api.headers("dave", **{"If-Match": '"1"'}),
    )
    assert stale.status_code == 412 and stale.json()["context"] == {"current_version": 2}
    activated = await c.post(
        f"/api/v1/collections/{cid}/activate",
        headers=await seeded_api.headers("dave", **{"If-Match": '"2"'}),
    )
    assert activated.json()["path"] == "helio/heliophysics/solar-wind/run7"
    erin = await seeded_api.headers("erin")
    by_name = await c.get("/api/v1/catalogs/heliophysics/collections/solar-wind.run7", headers=erin)
    assert by_name.json()["id"] == cid and by_name.headers["ETag"] == '"3"'
    assert (await c.get(f"/api/v1/collections/{cid}", headers=erin)).json()["version"] == 3
    schema = (await c.get(f"/api/v1/collections/{cid}/schema", headers=erin)).json()
    assert schema["required"] == ["title", "description"]
    sidecar = await c.get(f"/api/v1/collections/{cid}/metadata.json", headers=erin)
    assert sidecar.headers["content-type"] == "application/json"
    assert sidecar.json()["identifier"] == "heliophysics.solar-wind.run7"
    override = {"type": "object", "properties": {"run": {"type": "integer"}}, "required": ["run"]}
    invalid = await c.patch(
        f"/api/v1/collections/{cid}",
        json={"schema_override": override},
        headers=await seeded_api.headers("dave", **{"If-Match": '"3"'}),
    )
    assert invalid.json()["code"] == "METADATA_INVALID"
    both = await c.patch(
        f"/api/v1/collections/{cid}",
        json={"schema_override": override, "metadata": {"run": 7}},
        headers=await seeded_api.headers("dave", **{"If-Match": '"3"'}),
    )
    assert both.json()["schema_override"] == override
    cleared = await c.patch(
        f"/api/v1/collections/{cid}",
        json={"schema_override": None},
        headers=await seeded_api.headers("dave", **{"If-Match": '"4"'}),
    )
    assert cleared.json()["schema_override"] is None
    log = (await c.get(f"/api/v1/collections/{cid}/log", headers=erin)).json()
    assert log["items"][0]["action"] == "collection.set_schema_override"


async def test_drafts_are_hidden_from_readers(seeded_api: Service) -> None:
    c = seeded_api.client
    await draft(seeded_api, "hidden")
    await active(seeded_api, "shown")
    erin = await seeded_api.headers("erin")
    listing = await c.get(
        "/api/v1/catalogs/heliophysics/namespaces/solar-wind/collections", headers=erin
    )
    assert [x["name"] for x in listing.json()["items"]] == ["shown"]
    dave = await seeded_api.headers("dave")
    listing = await c.get(
        "/api/v1/catalogs/heliophysics/namespaces/solar-wind/collections", headers=dave
    )
    assert [x["name"] for x in listing.json()["items"]] == ["hidden", "shown"]


async def test_commits_files_and_conflicts(seeded_api: Service) -> None:
    c = seeded_api.client
    cid = (await active(seeded_api))["id"]
    dave = await seeded_api.headers("dave")
    body = {
        "base_version": 2,
        "adds": [{"rel_path": "a.txt", "size": 1, "sha256": SHA}],
        "removes": [],
        "host": "ws1",
        "message": "first",
    }
    first = await c.post(f"/api/v1/collections/{cid}/commits", json=body, headers=dave)
    assert first.status_code == 200 and first.json()["version"] == 3
    assert first.headers["ETag"] == '"3"'
    stale = await c.post(f"/api/v1/collections/{cid}/commits", json=body, headers=dave)
    assert stale.status_code == 409 and stale.json()["code"] == "BASE_VERSION_CONFLICT"
    assert stale.json()["context"]["current_version"] == 3
    too_big = {**body, "base_version": 3, "removes": [str(i) for i in range(10_001)]}
    big = await c.post(f"/api/v1/collections/{cid}/commits", json=too_big, headers=dave)
    assert big.status_code == 413
    malformed = await c.post(f"/api/v1/collections/{cid}/commits", json={"x": 1}, headers=dave)
    assert malformed.json()["code"] == "COMMIT_INVALID"
    erin = await seeded_api.headers("erin")
    files = (await c.get(f"/api/v1/collections/{cid}/files", headers=erin)).json()
    assert files["items"][0]["rel_path"] == "a.txt"
    commits = (await c.get(f"/api/v1/collections/{cid}/commits", headers=erin)).json()
    assert commits["items"][0]["message"] == "first"
    refused = await c.post(
        f"/api/v1/collections/{cid}/commits", json={**body, "base_version": 3}, headers=erin
    )
    assert refused.status_code == 403
    not_empty = await c.delete(
        f"/api/v1/collections/{cid}",
        headers=await seeded_api.headers("dave", **{"If-Match": '"3"'}),
    )
    assert not_empty.json()["code"] == "COLLECTION_NOT_EMPTY"
    removal = {"base_version": 3, "adds": [], "removes": ["a.txt"], "host": "ws1"}
    assert (
        await c.post(f"/api/v1/collections/{cid}/commits", json=removal, headers=dave)
    ).status_code == 200
    deleted = await c.delete(
        f"/api/v1/collections/{cid}",
        headers=await seeded_api.headers("dave", **{"If-Match": '"4"'}),
    )
    assert deleted.status_code == 204


async def test_search(seeded_api: Service) -> None:
    c = seeded_api.client
    await active(seeded_api, "alpha")
    await draft(seeded_api, "beta")
    erin = await seeded_api.headers("erin")
    hits = await c.get("/api/v1/catalogs/heliophysics/search?q=solar&label=site=a", headers=erin)
    assert [x["name"] for x in hits.json()["items"]] == ["alpha"]
    colon = await c.get("/api/v1/catalogs/heliophysics/search?label=site:b", headers=erin)
    assert colon.json()["items"] == []
    drafts = await c.get(
        "/api/v1/catalogs/heliophysics/search?state=draft", headers=await seeded_api.headers("dave")
    )
    assert [x["name"] for x in drafts.json()["items"]] == ["beta"]
    bad = await c.get("/api/v1/catalogs/heliophysics/search?label=nolabel", headers=erin)
    assert bad.status_code == 422
