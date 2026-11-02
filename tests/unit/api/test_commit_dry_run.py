"""``POST /collections/{id}/commits?dry_run=true`` over HTTP: checked like a commit, no change."""

from typing import Any

from tests.support.api import Service

META = {"title": "Run 7", "description": "Solar wind run seven", "labels": {"site": "a"}}
SHA = "d" * 64


async def active(api: Service) -> str:
    created = await api.client.post(
        "/api/v1/catalogs/heliophysics/namespaces/solar-wind/collections",
        json={"name": "run7", "metadata": META},
        headers=await api.headers("dave"),
    )
    cid = str(created.json()["id"])
    activated = await api.client.post(
        f"/api/v1/collections/{cid}/activate",
        headers=await api.headers("dave", **{"If-Match": '"1"'}),
    )
    assert activated.status_code == 200, activated.text
    return cid


def unhashed(base_version: int = 2, **extra: Any) -> dict[str, Any]:
    return {
        "base_version": base_version,
        "adds": [{"rel_path": "a.txt", "size": 5}],
        "removes": [],
        "host": "ws1",
        **extra,
    }


async def state(api: Service, cid: str) -> tuple[int, int, int]:
    erin = await api.headers("erin")
    collection = (await api.client.get(f"/api/v1/collections/{cid}", headers=erin)).json()
    commits = (await api.client.get(f"/api/v1/collections/{cid}/commits", headers=erin)).json()
    return collection["version"], collection["file_count"], len(commits["items"])


async def test_a_dry_run_answers_the_would_be_result_without_committing(
    seeded_api: Service,
) -> None:
    cid = await active(seeded_api)
    dave = await seeded_api.headers("dave")
    answer = await seeded_api.client.post(
        f"/api/v1/collections/{cid}/commits",
        params={"dry_run": "true"},
        json=unhashed(message="first"),
        headers=dave,
    )
    assert answer.status_code == 200, answer.text
    assert answer.json() == {"version": 3, "file_count": 1, "commit_id": None}
    assert "ETag" not in answer.headers
    assert await state(seeded_api, cid) == (2, 0, 0)
    log = await seeded_api.client.get(f"/api/v1/collections/{cid}/log", headers=dave)
    assert "collection.commit" not in [entry["action"] for entry in log.json()["items"]]


async def test_a_dry_run_is_refused_like_a_commit(seeded_api: Service) -> None:
    cid = await active(seeded_api)
    c = seeded_api.client
    url = f"/api/v1/collections/{cid}/commits?dry_run=true"
    reader = await c.post(url, json=unhashed(), headers=await seeded_api.headers("erin"))
    assert reader.status_code == 403 and reader.json()["code"] == "FORBIDDEN"
    dave = await seeded_api.headers("dave")
    stale = await c.post(url, json=unhashed(base_version=1), headers=dave)
    assert stale.status_code == 409 and stale.json()["code"] == "BASE_VERSION_CONFLICT"
    assert stale.json()["context"] == {"current_version": 2, "base_version": 1}
    malformed = await c.post(url, json={"adds": []}, headers=dave)
    assert malformed.status_code == 422 and malformed.json()["code"] == "COMMIT_INVALID"
    missing = await c.post(url, json={**unhashed(), "removes": ["gone.txt"]}, headers=dave)
    assert missing.json()["code"] == "FILE_NOT_RECORDED"
    too_big = await c.post(
        url, json={**unhashed(), "removes": [str(i) for i in range(10_001)]}, headers=dave
    )
    assert too_big.status_code == 413
    assert await state(seeded_api, cid) == (2, 0, 0)


async def test_a_real_commit_still_needs_hashes(seeded_api: Service) -> None:
    cid = await active(seeded_api)
    dave = await seeded_api.headers("dave")
    refused = await seeded_api.client.post(
        f"/api/v1/collections/{cid}/commits", json=unhashed(), headers=dave
    )
    assert refused.status_code == 422 and refused.json()["code"] == "COMMIT_INVALID"
    hashed = {**unhashed(), "adds": [{"rel_path": "a.txt", "size": 5, "sha256": SHA}]}
    preview = await seeded_api.client.post(
        f"/api/v1/collections/{cid}/commits?dry_run=true", json=hashed, headers=dave
    )
    committed = await seeded_api.client.post(
        f"/api/v1/collections/{cid}/commits", json=hashed, headers=dave
    )
    assert committed.status_code == 200 and committed.headers["ETag"] == '"3"'
    real = committed.json()
    assert preview.json() == {**real, "commit_id": None} and real["commit_id"]
