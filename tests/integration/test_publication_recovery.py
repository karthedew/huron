"""Recovery of seals and commits after a kill of the API, on the real application.

Each test runs the API in a child process over PostgreSQL and a temporary lake. The test plays
tusd: it writes the upload files and sends the hooks. It kills the child with ``SIGKILL`` at a
named point, starts a new child, sends the same request again, and reads the files, the rows
and the saved outcome.

The collection starts at version 3 with ``a.txt``, ``b.txt`` and ``c.txt``. A seal case
replaces ``a.txt``. A publication case replaces ``a.txt`` and ``b.txt`` and removes ``c.txt``
in one commit, so its entries are one unlink, then two links and renames.
"""

import asyncio
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest

from huron.applications.api.routes.v1.endpoints.uploads import UPLOAD_STATE_HEADER
from huron.schema.naming import METADATA_FILE
from tests.support.api import active_collection, seed_service
from tests.support.crash import (
    Action,
    Arm,
    ChildApi,
    Phase,
    Point,
    object_count,
    read_facts,
    until,
)
from tests.support.publication import sha256
from tests.support.tusd import HOOKS, FakeTusd, hook_body, problem_of, upload_body

pytestmark = pytest.mark.integration

OLD = {"a.txt": b"a, first version", "b.txt": b"b, first version", "c.txt": b"c, first version"}
NEW_A = b"a, second version"
NEW_B = b"b, second version, with more bytes"
LATE = b"bytes that tusd completes late"

#: The version of the collection before the commit of a test, and after it.
BASE, NEXT = 3, 4

#: The files after a seal case and after a publication case.
SEALED_FILES = {**OLD, "a.txt": NEW_A}
PUBLISHED_FILES = {"a.txt": NEW_A, "b.txt": NEW_B}

#: Seconds that tusd waits for the pre-finish hook in the case where the hook gets no answer.
HOOK_TIMEOUT = 2.0

#: Each kill point with the call at which the child stops: the seals first, then the
#: publication of the commit, whose entries are the unlink of c.txt (done as entry 1), the add
#: of a.txt (entry 2) and the add of b.txt (entry 3).
SEAL_KILLS = [(Point.COPY, 1), (Point.SEAL_COMMIT, 1)]
PUBLICATION_KILLS = [
    (Point.ACCEPTANCE, 1),
    (Point.UNLINK, 1),
    (Point.LINK, 1),
    (Point.RENAME, 1),
    (Point.ENTRY_DONE, 2),
    (Point.FINAL, 1),
]


@dataclass(frozen=True)
class Scene:
    """The child API, collection ``run7`` at version 3 with :data:`OLD`, its directory and the
    lake path of the directory, and tusd in front of the child.
    """

    api: ChildApi
    collection_id: str
    directory: Path
    scope: str
    tusd: FakeTusd[ChildApi]


@pytest.fixture
async def scene(child_api: ChildApi) -> Scene:
    """The seeded child API with collection ``run7`` at version 3 that holds :data:`OLD`."""
    await seed_service(child_api)
    collection = await active_collection(child_api)
    path: str = collection["path"]
    tusd = FakeTusd(child_api, child_api.lake)
    found = Scene(
        child_api, collection["id"], child_api.lake.joinpath(*path.split("/")), path, tusd
    )
    adds = [(name, data, await ready_upload(found, name, data)) for name, data in OLD.items()]
    answer = await commit(found, commit_body(BASE - 1, adds))
    assert answer.status_code == 200, answer.text
    return found


@pytest.mark.parametrize("phase", list(Phase))
@pytest.mark.parametrize(("point", "nth"), SEAL_KILLS)
async def test_a_kill_during_a_seal_is_recovered_by_the_attempt_read(
    scene: Scene, point: Point, nth: int, phase: Phase
) -> None:
    attempt_id = str(uuid.uuid4())
    arm = Arm(point, phase, nth)
    scene.api.arm(arm)
    upload_id = await scene.tusd.begin(
        "dave", scene.collection_id, "a.txt", NEW_A, attempt_id=attempt_id
    )
    reading = asyncio.create_task(attempt_read(scene, attempt_id))
    assert await scene.api.stopped() == arm
    await scene.api.restart(reading)
    attempt = (await attempt_read(scene, attempt_id)).json()
    assert (attempt["state"], attempt["upload_id"]) == ("ready", upload_id)
    assert await object_count(scene.api.database_url, upload_id) == 1
    body = commit_body(BASE, [("a.txt", NEW_A, upload_id)])
    answer = await commit(scene, body)
    assert answer.status_code == 200, answer.text
    await assert_published(scene, body, SEALED_FILES)


@pytest.mark.parametrize("phase", list(Phase))
@pytest.mark.parametrize(("point", "nth"), PUBLICATION_KILLS)
async def test_a_kill_during_a_two_file_replace_with_one_remove_is_recovered(
    scene: Scene, point: Point, nth: int, phase: Phase
) -> None:
    body = await replace_two_remove_one(scene)
    arm = Arm(point, phase, nth, scope=scene.scope)
    scene.api.arm(arm)
    posting = asyncio.create_task(commit(scene, body))
    assert await scene.api.stopped() == arm
    await scene.api.restart(posting)
    if point is Point.ACCEPTANCE and phase is Phase.BEFORE:
        # Nothing was saved, so the request sent again is a new request.
        assert (await status(scene, body["request_id"])).status_code == 404
        assert (await commit(scene, body)).status_code == 200
    else:
        # The new process continues the accepted request on its own.
        await succeeded(scene, body["request_id"])
    await assert_published(scene, body, PUBLISHED_FILES)


async def test_a_kill_of_the_api_during_the_pre_finish_hook_is_recovered_by_the_attempt_read(
    scene: Scene,
) -> None:
    attempt_id = str(uuid.uuid4())
    arm = Arm(Point.COPY, Phase.AFTER)
    scene.api.arm(arm)
    upload_id = await scene.tusd.begin(
        "dave", scene.collection_id, "a.txt", NEW_A, attempt_id=attempt_id
    )
    finishing = asyncio.create_task(scene.tusd.finish("dave", upload_id, len(NEW_A)))
    assert await scene.api.stopped() == arm
    await scene.api.restart(finishing)
    attempt = (await attempt_read(scene, attempt_id)).json()
    assert (attempt["state"], attempt["upload_id"]) == ("ready", upload_id)
    assert await object_count(scene.api.database_url, upload_id) == 1
    body = commit_body(BASE, [("a.txt", NEW_A, upload_id)])
    assert (await commit(scene, body)).status_code == 200
    await scene.api.restart()
    await assert_published(scene, body, SEALED_FILES)


async def test_a_pre_finish_hook_that_answers_500_leaves_the_seal_to_the_attempt_read(
    scene: Scene,
) -> None:
    attempt_id = str(uuid.uuid4())
    scene.api.arm(Arm(Point.COPY, action=Action.FAIL))
    upload_id = await scene.tusd.begin(
        "dave", scene.collection_id, "a.txt", NEW_A, attempt_id=attempt_id
    )
    # tusd sends the hook three times (-hooks-http-retry=3), then gives the client its 500.
    for _ in range(3):
        failed = await scene.tusd.finish("dave", upload_id, len(NEW_A))
        assert failed.status_code == 500, failed.text
    scene.api.disarm()
    attempt = (await attempt_read(scene, attempt_id)).json()
    assert (attempt["state"], attempt["upload_id"]) == ("ready", upload_id)
    body = commit_body(BASE, [("a.txt", NEW_A, upload_id)])
    assert (await commit(scene, body)).status_code == 200
    await scene.api.restart()
    await assert_published(scene, body, SEALED_FILES)


async def test_a_pre_finish_hook_that_answers_422_fails_the_attempt_and_nothing_seals_it(
    scene: Scene,
) -> None:
    attempt_id = str(uuid.uuid4())
    created = await scene.tusd.create(
        "dave", scene.collection_id, "a.txt", len(NEW_A), attempt_id=attempt_id
    )
    upload_id: str = created.json()["ChangeFileInfo"]["ID"]
    # The data file holds more bytes than the upload declared, so it can never be complete.
    scene.tusd.receive(upload_id, NEW_A + b"!", size=len(NEW_A))
    refused = await scene.tusd.finish("dave", upload_id, len(NEW_A))
    assert problem_of(refused)["code"] == "UPLOAD_SIZE_MISMATCH"
    assert refused.json()["HTTPResponse"]["StatusCode"] == 422
    attempt = (await attempt_read(scene, attempt_id)).json()
    assert (attempt["state"], attempt["upload_id"]) == ("failed", upload_id)
    assert await object_count(scene.api.database_url, upload_id) == 0
    rejected = commit_body(BASE, [("a.txt", NEW_A, upload_id)])
    answer = await commit(scene, rejected)
    assert (answer.status_code, answer.json()["code"]) == (409, "UPLOAD_INELIGIBLE")
    replacement = await ready_upload(scene, "a.txt", NEW_A)
    body = commit_body(BASE, [("a.txt", NEW_A, replacement)])
    assert (await commit(scene, body)).status_code == 200
    await scene.api.restart()
    again = await commit(scene, rejected)
    assert (again.status_code, again.json()) == (409, answer.json())
    assert (await status(scene, rejected["request_id"])).json()["state"] == "rejected"
    assert (await attempt_read(scene, attempt_id)).json()["state"] == "failed"
    await assert_published(scene, body, SEALED_FILES)


async def test_a_pre_finish_hook_that_gets_no_answer_in_time_leaves_the_seal_to_the_attempt_read(
    scene: Scene,
) -> None:
    attempt_id = str(uuid.uuid4())
    arm = Arm(Point.COPY, action=Action.PAUSE)
    scene.api.arm(arm)
    upload_id = await scene.tusd.begin(
        "dave", scene.collection_id, "a.txt", NEW_A, attempt_id=attempt_id
    )
    upload = upload_body(upload_id, len(NEW_A))
    hook = hook_body("pre-finish", upload, "PATCH", f"/files/{upload_id}")
    headers = await scene.api.headers("dave")
    finishing = asyncio.create_task(
        scene.api.client.post(HOOKS, json=hook, headers=headers, timeout=HOOK_TIMEOUT)
    )
    assert await scene.api.stopped() == arm
    with pytest.raises(httpx.ReadTimeout):
        await finishing
    scene.api.disarm()
    attempt = (await attempt_read(scene, attempt_id)).json()
    assert (attempt["state"], attempt["upload_id"]) == ("ready", upload_id)
    body = commit_body(BASE, [("a.txt", NEW_A, upload_id)])
    assert (await commit(scene, body)).status_code == 200
    await scene.api.restart()
    await assert_published(scene, body, SEALED_FILES)


async def test_a_late_tusd_completion_after_a_newer_commit_stays_private(scene: Scene) -> None:
    late_attempt = str(uuid.uuid4())
    created = await scene.tusd.create(
        "dave", scene.collection_id, "a.txt", len(LATE), attempt_id=late_attempt
    )
    late_id: str = created.json()["ChangeFileInfo"]["ID"]
    scene.tusd.receive(late_id, LATE[:5], size=len(LATE))
    newer = await ready_upload(scene, "a.txt", NEW_A)
    body = commit_body(BASE, [("a.txt", NEW_A, newer)])
    assert (await commit(scene, body)).status_code == 200
    # tusd completes the old upload, and writes late bytes into the file of the committed one.
    scene.tusd.receive(late_id, LATE)
    finished = await scene.tusd.finish("dave", late_id, len(LATE))
    assert finished.json()["HTTPResponse"]["Header"][UPLOAD_STATE_HEADER] == "ready"
    (scene.tusd.upload_dir / newer).write_bytes(b"x" * len(NEW_A))
    await scene.api.restart()
    assert (await attempt_read(scene, late_attempt)).json()["state"] == "ready"
    await assert_published(scene, body, SEALED_FILES)


async def test_a_late_completion_of_an_upload_id_that_is_not_current_stays_private(
    scene: Scene,
) -> None:
    attempt_id = str(uuid.uuid4())
    first = await scene.tusd.create(
        "dave", scene.collection_id, "a.txt", len(NEW_A), attempt_id=attempt_id
    )
    old_id: str = first.json()["ChangeFileInfo"]["ID"]
    # tusd made no .info file for the first ID, so the same creation issues a new current ID.
    second = await scene.tusd.create(
        "dave", scene.collection_id, "a.txt", len(NEW_A), attempt_id=attempt_id
    )
    current: str = second.json()["ChangeFileInfo"]["ID"]
    assert current != old_id
    scene.tusd.receive(current, NEW_A[:5], size=len(NEW_A))
    # tusd completes the old ID while the attempt still receives the bytes of the current one.
    stale = LATE[: len(NEW_A)]
    await assert_superseded(scene, old_id, stale)
    attempt = (await attempt_read(scene, attempt_id)).json()
    assert (attempt["state"], attempt["upload_id"]) == ("receiving", current)
    scene.tusd.receive(current, NEW_A)
    finished = await scene.tusd.finish("dave", current, len(NEW_A))
    assert finished.json()["HTTPResponse"]["Header"][UPLOAD_STATE_HEADER] == "ready"
    body = commit_body(BASE, [("a.txt", NEW_A, current)])
    assert (await commit(scene, body)).status_code == 200
    # tusd completes the old ID again after the commit.
    await assert_superseded(scene, old_id, stale)
    await scene.api.restart()
    leftovers = [scene.tusd.upload_dir / old_id, scene.tusd.upload_dir / f"{old_id}.info"]

    async def removed() -> bool:
        return not any(path.exists() for path in leftovers)

    await until(removed, "the cleanup removes the tusd files of the upload ID that is not current")
    assert await object_count(scene.api.database_url, old_id) == 0
    await assert_published(scene, body, SEALED_FILES)


async def assert_superseded(scene: Scene, upload_id: str, data: bytes) -> None:
    """tusd completes ``upload_id`` with ``data``, and the pre-finish hook refuses it because
    the ID is not the current ID of its attempt; no object of the ID exists.
    """
    scene.tusd.receive(upload_id, data)
    refused = await scene.tusd.finish("dave", upload_id, len(data))
    assert refused.json()["HTTPResponse"]["StatusCode"] == 409
    problem = problem_of(refused)
    assert (problem["code"], problem["context"]["reason"]) == ("UPLOAD_INELIGIBLE", "superseded")
    assert await object_count(scene.api.database_url, upload_id) == 0


async def ready_upload(scene: Scene, rel_path: str, data: bytes) -> str:
    """The upload ID of a ready upload of ``data`` to ``rel_path``, sealed by pre-finish."""
    upload_id = await scene.tusd.begin("dave", scene.collection_id, rel_path, data)
    finished = await scene.tusd.finish("dave", upload_id, len(data))
    assert finished.json()["HTTPResponse"]["Header"][UPLOAD_STATE_HEADER] == "ready"
    return upload_id


async def replace_two_remove_one(scene: Scene) -> dict[str, Any]:
    """The body of a commit that replaces a.txt and b.txt with ready uploads and removes c.txt."""
    a = await ready_upload(scene, "a.txt", NEW_A)
    b = await ready_upload(scene, "b.txt", NEW_B)
    return commit_body(BASE, [("a.txt", NEW_A, a), ("b.txt", NEW_B, b)], ["c.txt"])


def commit_body(
    base_version: int, adds: list[tuple[str, bytes, str]], removes: list[str] | None = None
) -> dict[str, Any]:
    """A commit body with a new request ID; each add is a path, its bytes and its upload ID."""
    return {
        "request_id": str(uuid.uuid4()),
        "base_version": base_version,
        "adds": [
            {"rel_path": path, "size": len(data), "sha256": sha256(data), "upload_id": upload_id}
            for path, data, upload_id in adds
        ],
        "removes": removes or [],
        "host": "ws1",
        "message": "a crash test commit",
    }


async def commit(scene: Scene, body: dict[str, Any]) -> httpx.Response:
    """dave's commit of ``body`` to the collection."""
    return await scene.api.client.post(
        f"/api/v1/collections/{scene.collection_id}/commits",
        json=body,
        headers=await scene.api.headers("dave"),
    )


async def status(scene: Scene, request_id: str) -> httpx.Response:
    """dave's read of the saved outcome of his request ``request_id``."""
    return await scene.api.client.get(
        f"/api/v1/commit-requests/{request_id}", headers=await scene.api.headers("dave")
    )


async def attempt_read(scene: Scene, attempt_id: str) -> httpx.Response:
    """dave's read of his upload attempt, which runs the API's own seal check."""
    return await scene.api.client.get(
        f"/api/v1/upload-attempts/{attempt_id}", headers=await scene.api.headers("dave")
    )


async def succeeded(scene: Scene, request_id: str) -> None:
    """Wait until dave's request ``request_id`` is saved as ``succeeded``."""

    async def done() -> bool:
        saved = await status(scene, request_id)
        return saved.status_code == 200 and saved.json()["state"] == "succeeded"

    await until(done, "the commit request succeeds")


async def assert_published(scene: Scene, body: dict[str, Any], files: dict[str, bytes]) -> None:
    """The commit of ``body`` succeeded one time, and the collection holds exactly ``files``.

    It checks the saved outcome and the answer to the same request sent again, the version, the
    file count, the one audit record of the commit, the file rows, and the bytes on disk, each
    file a link of the object that its row names, and no other entry than the metadata file.
    """
    request_id = body["request_id"]
    await succeeded(scene, request_id)
    outcome = (await status(scene, request_id)).json()
    assert outcome == {
        "request_id": request_id,
        "state": "succeeded",
        "collection_id": scene.collection_id,
        "version": NEXT,
        "file_count": len(files),
        "commit_id": outcome["commit_id"],
        "refusal": None,
    }
    again = await commit(scene, body)
    assert (again.status_code, again.json()) == (200, outcome)
    facts = await read_facts(scene.api.database_url, scene.collection_id)
    assert (facts.version, facts.file_count, facts.pending_request_id) == (NEXT, len(files), None)
    assert facts.commit_versions == [BASE, NEXT]
    assert {path: row[0] for path, row in facts.files.items()} == {
        path: sha256(data) for path, data in files.items()
    }
    assert sorted(os.listdir(scene.directory)) == sorted([*files, METADATA_FILE])
    for path, data in files.items():
        assert (scene.directory / path).read_bytes() == data
        assert os.stat(scene.directory / path).st_ino == facts.files[path][1]
