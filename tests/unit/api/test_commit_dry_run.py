"""``POST /collections/{id}/commits?dry_run=true`` over HTTP: checked like a commit, no change."""

import hashlib
import uuid
from typing import Any

import httpx

from tests.support.api import Service
from tests.support.tusd import UploadTarget


def unhashed(base_version: int = 2, **extra: Any) -> dict[str, Any]:
    return {
        "base_version": base_version,
        "adds": [{"rel_path": "a.txt", "size": 5}],
        "removes": [],
        "host": "ws1",
        **extra,
    }


async def dry_run(target: UploadTarget, payload: Any, user: str = "dave") -> httpx.Response:
    api = target.tusd.api
    return await api.client.post(
        f"/api/v1/collections/{target.collection_id}/commits",
        params={"dry_run": "true"},
        json=payload,
        headers=await api.headers(user),
    )


async def state(api: Service, cid: str) -> tuple[int, int, int]:
    erin = await api.headers("erin")
    collection = (await api.client.get(f"/api/v1/collections/{cid}", headers=erin)).json()
    commits = (await api.client.get(f"/api/v1/collections/{cid}/commits", headers=erin)).json()
    return collection["version"], collection["file_count"], len(commits["items"])


async def test_a_dry_run_answers_the_would_be_result_without_committing(
    target: UploadTarget,
) -> None:
    api = target.tusd.api
    answer = await dry_run(target, unhashed(message="first"))
    assert answer.status_code == 200, answer.text
    assert answer.json() == {"version": 3, "file_count": 1}
    assert "ETag" not in answer.headers
    assert await state(api, target.collection_id) == (2, 0, 0)
    log = await api.client.get(
        f"/api/v1/collections/{target.collection_id}/log", headers=await api.headers("dave")
    )
    assert "collection.commit" not in [entry["action"] for entry in log.json()["items"]]


async def test_a_dry_run_may_carry_a_request_id_a_hash_and_an_upload(
    target: UploadTarget,
) -> None:
    add = {"rel_path": "a.txt", "size": 5, "sha256": "d" * 64, "upload_id": str(uuid.uuid4())}
    payload = unhashed(request_id=str(uuid.uuid4()), adds=[add])
    answer = await dry_run(target, payload)
    assert (answer.status_code, answer.json()) == (200, {"version": 3, "file_count": 1})


async def test_a_dry_run_is_refused_like_a_commit(target: UploadTarget) -> None:
    api = target.tusd.api
    reader = await dry_run(target, unhashed(), user="erin")
    assert reader.status_code == 403 and reader.json()["code"] == "FORBIDDEN"
    stale = await dry_run(target, unhashed(base_version=1))
    assert stale.status_code == 409 and stale.json()["code"] == "BASE_VERSION_CONFLICT"
    assert stale.json()["context"] == {"current_version": 2, "base_version": 1}
    malformed = await dry_run(target, {"adds": []})
    assert malformed.status_code == 422 and malformed.json()["code"] == "REQUEST_INVALID"
    bad_hash = unhashed(adds=[{"rel_path": "a.txt", "size": 5, "sha256": "X"}])
    assert (await dry_run(target, bad_hash)).json()["code"] == "REQUEST_INVALID"
    bad_path = unhashed(adds=[{"rel_path": "../a", "size": 5}])
    assert (await dry_run(target, bad_path)).json()["code"] == "COMMIT_INVALID"
    missing = await dry_run(target, {**unhashed(), "removes": ["gone.txt"]})
    assert missing.json()["code"] == "FILE_NOT_RECORDED"
    too_big = await dry_run(target, {**unhashed(), "removes": [str(i) for i in range(10_001)]})
    assert too_big.status_code == 413
    assert await state(api, target.collection_id) == (2, 0, 0)


async def test_a_dry_run_and_the_commit_agree(target: UploadTarget) -> None:
    data = b"alpha"
    upload_id = await target.tusd.begin("dave", target.collection_id, "a.txt", data)
    preview = await dry_run(target, unhashed())
    add = {
        "rel_path": "a.txt",
        "size": 5,
        "sha256": hashlib.sha256(data).hexdigest(),
        "upload_id": upload_id,
    }
    api = target.tusd.api
    committed = await api.client.post(
        f"/api/v1/collections/{target.collection_id}/commits",
        json=unhashed(request_id=str(uuid.uuid4()), adds=[add]),
        headers=await api.headers("dave"),
    )
    assert committed.status_code == 200 and committed.headers["ETag"] == '"3"'
    real = committed.json()
    assert preview.json() == {"version": real["version"], "file_count": real["file_count"]}
