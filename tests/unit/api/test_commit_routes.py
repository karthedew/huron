"""The commit route, the state of a commit request and the operator's resolution, over HTTP."""

import asyncio
import hashlib
import threading
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from huron.applications.api.disk import PUBLISH_WAIT, SEAL_WAIT
from huron.core.storage import MARKER_FILE
from huron.core.storage.posix import PosixStorage
from tests.support.api import Service, mark_lake, seed_service, service
from tests.support.clock import LoopClock, run_ready
from tests.support.disk import SIGNAL_TIMEOUT
from tests.support.lake import CONTRIBUTOR
from tests.support.postgres import empty_store
from tests.support.tusd import UploadTarget, upload_target

WIND, SUN = b"solar wind", b"sunspots"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def sealed(target: UploadTarget, rel_path: str, data: bytes, user: str = "dave") -> str:
    """The upload ID of a ready upload of ``data`` to ``rel_path``, through tusd's hooks."""
    upload_id = await target.tusd.begin(user, target.collection_id, rel_path, data)
    finished = await target.tusd.finish(user, upload_id, len(data))
    assert finished.json()["HTTPResponse"]["Header"]["Huron-Upload-State"] == "ready"
    return upload_id


def body(
    base_version: int,
    adds: list[tuple[str, bytes, str]] | None = None,
    removes: list[str] | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    return {
        "request_id": request_id or str(uuid.uuid4()),
        "base_version": base_version,
        "adds": [
            {"rel_path": path, "size": len(data), "sha256": sha(data), "upload_id": upload_id}
            for path, data, upload_id in adds or []
        ],
        "removes": removes or [],
        "host": "ws1",
        "message": "a test commit",
    }


async def post(target: UploadTarget, payload: dict[str, Any], user: str = "dave") -> httpx.Response:
    api = target.tusd.api
    return await api.client.post(
        f"/api/v1/collections/{target.collection_id}/commits",
        json=payload,
        headers=await api.headers(user),
    )


async def status(api: Service, request_id: str, user: str = "dave") -> httpx.Response:
    return await api.client.get(
        f"/api/v1/commit-requests/{request_id}", headers=await api.headers(user)
    )


async def published(target: UploadTarget, request_id: str) -> str:
    """The state of dave's request once its running publication task ended."""
    runtime = target.tusd.api.runtime
    assert runtime.orchestration is not None
    outcome = await runtime.publications.status(CONTRIBUTOR, uuid.UUID(request_id))
    task = runtime.orchestration.materializer.start(outcome)
    return str((await asyncio.wait_for(task, SIGNAL_TIMEOUT)).state)


async def collection(target: UploadTarget) -> dict[str, Any]:
    api = target.tusd.api
    answer = await api.client.get(
        f"/api/v1/collections/{target.collection_id}", headers=await api.headers("erin")
    )
    found: dict[str, Any] = answer.json()
    return found


async def test_a_commit_that_succeeds_answers_200_with_its_outcome(target: UploadTarget) -> None:
    upload_id = await sealed(target, "wind/a.txt", WIND)
    payload = body(target.version, [("wind/a.txt", WIND, upload_id)])
    answer = await post(target, payload)
    assert answer.status_code == 200, answer.text
    outcome = answer.json()
    assert outcome == {
        "request_id": payload["request_id"],
        "state": "succeeded",
        "collection_id": target.collection_id,
        "version": 3,
        "file_count": 1,
        "commit_id": outcome["commit_id"],
        "refusal": None,
    }
    assert answer.headers["ETag"] == '"3"'
    assert (target.directory / "wind" / "a.txt").read_bytes() == WIND
    found = await collection(target)
    assert (found["version"], found["file_count"], found["pending_request"]) == (3, 1, None)
    again = await post(target, payload)
    assert (again.status_code, again.json()) == (200, outcome)
    assert (await status(target.tusd.api, payload["request_id"])).json() == outcome


async def test_a_removal_only_commit_removes_the_file(target: UploadTarget) -> None:
    upload_id = await sealed(target, "a.txt", WIND)
    assert (await post(target, body(2, [("a.txt", WIND, upload_id)]))).status_code == 200
    answer = await post(target, body(3, removes=["a.txt"]))
    assert answer.status_code == 200
    assert answer.json()["file_count"] == 0
    assert not (target.directory / "a.txt").exists()


@pytest.fixture
async def paused(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[threading.Event, threading.Event]]:
    """The first publication link waits until the second event is set; the first is set then."""
    linking, release = threading.Event(), threading.Event()
    real = PosixStorage.link_once

    def paused_link(self: PosixStorage, *args: Any, **kwargs: Any) -> Any:
        linking.set()
        assert release.wait(SIGNAL_TIMEOUT)
        return real(self, *args, **kwargs)

    monkeypatch.setattr(PosixStorage, "link_once", paused_link)
    yield linking, release
    release.set()


async def test_a_commit_that_does_not_end_in_five_seconds_answers_202_with_its_state(
    target: UploadTarget,
    paused: tuple[threading.Event, threading.Event],
    loop_clock: LoopClock,
) -> None:
    linking, release = paused
    upload_id = await sealed(target, "a.txt", WIND)
    payload = body(2, [("a.txt", WIND, upload_id)])
    sending = asyncio.create_task(post(target, payload))
    assert await asyncio.to_thread(linking.wait, SIGNAL_TIMEOUT)
    loop_clock.advance(PUBLISH_WAIT - 0.001)
    await asyncio.sleep(0)
    assert not sending.done()
    loop_clock.advance(0.001)
    answer = await asyncio.wait_for(sending, SIGNAL_TIMEOUT)
    assert answer.status_code == 202
    assert answer.headers["Location"] == f"/api/v1/commit-requests/{payload['request_id']}"
    assert "ETag" not in answer.headers
    assert answer.json()["state"] == "accepted"
    pending = await collection(target)
    assert pending["version"] == 2
    assert pending["pending_request"]["state"] == "accepted"
    release.set()
    assert await published(target, payload["request_id"]) == "succeeded"
    assert (await collection(target))["pending_request"] is None


async def test_the_state_of_a_request_is_for_its_creator_only(target: UploadTarget) -> None:
    upload_id = await sealed(target, "a.txt", WIND)
    payload = body(2, [("a.txt", WIND, upload_id)])
    await post(target, payload)
    api = target.tusd.api
    for request_id, user in ((payload["request_id"], "frank"), (str(uuid.uuid4()), "dave")):
        answer = await status(api, request_id, user)
        assert (answer.status_code, answer.json()["code"]) == (404, "COMMIT_REQUEST_NOT_FOUND")
        assert answer.json()["context"] == {"request_id": request_id}


async def test_a_refused_commit_keeps_its_refusal_for_its_request_id(target: UploadTarget) -> None:
    upload_id = await sealed(target, "a.txt", WIND)
    payload = body(1, [("a.txt", WIND, upload_id)])
    answer = await post(target, payload)
    assert (answer.status_code, answer.json()["code"]) == (409, "BASE_VERSION_CONFLICT")
    assert answer.json()["context"] == {"current_version": 2, "base_version": 1}
    again = await post(target, payload)
    assert (again.status_code, again.json()) == (409, answer.json())
    saved = (await status(target.tusd.api, payload["request_id"])).json()
    assert saved["state"] == "rejected"
    assert saved["refusal"] == {
        "code": "BASE_VERSION_CONFLICT",
        "detail": answer.json()["detail"],
        "context": {"current_version": 2, "base_version": 1},
    }


async def test_a_request_id_with_another_body_is_a_conflict(target: UploadTarget) -> None:
    payload = body(2)
    assert (await post(target, payload)).status_code == 200
    answer = await post(target, {**payload, "host": "ws2"})
    assert (answer.status_code, answer.json()["code"]) == (409, "REQUEST_ID_CONFLICT")


async def test_a_commit_on_a_busy_collection_is_refused(
    target: UploadTarget,
    paused: tuple[threading.Event, threading.Event],
    loop_clock: LoopClock,
) -> None:
    linking, release = paused
    upload_id = await sealed(target, "a.txt", WIND)
    other = await sealed(target, "b.txt", SUN)
    first = asyncio.create_task(post(target, body(2, [("a.txt", WIND, upload_id)])))
    assert await asyncio.to_thread(linking.wait, SIGNAL_TIMEOUT)
    loop_clock.advance(PUBLISH_WAIT)
    assert (await asyncio.wait_for(first, SIGNAL_TIMEOUT)).status_code == 202
    answer = await post(target, body(2, [("b.txt", SUN, other)]))
    assert (answer.status_code, answer.json()["code"]) == (409, "COLLECTION_BUSY")
    release.set()


async def test_a_commit_seals_an_upload_that_no_hook_reported(target: UploadTarget) -> None:
    upload_id = await target.tusd.begin("dave", target.collection_id, "a.txt", WIND)
    answer = await post(target, body(2, [("a.txt", WIND, upload_id)]))
    assert answer.status_code == 200, answer.text
    assert (target.directory / "a.txt").read_bytes() == WIND


async def test_a_commit_whose_seal_goes_on_after_the_wait_is_ineligible_while_sealing(
    target: UploadTarget,
    paused_copy: tuple[threading.Event, threading.Event],
    loop_clock: LoopClock,
) -> None:
    copying, release = paused_copy
    upload_id = await target.tusd.begin("dave", target.collection_id, "a.txt", WIND)
    sending = asyncio.create_task(post(target, body(2, [("a.txt", WIND, upload_id)])))
    assert await asyncio.to_thread(copying.wait, SIGNAL_TIMEOUT)
    loop_clock.advance(SEAL_WAIT - 0.001)
    await run_ready()
    assert not sending.done()
    loop_clock.advance(0.001)
    await run_ready()
    assert sending.done()
    answer = sending.result()
    assert (answer.status_code, answer.json()["code"]) == (409, "UPLOAD_INELIGIBLE")
    assert answer.json()["context"] == {
        "upload_id": upload_id,
        "state": "sealing",
        "reason": "state",
    }
    orchestration = target.tusd.api.runtime.orchestration
    assert orchestration is not None
    assert orchestration.sealing.running(uuid.UUID(upload_id))
    release.set()
    seal = orchestration.sealing.start(uuid.UUID(upload_id))
    assert (await asyncio.wait_for(seal, SIGNAL_TIMEOUT)).state.value == "ready"
    assert not (target.directory / "a.txt").exists()


async def test_a_commit_of_an_upload_that_is_still_receiving_is_ineligible(
    target: UploadTarget,
) -> None:
    created = await target.tusd.create("dave", target.collection_id, "a.txt", len(WIND))
    upload_id = created.json()["ChangeFileInfo"]["ID"]
    target.tusd.receive(upload_id, WIND, locked=True)
    answer = await post(target, body(2, [("a.txt", WIND, upload_id)]))
    assert (answer.status_code, answer.json()["code"]) == (409, "UPLOAD_INELIGIBLE")
    assert answer.json()["context"] == {
        "upload_id": upload_id,
        "state": "receiving",
        "reason": "state",
    }


async def test_a_commit_of_a_cancelled_upload_says_to_start_a_new_upload(
    target: UploadTarget,
) -> None:
    upload_id = await sealed(target, "a.txt", WIND)
    api = target.tusd.api
    await api.client.post(f"/api/v1/uploads/{upload_id}/cancel", headers=await api.headers("dave"))
    answer = await post(target, body(2, [("a.txt", WIND, upload_id)]))
    assert (answer.status_code, answer.json()["code"]) == (409, "UPLOAD_INELIGIBLE")
    assert "Start a new upload of the file with a new attempt_id" in answer.json()["detail"]


async def test_a_commit_whose_hash_is_not_the_sealed_hash_is_ineligible(
    target: UploadTarget,
) -> None:
    upload_id = await sealed(target, "a.txt", WIND)
    payload = body(2, [("a.txt", WIND, upload_id)])
    payload["adds"][0]["sha256"] = sha(SUN)
    answer = await post(target, payload)
    assert answer.json()["context"]["reason"] == "different_file"
    assert not (target.directory / "a.txt").exists()


async def test_the_old_body_is_refused(target: UploadTarget) -> None:
    old = {
        "base_version": 2,
        "adds": [{"rel_path": "a.txt", "size": 5, "sha256": sha(b"x")}],
        "removes": [],
        "host": "ws1",
    }
    answer = await post(target, old)
    assert (answer.status_code, answer.json()["code"]) == (422, "REQUEST_INVALID")
    assert answer.json()["context"] == {"missing": ["/request_id", "/adds/0/upload_id"]}
    unknown = await post(target, {**old, "extra": 1})
    assert (unknown.status_code, unknown.json()["code"]) == (422, "REQUEST_INVALID")


@pytest.mark.parametrize("base_version", [-1, 2**31])
async def test_a_base_version_outside_the_column_is_a_validation_error(
    target: UploadTarget, base_version: int
) -> None:
    answer = await post(target, body(base_version))
    assert (answer.status_code, answer.json()["code"]) == (422, "REQUEST_INVALID")
    assert [problem["path"] for problem in answer.json()["context"]["problems"]] == [
        "/body/base_version"
    ]


async def test_a_commit_of_more_than_ten_thousand_entries_is_too_large(
    target: UploadTarget,
) -> None:
    answer = await post(target, body(2, removes=[f"f{index}" for index in range(10_001)]))
    assert (answer.status_code, answer.json()["code"]) == (413, "COMMIT_TOO_LARGE")


async def test_a_commit_needs_a_lake(seeded_api: Service) -> None:
    answer = await seeded_api.client.post(
        f"/api/v1/collections/{uuid.uuid4()}/commits",
        json=body(2),
        headers=await seeded_api.headers("dave"),
    )
    assert (answer.status_code, answer.json()["code"]) == (404, "UPLOADS_DISABLED")


async def test_a_commit_in_a_process_that_is_not_the_writer_is_unavailable(
    target: UploadTarget,
) -> None:
    orchestration = target.tusd.api.runtime.orchestration
    assert orchestration is not None
    await orchestration.ownership.close()
    answer = await post(target, body(2))
    assert (answer.status_code, answer.json()["code"]) == (503, "LAKE_UNAVAILABLE")
    assert answer.json()["context"] == {"reason": "writer_lock"}


async def blocked(target: UploadTarget, lake: Path) -> tuple[str, str]:
    """A commit request that a foreign file blocks; its request ID and its upload ID."""
    upload_id = await sealed(target, "a.txt", WIND)
    (target.directory / "a.txt").write_bytes(b"foreign")
    payload = body(2, [("a.txt", WIND, upload_id)])
    answer = await post(target, payload)
    assert answer.status_code == 202
    assert answer.json()["state"] == "blocked"
    assert answer.json()["refusal"]["code"] == "PUBLICATION_BLOCKED"
    return payload["request_id"], upload_id


async def resolve(target: UploadTarget, resolution: str, user: str = "alice") -> httpx.Response:
    api = target.tusd.api
    return await api.client.post(
        f"/api/v1/admin/collections/{target.collection_id}/pending-request",
        json={"resolution": resolution},
        headers=await api.headers(user),
    )


async def test_an_operator_abandons_a_blocked_request_and_the_upload_is_ready_again(
    target: UploadTarget, lake: Path
) -> None:
    request_id, upload_id = await blocked(target, lake)
    assert (await collection(target))["pending_request"]["state"] == "blocked"
    refused = await resolve(target, "abandon", user="carol")
    assert (refused.status_code, refused.json()["code"]) == (403, "FORBIDDEN")
    answer = await resolve(target, "abandon")
    assert answer.status_code == 200
    assert (answer.json()["request_id"], answer.json()["state"]) == (request_id, "abandoned")
    assert (await collection(target))["pending_request"] is None
    again = await post(target, body(2, [("a.txt", WIND, upload_id)], request_id=request_id))
    assert (again.status_code, again.json()["code"]) == (409, "STATE_CONFLICT")
    assert again.json()["context"] == {"request_id": request_id, "state": "abandoned"}
    nothing = await resolve(target, "retry")
    assert (nothing.status_code, nothing.json()["code"]) == (404, "NOT_FOUND")


async def test_an_operator_retries_a_blocked_request_after_the_foreign_file_is_gone(
    target: UploadTarget, lake: Path
) -> None:
    request_id, _ = await blocked(target, lake)
    (target.directory / "a.txt").unlink()
    answer = await resolve(target, "retry")
    assert (answer.status_code, answer.json()["state"]) == (200, "accepted")
    assert await published(target, request_id) == "succeeded"
    assert (target.directory / "a.txt").read_bytes() == WIND


async def test_a_resolution_needs_the_writer_and_a_known_resolution(
    target: UploadTarget, lake: Path
) -> None:
    unknown = await resolve(target, "ignore")
    assert (unknown.status_code, unknown.json()["code"]) == (422, "REQUEST_INVALID")
    orchestration = target.tusd.api.runtime.orchestration
    assert orchestration is not None
    await orchestration.ownership.close()
    refused = await resolve(target, "retry", user="carol")
    assert (refused.status_code, refused.json()["code"]) == (403, "FORBIDDEN")
    answer = await resolve(target, "retry")
    assert (answer.status_code, answer.json()["code"]) == (503, "LAKE_UNAVAILABLE")


async def test_a_commit_that_the_lake_refuses_stays_accepted(
    target: UploadTarget, lake: Path
) -> None:
    upload_id = await sealed(target, "a.txt", WIND)
    (lake / MARKER_FILE).unlink()
    payload = body(2, [("a.txt", WIND, upload_id)])
    answer = await post(target, payload)
    assert (answer.status_code, answer.json()["state"]) == (202, "accepted")
    mark_lake(lake)
    retried = await post(target, payload)
    assert (retried.status_code, retried.json()["state"]) == (200, "succeeded")


@pytest.fixture(params=["memory", pytest.param("postgres", marks=pytest.mark.contract)])
def database(request: pytest.FixtureRequest) -> str | None:
    """``None`` for the in-memory store, the URL of a migrated database for PostgreSQL."""
    if request.param == "memory":
        return None
    url: str = request.getfixturevalue("database_url")
    return url


@pytest.fixture
async def any_store_target(database: str | None, lake: Path) -> AsyncIterator[UploadTarget]:
    """Collection ``run7`` of a seeded service with a lake, over each store."""
    if database is None:
        async with service(lake_path=lake) as api:
            yield await upload_target(await seed_service(api), lake)
        return
    async with empty_store(database) as store, service(store=store, lake_path=lake) as api:
        yield await upload_target(await seed_service(api), lake)


async def test_a_commit_seals_only_the_callers_own_unsealed_uploads(
    any_store_target: UploadTarget, lake: Path
) -> None:
    target = any_store_target
    foreign = await target.tusd.begin("frank", target.collection_id, "f.txt", SUN)
    own = await target.tusd.begin("dave", target.collection_id, "a.txt", WIND)
    payload = body(2, [("f.txt", SUN, foreign)])
    answer = await post(target, payload)
    assert (answer.status_code, answer.json()["code"]) == (404, "UPLOAD_NOT_FOUND")
    assert answer.json()["context"] == {"upload": foreign}
    runtime = target.tusd.api.runtime
    assert (await runtime.attempts.find(uuid.UUID(foreign))).state.value == "receiving"
    assert not (lake / "helio" / ".huron-objects" / foreign).exists()
    committed = await post(target, body(2, [("a.txt", WIND, own)]))
    assert committed.status_code == 200, committed.text
    assert (await runtime.attempts.find(uuid.UUID(own))).state.value == "consumed"
    assert (lake / "helio" / ".huron-objects" / own).exists()
