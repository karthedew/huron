"""tusd's hooks over HTTP: the creation rule in ``pre-create`` and the seal in ``pre-finish``."""

import asyncio
import threading
import uuid
from pathlib import Path
from typing import Any

import pytest

from huron.applications.api.disk import SEAL_WAIT
from huron.applications.api.routes.v1.endpoints.uploads import UPLOAD_STATE_HEADER
from huron.core.storage import MARKER_FILE, FreeSpace
from huron.core.storage.posix import PosixStorage
from tests.support.api import mark_lake, seed_service, service
from tests.support.clock import LoopClock, run_ready
from tests.support.disk import SIGNAL_TIMEOUT
from tests.support.tusd import UploadTarget, problem_of, upload_target

DATA = b"solar wind, day one"
ATTEMPT = "0190d5a4-0000-7000-8000-0000000000a1"


async def attempt_of(target: UploadTarget, attempt_id: str = ATTEMPT) -> dict[str, Any]:
    """The upload attempt as its owner dave reads it."""
    api = target.tusd.api
    read = await api.client.get(
        f"/api/v1/upload-attempts/{attempt_id}", headers=await api.headers("dave")
    )
    assert read.status_code == 200, read.text
    attempt: dict[str, Any] = read.json()
    return attempt


async def created(target: UploadTarget, **options: Any) -> str:
    """The upload ID that ``pre-create`` of :data:`DATA` by dave names."""
    answer = await target.tusd.create(
        "dave", target.collection_id, "a.cdf", len(DATA), attempt_id=ATTEMPT, **options
    )
    assert answer.status_code == 200, answer.text
    upload_id: str = answer.json()["ChangeFileInfo"]["ID"]
    return upload_id


# pre-create: the six cases of the creation rule.


async def test_a_first_creation_names_the_upload_with_the_issued_id(target: UploadTarget) -> None:
    answer = await target.tusd.create(
        "dave", target.collection_id, "a.cdf", len(DATA), attempt_id=ATTEMPT
    )
    assert answer.status_code == 200
    upload_id = answer.json()["ChangeFileInfo"]["ID"]
    assert answer.json() == {"ChangeFileInfo": {"ID": upload_id}}
    attempt = await attempt_of(target)
    assert attempt == {
        "attempt_id": ATTEMPT,
        "collection_id": target.collection_id,
        "rel_path": "a.cdf",
        "size": len(DATA),
        "state": "receiving",
        "upload_id": upload_id,
        "failure": None,
    }


async def test_a_creation_with_other_fields_for_the_attempt_is_a_conflict(
    target: UploadTarget,
) -> None:
    await created(target)
    answer = await target.tusd.create(
        "dave", target.collection_id, "a.cdf", len(DATA) + 1, attempt_id=ATTEMPT
    )
    assert answer.json()["RejectUpload"] is True
    problem = problem_of(answer)
    assert (problem["status"], problem["code"]) == (409, "ATTEMPT_ID_CONFLICT")
    assert problem["context"] == {"attempt_id": ATTEMPT}


async def test_a_creation_of_an_upload_that_tusd_holds_names_the_id_to_continue(
    target: UploadTarget,
) -> None:
    upload_id = await created(target)
    target.tusd.receive(upload_id, DATA[:5])
    answer = await target.tusd.create(
        "dave", target.collection_id, "a.cdf", len(DATA), attempt_id=ATTEMPT
    )
    problem = problem_of(answer)
    assert (answer.json()["RejectUpload"], problem["status"]) == (True, 409)
    assert problem["code"] == "UPLOAD_STATE_CONFLICT"
    assert problem["context"] == {
        "attempt_id": ATTEMPT,
        "state": "receiving",
        "upload_id": upload_id,
    }
    assert problem["detail"] == f"the upload attempt is receiving. Continue upload {upload_id}"


async def test_a_creation_whose_upload_tusd_never_made_gets_a_new_id(
    target: UploadTarget,
) -> None:
    first = await created(target)
    second = await created(target)
    assert second != first
    assert (await attempt_of(target))["upload_id"] == second


async def test_a_creation_of_a_sealed_upload_names_its_state_and_id(target: UploadTarget) -> None:
    upload_id = await created(target)
    target.tusd.receive(upload_id, DATA)
    assert (await target.tusd.finish("dave", upload_id, len(DATA))).status_code == 200
    answer = await target.tusd.create(
        "dave", target.collection_id, "a.cdf", len(DATA), attempt_id=ATTEMPT
    )
    problem = problem_of(answer)
    assert (problem["status"], problem["code"]) == (409, "UPLOAD_STATE_CONFLICT")
    assert problem["context"] == {"attempt_id": ATTEMPT, "state": "ready", "upload_id": upload_id}


async def test_a_creation_of_a_cancelled_attempt_names_its_state_only(
    target: UploadTarget,
) -> None:
    upload_id = await created(target)
    api = target.tusd.api
    cancelled = await api.client.post(
        f"/api/v1/uploads/{upload_id}/cancel", headers=await api.headers("dave")
    )
    assert cancelled.status_code == 200
    answer = await target.tusd.create(
        "dave", target.collection_id, "a.cdf", len(DATA), attempt_id=ATTEMPT
    )
    problem = problem_of(answer)
    assert (problem["status"], problem["code"]) == (409, "UPLOAD_STATE_CONFLICT")
    assert problem["context"] == {"attempt_id": ATTEMPT, "state": "cancelled"}


# pre-create: the refusals.


@pytest.mark.parametrize(
    ("options", "carries"),
    [
        ({"SizeIsDeferred": True}, {"size_is_deferred": True}),
        ({"IsPartial": True}, {"is_partial": True}),
        ({"IsFinal": True}, {"is_final": True}),
        ({"header": {"Content-Length": ["5"]}}, {"carries_bytes": True}),
        (
            {"header": {"content-type": ["application/offset+octet-stream"]}},
            {"carries_bytes": True},
        ),
    ],
)
async def test_a_creation_that_is_not_one_declared_upload_without_bytes_is_refused(
    target: UploadTarget, options: dict[str, Any], carries: dict[str, bool]
) -> None:
    answer = await target.tusd.create("dave", target.collection_id, "a.cdf", 4, **options)
    problem = problem_of(answer)
    assert (answer.json()["RejectUpload"], problem["status"]) == (True, 422)
    assert problem["code"] == "REQUEST_INVALID"
    expected = {
        "size_is_deferred": False,
        "is_partial": False,
        "is_final": False,
        "carries_bytes": False,
    }
    assert problem["context"] == expected | carries


async def test_a_creation_with_an_empty_body_is_allowed(target: UploadTarget) -> None:
    upload_id = await created(target, header={"Content-Length": ["0"]})
    assert uuid.UUID(upload_id)


@pytest.mark.parametrize(
    "metadata",
    [
        {"collection": "x", "rel_path": "a", "attempt_id": ATTEMPT},
        {"rel_path": "a"},
        {"attempt_id": "not-a-uuid", "rel_path": "a"},
        {"attempt_id": ATTEMPT.upper(), "rel_path": "a"},
        {"attempt_id": ATTEMPT},
    ],
)
async def test_a_creation_without_the_attempt_the_collection_and_the_path_is_refused(
    target: UploadTarget, metadata: dict[str, str]
) -> None:
    metadata.setdefault("collection", target.collection_id)
    body = {
        "Type": "pre-create",
        "Event": {"Upload": {"ID": "", "Size": 4, "MetaData": metadata}},
    }
    problem = problem_of(await target.tusd.send("dave", body))
    assert (problem["status"], problem["code"]) == (422, "REQUEST_INVALID")
    assert problem["context"] == {"metadata": sorted(metadata)}


async def test_a_creation_without_a_token_is_refused_with_the_401_problem(
    target: UploadTarget,
) -> None:
    answer = await target.tusd.create(None, target.collection_id, "a.cdf", 4)
    assert answer.status_code == 200
    assert set(answer.json()) == {"HTTPResponse", "RejectUpload"}
    problem = problem_of(answer)
    assert (problem["status"], problem["code"], problem["instance"]) == (
        401,
        "UNAUTHENTICATED",
        "/files/",
    )


async def test_a_hook_with_an_invalid_token_is_refused_with_the_401_problem(
    target: UploadTarget,
) -> None:
    api = target.tusd.api
    body = {
        "Type": "pre-finish",
        "Event": {"Upload": {"ID": str(uuid.uuid4()), "Size": 1}},
    }
    answer = await api.client.post(
        "/api/v1/uploads/hooks", json=body, headers={"Authorization": "Bearer not-a-token"}
    )
    assert answer.status_code == 200
    assert set(answer.json()) == {"HTTPResponse"}
    problem = problem_of(answer)
    assert (problem["status"], problem["code"]) == (401, "TOKEN_INVALID")


async def test_a_creation_by_a_reader_is_refused(target: UploadTarget) -> None:
    problem = problem_of(await target.tusd.create("erin", target.collection_id, "a.cdf", 4))
    assert (problem["status"], problem["code"]) == (403, "FORBIDDEN")


async def test_a_creation_in_an_unknown_collection_is_not_found(target: UploadTarget) -> None:
    problem = problem_of(await target.tusd.create("dave", str(uuid.uuid4()), "a.cdf", 4))
    assert (problem["status"], problem["code"]) == (404, "NOT_FOUND")


async def test_a_creation_that_can_never_fit_is_too_large(lake: Path) -> None:
    async with service(lake_path=lake, max_upload_bytes=3, min_free_bytes=1 << 62) as api:
        target = await upload_target(await seed_service(api), lake)
        problem = problem_of(await target.tusd.create("dave", target.collection_id, "a", 4))
    assert (problem["status"], problem["code"]) == (413, "UPLOAD_TOO_LARGE")
    assert problem["context"] == {"size": 4, "maximum": 3}


async def test_a_creation_without_free_space_is_refused(lake: Path) -> None:
    async with service(lake_path=lake, min_free_bytes=1 << 62) as api:
        target = await upload_target(await seed_service(api), lake)
        answer = await target.tusd.create("dave", target.collection_id, "a", 4)
    problem = problem_of(answer)
    assert (problem["status"], problem["code"]) == (429, "CAPACITY_EXCEEDED")
    assert problem["context"]["limit"] == "min_free_bytes"
    assert problem["context"]["requested"] == 8
    assert "two times its size" in problem["detail"]


async def test_a_resume_and_a_refusal_need_no_free_space(
    target: UploadTarget, monkeypatch: pytest.MonkeyPatch
) -> None:
    upload_id = await created(target)
    target.tusd.receive(upload_id, DATA[:3])
    monkeypatch.setattr(PosixStorage, "free_space", lambda self, location: FreeSpace(1, 0))
    resumed = await target.tusd.create(
        "dave", target.collection_id, "a.cdf", len(DATA), attempt_id=ATTEMPT
    )
    assert problem_of(resumed)["code"] == "UPLOAD_STATE_CONFLICT"
    conflict = await target.tusd.create(
        "dave", target.collection_id, "a.cdf", 1, attempt_id=ATTEMPT
    )
    assert problem_of(conflict)["code"] == "ATTEMPT_ID_CONFLICT"
    new = await target.tusd.create("dave", target.collection_id, "b.cdf", 1)
    assert problem_of(new)["code"] == "CAPACITY_EXCEEDED"


async def test_the_upload_routes_need_a_lake() -> None:
    async with service() as api:
        headers = await api.headers("dave")
        answers = [
            await api.client.post(
                "/api/v1/uploads/hooks",
                json={"Type": "pre-create", "Event": {"Upload": {}}},
                headers=headers,
            ),
            await api.client.post(f"/api/v1/uploads/{uuid.uuid4()}/cancel", headers=headers),
        ]
    for answer in answers:
        assert (answer.status_code, answer.json()["code"]) == (404, "UPLOADS_DISABLED")


async def test_a_hook_that_tusd_does_not_send_is_refused_as_invalid(target: UploadTarget) -> None:
    body = {"Type": "post-finish", "Event": {"Upload": {"ID": str(uuid.uuid4())}}}
    answer = await target.tusd.send("dave", body)
    assert (answer.status_code, answer.json()["code"]) == (422, "REQUEST_INVALID")


# pre-finish.


async def test_the_finish_of_a_complete_upload_answers_that_it_is_ready(
    target: UploadTarget, lake: Path
) -> None:
    upload_id = await target.tusd.begin(
        "dave", target.collection_id, "a.cdf", DATA, attempt_id=ATTEMPT
    )
    answer = await target.tusd.finish("dave", upload_id, len(DATA))
    assert answer.status_code == 200
    assert answer.json() == {"HTTPResponse": {"Header": {UPLOAD_STATE_HEADER: "ready"}}}
    assert (await attempt_of(target))["state"] == "ready"
    assert (lake / "helio" / ".huron-objects" / upload_id).read_bytes() == DATA


async def test_the_finish_answers_sealing_after_the_wait_and_the_seal_goes_on(
    target: UploadTarget,
    paused_copy: tuple[threading.Event, threading.Event],
    loop_clock: LoopClock,
) -> None:
    copying, release = paused_copy
    upload_id = await target.tusd.begin(
        "dave", target.collection_id, "a.cdf", DATA, attempt_id=ATTEMPT
    )
    finishing = asyncio.create_task(target.tusd.finish("dave", upload_id, len(DATA)))
    assert await asyncio.to_thread(copying.wait, SIGNAL_TIMEOUT)
    loop_clock.advance(SEAL_WAIT - 0.001)
    await asyncio.sleep(0)
    assert not finishing.done()
    loop_clock.advance(0.001)
    answer = await asyncio.wait_for(finishing, SIGNAL_TIMEOUT)
    assert answer.json() == {"HTTPResponse": {"Header": {UPLOAD_STATE_HEADER: "sealing"}}}
    release.set()
    orchestration = target.tusd.api.runtime.orchestration
    assert orchestration is not None
    sealed = await asyncio.wait_for(orchestration.sealing.start(uuid.UUID(upload_id)), 5)
    assert sealed.state.value == "ready"


async def test_the_finish_of_a_seal_that_ends_within_the_wait_answers_ready(
    target: UploadTarget,
    paused_copy: tuple[threading.Event, threading.Event],
    loop_clock: LoopClock,
) -> None:
    copying, release = paused_copy
    upload_id = await target.tusd.begin(
        "dave", target.collection_id, "a.cdf", DATA, attempt_id=ATTEMPT
    )
    finishing = asyncio.create_task(target.tusd.finish("dave", upload_id, len(DATA)))
    assert await asyncio.to_thread(copying.wait, SIGNAL_TIMEOUT)
    loop_clock.advance(SEAL_WAIT - 0.001)
    release.set()
    answer = await asyncio.wait_for(finishing, SIGNAL_TIMEOUT)
    assert answer.json() == {"HTTPResponse": {"Header": {UPLOAD_STATE_HEADER: "ready"}}}


async def test_the_attempt_read_answers_sealing_after_the_wait_and_the_seal_goes_on(
    target: UploadTarget,
    paused_copy: tuple[threading.Event, threading.Event],
    loop_clock: LoopClock,
) -> None:
    copying, release = paused_copy
    upload_id = await target.tusd.begin(
        "dave", target.collection_id, "a.cdf", DATA, attempt_id=ATTEMPT
    )
    reading = asyncio.create_task(attempt_of(target))
    assert await asyncio.to_thread(copying.wait, SIGNAL_TIMEOUT)
    loop_clock.advance(SEAL_WAIT - 0.001)
    await run_ready()
    assert not reading.done()
    loop_clock.advance(0.001)
    await run_ready()
    assert reading.done()
    assert reading.result()["state"] == "sealing"
    orchestration = target.tusd.api.runtime.orchestration
    assert orchestration is not None
    assert orchestration.sealing.running(uuid.UUID(upload_id))
    release.set()
    sealed = await asyncio.wait_for(orchestration.sealing.start(uuid.UUID(upload_id)), 5)
    assert sealed.state.value == "ready"


async def test_the_attempt_read_of_a_seal_that_ends_within_the_wait_answers_ready(
    target: UploadTarget,
    paused_copy: tuple[threading.Event, threading.Event],
    loop_clock: LoopClock,
) -> None:
    copying, release = paused_copy
    await target.tusd.begin("dave", target.collection_id, "a.cdf", DATA, attempt_id=ATTEMPT)
    reading = asyncio.create_task(attempt_of(target))
    assert await asyncio.to_thread(copying.wait, SIGNAL_TIMEOUT)
    loop_clock.advance(SEAL_WAIT - 0.001)
    await run_ready()
    release.set()
    assert (await asyncio.wait_for(reading, SIGNAL_TIMEOUT))["state"] == "ready"


async def test_the_finish_of_an_upload_of_another_size_fails_its_attempt(
    target: UploadTarget,
) -> None:
    upload_id = await created(target)
    target.tusd.receive(upload_id, DATA + b"!")
    answer = await target.tusd.finish("dave", upload_id, len(DATA) + 1)
    assert "RejectUpload" not in answer.json()
    problem = problem_of(answer)
    assert (problem["status"], problem["code"]) == (422, "UPLOAD_SIZE_MISMATCH")
    assert problem["context"] == {"upload": upload_id}
    attempt = await attempt_of(target)
    assert attempt["state"] == "failed"
    assert attempt["failure"]["code"] == "UPLOAD_SIZE_MISMATCH"


async def test_the_finish_of_an_id_that_is_not_current_is_refused(target: UploadTarget) -> None:
    first = await created(target)
    await created(target)
    target.tusd.receive(first, DATA)
    problem = problem_of(await target.tusd.finish("dave", first, len(DATA)))
    assert (problem["status"], problem["code"]) == (409, "UPLOAD_INELIGIBLE")
    assert problem["context"] == {"upload_id": first, "state": "receiving", "reason": "superseded"}


async def test_the_finish_of_a_cancelled_upload_is_refused(target: UploadTarget) -> None:
    upload_id = await created(target)
    api = target.tusd.api
    await api.client.post(f"/api/v1/uploads/{upload_id}/cancel", headers=await api.headers("dave"))
    target.tusd.receive(upload_id, DATA)
    problem = problem_of(await target.tusd.finish("dave", upload_id, len(DATA)))
    assert (problem["status"], problem["code"]) == (409, "UPLOAD_INELIGIBLE")
    assert problem["context"] == {"upload_id": upload_id, "state": "cancelled", "reason": "state"}


async def test_the_finish_of_another_users_upload_is_not_found(target: UploadTarget) -> None:
    upload_id = await target.tusd.begin("dave", target.collection_id, "a.cdf", DATA)
    problem = problem_of(await target.tusd.finish("frank", upload_id, len(DATA)))
    assert (problem["status"], problem["code"]) == (404, "UPLOAD_NOT_FOUND")
    for named in ("not-an-id", upload_id.upper()):
        problem = problem_of(await target.tusd.finish("dave", named, len(DATA)))
        assert (problem["status"], problem["code"]) == (422, "REQUEST_INVALID")


async def test_a_finish_that_the_lake_refuses_is_an_http_error_for_tusd_to_retry(
    target: UploadTarget, lake: Path
) -> None:
    upload_id = await target.tusd.begin("dave", target.collection_id, "a.cdf", DATA)
    (lake / MARKER_FILE).unlink()
    answer = await target.tusd.finish("dave", upload_id, len(DATA))
    assert (answer.status_code, answer.json()["code"]) == (503, "LAKE_UNAVAILABLE")
    runtime = target.tusd.api.runtime
    assert (await runtime.attempts.find(uuid.UUID(upload_id))).state.value == "receiving"
    assert (target.tusd.upload_dir / upload_id).read_bytes() == DATA
    mark_lake(lake)
    retried = await target.tusd.finish("dave", upload_id, len(DATA))
    assert retried.json() == {"HTTPResponse": {"Header": {UPLOAD_STATE_HEADER: "ready"}}}


async def test_an_empty_upload_is_sealed_with_the_hash_of_no_bytes(
    target: UploadTarget, lake: Path
) -> None:
    upload_id = await target.tusd.begin("dave", target.collection_id, "empty.bin", b"")
    answer = await target.tusd.finish("dave", upload_id, 0)
    assert answer.json() == {"HTTPResponse": {"Header": {UPLOAD_STATE_HEADER: "ready"}}}
    assert (lake / "helio" / ".huron-objects" / upload_id).read_bytes() == b""
    sealed = await target.tusd.api.runtime.attempts.find(uuid.UUID(upload_id))
    assert (sealed.state.value, sealed.size) == ("ready", 0)


async def test_a_repeated_finish_of_a_sealed_upload_answers_ready_and_copies_nothing(
    target: UploadTarget, lake: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    upload_id = await target.tusd.begin("dave", target.collection_id, "a.cdf", DATA)
    assert (await target.tusd.finish("dave", upload_id, len(DATA))).status_code == 200
    copies: list[object] = []
    real = PosixStorage.copy_sealed

    def counted(self: PosixStorage, *args: Any, **kwargs: Any) -> Any:
        copies.append(args)
        return real(self, *args, **kwargs)

    monkeypatch.setattr(PosixStorage, "copy_sealed", counted)
    again = await target.tusd.finish("dave", upload_id, len(DATA))
    assert again.json() == {"HTTPResponse": {"Header": {UPLOAD_STATE_HEADER: "ready"}}}
    assert copies == []
    assert (lake / "helio" / ".huron-objects" / upload_id).read_bytes() == DATA
