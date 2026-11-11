"""Namespaces, collections, commits, files, search and logs over HTTP."""

import hashlib
import uuid

import httpx

from tests.support.api import Service
from tests.support.tusd import UploadTarget

META = {"title": "Run 7", "description": "Solar wind run seven", "labels": {"site": "a"}}


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


async def test_commits_list_the_files_and_keep_a_collection_until_it_is_empty(
    target: UploadTarget,
) -> None:
    api = target.tusd.api
    c, cid = api.client, target.collection_id
    dave, erin = await api.headers("dave"), await api.headers("erin")
    upload_id = await target.tusd.begin("dave", cid, "a.txt", b"a")
    add = {"rel_path": "a.txt", "size": 1, "sha256": hashlib.sha256(b"a").hexdigest()}
    body = {
        "request_id": str(uuid.uuid4()),
        "base_version": 2,
        "adds": [{**add, "upload_id": upload_id}],
        "removes": [],
        "host": "ws1",
        "message": "first",
    }
    refused = await c.post(f"/api/v1/collections/{cid}/commits", json=body, headers=erin)
    assert refused.status_code == 403
    first = await c.post(
        f"/api/v1/collections/{cid}/commits",
        json={**body, "request_id": str(uuid.uuid4())},
        headers=dave,
    )
    assert first.status_code == 200 and first.json()["version"] == 3
    files = (await c.get(f"/api/v1/collections/{cid}/files", headers=erin)).json()
    assert [(item["rel_path"], item["size"]) for item in files["items"]] == [("a.txt", 1)]
    commits = (await c.get(f"/api/v1/collections/{cid}/commits", headers=erin)).json()
    assert [(item["message"], item["adds"]) for item in commits["items"]] == [("first", 1)]
    not_empty = await c.delete(
        f"/api/v1/collections/{cid}", headers=await api.headers("dave", **{"If-Match": '"3"'})
    )
    assert not_empty.json()["code"] == "COLLECTION_NOT_EMPTY"
    removal = {**body, "request_id": str(uuid.uuid4()), "base_version": 3}
    removal |= {"adds": [], "removes": ["a.txt"]}
    removed = await c.post(f"/api/v1/collections/{cid}/commits", json=removal, headers=dave)
    assert removed.status_code == 200
    deleted = await c.delete(
        f"/api/v1/collections/{cid}", headers=await api.headers("dave", **{"If-Match": '"4"'})
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


async def test_the_sidecar_writes_integers_of_any_size_exactly(seeded_api: Service) -> None:
    created = (await draft(seeded_api, "huge", {**META, "fill": -(10**31)})).json()
    activated = await seeded_api.client.post(
        f"/api/v1/collections/{created['id']}/activate",
        headers=await seeded_api.headers("dave", **{"If-Match": '"1"'}),
    )
    assert activated.status_code == 200, activated.text
    sidecar = await seeded_api.client.get(
        f"/api/v1/collections/{created['id']}/metadata.json",
        headers=await seeded_api.headers("erin"),
    )
    assert sidecar.status_code == 200, sidecar.text
    assert b'"fill":-10000000000000000000000000000000' in sidecar.content
    assert sidecar.json()["metadata"]["fill"] == -(10**31)


async def test_metadata_json_cannot_hold_is_refused(seeded_api: Service) -> None:
    refused = await seeded_api.client.post(
        "/api/v1/catalogs/heliophysics/namespaces/solar-wind/collections",
        content=b'{"name": "nan", "metadata": {"title": "t", "x": NaN}}',
        headers={**(await seeded_api.headers("dave")), "content-type": "application/json"},
    )
    assert refused.status_code == 422
    assert refused.json()["code"] == "METADATA_INVALID"
    assert refused.json()["context"]["problems"][0]["rule"] == "json"


async def commit_files(target: UploadTarget, base_version: int, files: dict[str, bytes]) -> None:
    """Upload ``files`` through tusd's hooks and commit them as dave."""
    api = target.tusd.api
    adds = []
    for rel_path, data in files.items():
        upload_id = await target.tusd.begin("dave", target.collection_id, rel_path, data)
        add = {"rel_path": rel_path, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        adds.append({**add, "upload_id": upload_id})
    body = {"request_id": str(uuid.uuid4()), "base_version": base_version, "adds": adds}
    committed = await api.client.post(
        f"/api/v1/collections/{target.collection_id}/commits",
        json={**body, "removes": [], "host": "ws1"},
        headers=await api.headers("dave"),
    )
    assert committed.status_code == 200, committed.text


async def every_page(api: Service, path: str) -> list[list[dict[str, object]]]:
    """Each page of a listing at ``path`` with ``limit=1``, following ``next_cursor``."""
    erin = await api.headers("erin")
    pages: list[list[dict[str, object]]] = []
    params: dict[str, str | int] = {"limit": 1}
    while True:
        answer = await api.client.get(path, params=params, headers=erin)
        assert answer.status_code == 200
        body = answer.json()
        assert set(body) == {"items", "next_cursor"}
        pages.append(body["items"])
        if body["next_cursor"] is None:
            return pages
        params = {"limit": 1, "cursor": body["next_cursor"]}


async def test_files_and_commits_page_over_http(target: UploadTarget) -> None:
    api = target.tusd.api
    await commit_files(target, 2, {"b.txt": b"b", "A.txt": b"aa"})
    await commit_files(target, 3, {"c.txt": b"ccc"})
    base = f"/api/v1/collections/{target.collection_id}"
    files = await every_page(api, f"{base}/files")
    assert [[(item["rel_path"], item["size"]) for item in page] for page in files] == [
        [("A.txt", 2)],
        [("b.txt", 1)],
        [("c.txt", 3)],
    ]
    commits = await every_page(api, f"{base}/commits")
    assert [[item["new_version"] for item in page] for page in commits] == [[4], [3]]
    erin = await api.headers("erin")
    for listing in ("files", "commits"):
        refused = await api.client.get(
            f"{base}/{listing}", params={"cursor": "not-a-cursor"}, headers=erin
        )
        assert (refused.status_code, refused.json()["code"]) == (400, "INVALID_CURSOR")
