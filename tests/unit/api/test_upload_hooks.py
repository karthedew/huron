"""tusd's hooks over a temporary lake: creating, placing and terminating uploads."""

import asyncio
import hashlib
import os
import stat
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from huron.core.storage import MARKER_FILE, Marker, render_marker
from huron.pkg.hashing import EMPTY_SHA256
from tests.support.api import Service, seed_service, service
from tests.support.clock import frozen
from tests.support.disk import SIGNAL_TIMEOUT, PausingStorage, lake_disk
from tests.support.lake import CONTRIBUTOR
from tests.support.tusd import (
    HOOKS,
    UploadTarget,
    hook_body,
    problem_of,
    upload_body,
    upload_target,
)

DATA = b"solar wind, run seven"
SHA = hashlib.sha256(DATA).hexdigest()
OLD = b"old bytes"
OLD_SHA = hashlib.sha256(OLD).hexdigest()


def receipt(upload_id: str, sha256: str) -> dict[str, object]:
    return {"HTTPResponse": {"Header": {"Huron-Upload-Id": upload_id, "Huron-Sha256": sha256}}}


async def state(api: Service, upload_id: str, user: str = "dave") -> dict[str, object]:
    response = await api.client.get(f"/api/v1/uploads/{upload_id}", headers=await api.headers(user))
    assert response.status_code == 200, response.text
    return dict(response.json())


@pytest.fixture
async def pausing(lake: Path) -> AsyncIterator[tuple[Service, PausingStorage, UploadTarget]]:
    """A service whose lake pauses in its first hash, with collection ``run7`` ready."""
    storage = PausingStorage()
    clock = frozen()
    disk = lake_disk(storage, clock, lake_path=lake, service_gid=os.getgid())
    try:
        async with service(disk=disk, clock=clock) as api:
            await seed_service(api)
            yield api, storage, await upload_target(api, lake)
    finally:
        storage.release.set()


async def hashing(storage: PausingStorage) -> None:
    assert await asyncio.to_thread(storage.hashing.wait, SIGNAL_TIMEOUT)


async def delete_collection(api: Service, target: UploadTarget) -> httpx.Response:
    return await api.client.delete(
        f"/api/v1/collections/{target.collection_id}",
        headers=await api.headers("dave", **{"If-Match": f'"{target.version}"'}),
    )


async def commit(api: Service, target: UploadTarget, rel_path: str, data: bytes) -> None:
    """Commit the placed upload of ``data`` to ``rel_path`` as dave."""
    body = {
        "base_version": target.version,
        "adds": [
            {"rel_path": rel_path, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        ],
        "removes": [],
        "host": "ws1",
        "message": "first",
    }
    committed = await api.client.post(
        f"/api/v1/collections/{target.collection_id}/commits",
        json=body,
        headers=await api.headers("dave"),
    )
    assert committed.status_code == 200, committed.text


async def test_a_fresh_upload_is_placed_and_received(
    seeded_lake_api: Service, target: UploadTarget
) -> None:
    upload_id = await target.tusd.begin("dave", target.collection_id, "a/b/c.bin", DATA)
    inode = os.lstat(target.tusd.upload_dir / upload_id).st_ino
    finished = await target.tusd.finish("dave", upload_id, len(DATA))
    assert (finished.status_code, finished.json()) == (200, receipt(upload_id, SHA))
    placed = target.directory / "a" / "b" / "c.bin"
    assert placed.read_bytes() == DATA
    info = os.lstat(placed)
    assert (stat.S_IMODE(info.st_mode), info.st_nlink, info.st_ino) == (0o644, 1, inode)
    for directory in (target.directory / "a", target.directory / "a" / "b"):
        assert stat.S_IMODE(os.lstat(directory).st_mode) == 0o2750
    assert sorted(p.name for p in target.tusd.upload_dir.iterdir()) == []
    assert await state(seeded_lake_api, upload_id) == {
        "id": upload_id,
        "collection_id": target.collection_id,
        "rel_path": "a/b/c.bin",
        "size": len(DATA),
        "state": "placed",
        "sha256": SHA,
        "failure": None,
    }
    upload = await seeded_lake_api.runtime.lake.uploads.get(CONTRIBUTOR, uuid.UUID(upload_id))
    assert upload.inode == inode


@pytest.mark.parametrize("stale_part", [False, True], ids=["no-part", "stale-part"])
async def test_an_upload_replaces_a_file_through_the_part_file(
    target: UploadTarget, stale_part: bool
) -> None:
    first = await target.tusd.begin("dave", target.collection_id, "c.bin", OLD)
    await target.tusd.finish("dave", first, len(OLD))
    second = await target.tusd.begin("frank", target.collection_id, "c.bin", DATA)
    if stale_part:
        (target.directory / f".c.bin.{second}.huron-part").write_bytes(b"stale")
    finished = await target.tusd.finish("frank", second, len(DATA))
    assert finished.json() == receipt(second, SHA)
    assert (target.directory / "c.bin").read_bytes() == DATA
    assert sorted(p.name for p in target.directory.iterdir()) == ["c.bin"]


async def test_a_retried_pre_finish_after_the_receipt_answers_it_again_without_disk_work(
    seeded_lake_api: Service, target: UploadTarget
) -> None:
    upload_id = await target.tusd.begin("dave", target.collection_id, "c.bin", DATA)
    first = await target.tusd.finish("dave", upload_id, len(DATA))
    (target.directory / "c.bin").unlink()
    again = await target.tusd.finish("dave", upload_id, len(DATA))
    assert again.json() == first.json() == receipt(upload_id, SHA)
    assert not (target.directory / "c.bin").exists()
    await commit(seeded_lake_api, target, "c.bin", DATA)
    assert (await state(seeded_lake_api, upload_id))["state"] == "committed"
    late = await target.tusd.finish("dave", upload_id, len(DATA))
    assert late.json() == receipt(upload_id, SHA)


async def test_two_interleaved_attempts_of_one_upload_both_answer_the_receipt(
    pausing: tuple[Service, PausingStorage, UploadTarget],
) -> None:
    api, storage, target = pausing
    upload_id = await target.tusd.begin("dave", target.collection_id, "c.bin", DATA)
    first = asyncio.create_task(target.tusd.finish("dave", upload_id, len(DATA)))
    await hashing(storage)
    second = await target.tusd.finish("dave", upload_id, len(DATA))
    storage.release.set()
    first_answer = await asyncio.wait_for(first, SIGNAL_TIMEOUT)
    assert first_answer.json() == second.json() == receipt(upload_id, SHA)
    assert (target.directory / "c.bin").read_bytes() == DATA
    assert (await state(api, upload_id))["state"] == "placed"


async def test_an_attempt_that_finds_the_file_placed_by_another_records_the_receipt(
    seeded_lake_api: Service, target: UploadTarget
) -> None:
    upload_id = await target.tusd.begin("dave", target.collection_id, "c.bin", DATA)
    source = target.tusd.upload_dir / upload_id
    os.link(source, target.directory / "c.bin")
    source.unlink()
    finished = await target.tusd.finish("dave", upload_id, len(DATA))
    assert finished.json() == receipt(upload_id, SHA)
    assert (await state(seeded_lake_api, upload_id))["state"] == "placed"


@pytest.mark.parametrize("placed", [None, b"other"], ids=["nothing-placed", "other-size"])
async def test_an_attempt_without_the_file_or_its_placement_is_retried(
    seeded_lake_api: Service, target: UploadTarget, placed: bytes | None
) -> None:
    created = await target.tusd.create("dave", target.collection_id, "c.bin", len(DATA))
    upload_id = created.json()["ChangeFileInfo"]["ID"]
    if placed is not None:
        (target.directory / "c.bin").write_bytes(placed)
    finished = await target.tusd.finish("dave", upload_id, len(DATA))
    assert (finished.status_code, finished.json()["code"]) == (500, "STORAGE_FAILED")
    assert (await state(seeded_lake_api, upload_id))["state"] == "pending"


@pytest.mark.parametrize("received", [DATA[:-1], DATA + b"!"], ids=["shorter", "longer"])
async def test_the_size_of_the_received_file_must_be_the_declared_size(
    seeded_lake_api: Service, target: UploadTarget, received: bytes
) -> None:
    created = await target.tusd.create("dave", target.collection_id, "c.bin", len(DATA))
    upload_id = created.json()["ChangeFileInfo"]["ID"]
    target.tusd.receive(upload_id, received)
    finished = await target.tusd.finish("dave", upload_id, len(DATA))
    assert finished.status_code == 200
    problem = problem_of(finished)
    assert (problem["status"], problem["code"]) == (422, "UPLOAD_SIZE_MISMATCH")
    assert problem["context"] == {"declared": len(DATA), "received": len(received)}
    assert (await state(seeded_lake_api, upload_id))["state"] == "pending"
    assert not (target.directory / "c.bin").exists()


async def test_a_collection_deleted_during_the_hash_takes_the_placed_file_away(
    pausing: tuple[Service, PausingStorage, UploadTarget],
) -> None:
    api, storage, target = pausing
    upload_id = await target.tusd.begin("dave", target.collection_id, "a/b/c.bin", DATA)
    finishing = asyncio.create_task(target.tusd.finish("dave", upload_id, len(DATA)))
    await hashing(storage)
    assert (await delete_collection(api, target)).status_code == 204
    storage.release.set()
    finished = await asyncio.wait_for(finishing, SIGNAL_TIMEOUT)
    problem = problem_of(finished)
    assert (problem["status"], problem["code"]) == (404, "UPLOAD_NOT_FOUND")
    assert list(target.directory.iterdir()) == []


async def test_a_termination_during_the_hash_takes_the_placed_file_away(
    pausing: tuple[Service, PausingStorage, UploadTarget],
) -> None:
    api, storage, target = pausing
    upload_id = await target.tusd.begin("dave", target.collection_id, "c.bin", DATA)
    finishing = asyncio.create_task(target.tusd.finish("dave", upload_id, len(DATA)))
    await hashing(storage)
    assert (await target.tusd.terminate("dave", upload_id)).json() == {}
    storage.release.set()
    finished = await asyncio.wait_for(finishing, SIGNAL_TIMEOUT)
    problem = problem_of(finished)
    assert (problem["status"], problem["code"]) == (409, "UPLOAD_STATE_CONFLICT")
    assert list(target.directory.iterdir()) == []
    assert (await state(api, upload_id))["state"] == "terminated"


async def uploaded_first(
    api: Service, storage: PausingStorage, target: UploadTarget, *, committed: bool
) -> tuple[Path, int]:
    """Place an upload of ``OLD`` to ``c.bin``, committed or not; the next hash pauses.

    Returns the placed file and its inode.
    """
    storage.release.set()
    first = await target.tusd.begin("dave", target.collection_id, "c.bin", OLD)
    assert (await target.tusd.finish("dave", first, len(OLD))).json() == receipt(first, OLD_SHA)
    if committed:
        await commit(api, target, "c.bin", OLD)
    storage.pause_next()
    placed = target.directory / "c.bin"
    return placed, os.lstat(placed).st_ino


@pytest.mark.parametrize(
    ("refusal", "status", "code"),
    [("delete", 404, "UPLOAD_NOT_FOUND"), ("terminate", 409, "UPLOAD_STATE_CONFLICT")],
)
async def test_an_overwrite_refused_after_the_link_restores_the_replaced_file(
    pausing: tuple[Service, PausingStorage, UploadTarget], refusal: str, status: int, code: str
) -> None:
    api, storage, target = pausing
    # A collection with recorded files cannot be deleted, so the delete replaces a placed file.
    replaced, inode = await uploaded_first(api, storage, target, committed=refusal == "terminate")
    upload_id = await target.tusd.begin("dave", target.collection_id, "c.bin", DATA)
    finishing = asyncio.create_task(target.tusd.finish("dave", upload_id, len(DATA)))
    await hashing(storage)
    if refusal == "delete":
        assert (await delete_collection(api, target)).status_code == 204
    else:
        assert (await target.tusd.terminate("dave", upload_id)).json() == {}
    storage.release.set()
    problem = problem_of(await asyncio.wait_for(finishing, SIGNAL_TIMEOUT))
    assert (problem["status"], problem["code"]) == (status, code)
    assert (replaced.read_bytes(), os.lstat(replaced).st_ino) == (OLD, inode)
    assert not (target.directory / f".c.bin.{upload_id}.huron-prev").exists()


async def test_a_termination_after_a_crash_between_the_rename_and_the_cleanup_restores_the_file(
    pausing: tuple[Service, PausingStorage, UploadTarget],
) -> None:
    api, storage, target = pausing
    replaced, inode = await uploaded_first(api, storage, target, committed=True)
    upload_id = await target.tusd.begin("dave", target.collection_id, "c.bin", DATA)
    # An earlier attempt renamed its part over c.bin and stopped before it removed tusd's files.
    backup = target.directory / f".c.bin.{upload_id}.huron-prev"
    part = target.directory / f".c.bin.{upload_id}.huron-part"
    os.link(replaced, backup)
    os.link(target.tusd.upload_dir / upload_id, part)
    os.rename(part, replaced)
    finishing = asyncio.create_task(target.tusd.finish("dave", upload_id, len(DATA)))
    await hashing(storage)
    assert (await target.tusd.terminate("dave", upload_id)).json() == {}
    storage.release.set()
    problem = problem_of(await asyncio.wait_for(finishing, SIGNAL_TIMEOUT))
    assert (problem["status"], problem["code"]) == (409, "UPLOAD_STATE_CONFLICT")
    assert (replaced.read_bytes(), os.lstat(replaced).st_ino) == (OLD, inode)
    assert not backup.exists()


async def test_a_replay_after_a_crash_between_the_rename_and_the_receipt_drops_the_backup(
    seeded_lake_api: Service, target: UploadTarget
) -> None:
    destination = target.directory / "c.bin"
    destination.write_bytes(OLD)
    upload_id = await target.tusd.begin("dave", target.collection_id, "c.bin", DATA)
    backup = target.directory / f".c.bin.{upload_id}.huron-prev"
    os.link(destination, backup)
    os.replace(target.tusd.upload_dir / upload_id, destination)
    finished = await target.tusd.finish("dave", upload_id, len(DATA))
    assert finished.json() == receipt(upload_id, SHA)
    assert destination.read_bytes() == DATA
    assert not backup.exists()
    assert (await state(seeded_lake_api, upload_id))["state"] == "placed"


async def test_a_missing_collection_directory_fails_the_upload(
    seeded_lake_api: Service, target: UploadTarget
) -> None:
    upload_id = await target.tusd.begin("dave", target.collection_id, "a/c.bin", DATA)
    target.directory.rmdir()
    finished = await target.tusd.finish("dave", upload_id, len(DATA))
    assert finished.status_code == 200
    problem = problem_of(finished)
    assert (problem["status"], problem["code"]) == (500, "STORAGE_FAILED")
    assert "huron adm repair" in problem["detail"]
    assert problem["instance"] == f"/files/{upload_id}"
    failed = await state(seeded_lake_api, upload_id)
    assert failed["state"] == "failed"
    assert failed["failure"] == {"code": "STORAGE_FAILED", "message": problem["detail"]}
    assert not target.directory.exists()


async def test_a_wrong_marker_makes_tusd_send_the_hook_again(
    seeded_lake_api: Service, target: UploadTarget, lake: Path
) -> None:
    upload_id = await target.tusd.begin("dave", target.collection_id, "c.bin", DATA)
    (lake / MARKER_FILE).write_bytes(render_marker(Marker(1, "http://other", "other")))
    finished = await target.tusd.finish("dave", upload_id, len(DATA))
    assert (finished.status_code, finished.json()["code"]) == (503, "LAKE_UNAVAILABLE")
    assert (await state(seeded_lake_api, upload_id))["state"] == "pending"
    assert (target.tusd.upload_dir / upload_id).exists()


async def test_a_zero_length_upload_is_placed_with_the_hash_of_no_bytes(
    target: UploadTarget,
) -> None:
    upload_id = await target.tusd.begin("dave", target.collection_id, "empty.bin", b"")
    finished = await target.tusd.finish("dave", upload_id, 0)
    assert finished.json() == receipt(upload_id, EMPTY_SHA256)
    assert (target.directory / "empty.bin").read_bytes() == b""


async def test_a_terminated_upload_is_never_placed(
    seeded_lake_api: Service, target: UploadTarget
) -> None:
    upload_id = await target.tusd.begin("dave", target.collection_id, "c.bin", DATA)
    for _ in range(2):
        terminated = await target.tusd.terminate("dave", upload_id)
        assert (terminated.status_code, terminated.json()) == (200, {})
    assert (await state(seeded_lake_api, upload_id))["state"] == "terminated"
    finished = await target.tusd.finish("dave", upload_id, len(DATA))
    assert set(finished.json()) == {"HTTPResponse"}
    problem = problem_of(finished)
    assert (problem["status"], problem["code"]) == (409, "UPLOAD_STATE_CONFLICT")
    assert problem["context"] == {
        "state": "terminated",
        "allowed": ["pending", "placed", "committed"],
    }


async def test_a_creation_answers_the_upload_id(
    seeded_lake_api: Service, target: UploadTarget
) -> None:
    created = await target.tusd.create("dave", target.collection_id, "c.bin", len(DATA))
    assert created.status_code == 200
    upload_id = created.json()["ChangeFileInfo"]["ID"]
    assert created.json() == {"ChangeFileInfo": {"ID": upload_id}}
    assert (await state(seeded_lake_api, upload_id))["state"] == "pending"


@pytest.mark.parametrize(
    ("user", "metadata", "flags", "status", "code"),
    [
        ("dave", None, {"SizeIsDeferred": True}, 422, "REQUEST_INVALID"),
        ("dave", None, {"IsPartial": True}, 422, "REQUEST_INVALID"),
        ("dave", None, {"IsFinal": True}, 422, "REQUEST_INVALID"),
        ("dave", {"rel_path": "c.bin"}, {}, 422, "REQUEST_INVALID"),
        ("dave", {"collection": "not-a-uuid", "rel_path": "c.bin"}, {}, 422, "REQUEST_INVALID"),
        ("dave", {"collection": "<collection>"}, {}, 422, "REQUEST_INVALID"),
        ("erin", None, {}, 403, "FORBIDDEN"),
        (None, None, {}, 401, "UNAUTHENTICATED"),
    ],
)
async def test_a_creation_is_refused(
    target: UploadTarget,
    user: str | None,
    metadata: dict[str, str] | None,
    flags: dict[str, bool],
    status: int,
    code: str,
) -> None:
    given = metadata or {"collection": target.collection_id, "rel_path": "c.bin"}
    given = {k: v.replace("<collection>", target.collection_id) for k, v in given.items()}
    body = hook_body("pre-create", upload_body("", 5, given, **flags), "POST", "/files/")
    refused = await target.tusd.send(user, body)
    assert refused.status_code == 200
    assert set(refused.json()) == {"HTTPResponse", "RejectUpload"}
    assert refused.json()["RejectUpload"] is True
    problem = problem_of(refused)
    assert (problem["status"], problem["code"], problem["instance"]) == (status, code, "/files/")


async def test_an_invalid_token_is_refused_in_the_hook(
    seeded_lake_api: Service, target: UploadTarget
) -> None:
    body = hook_body("pre-finish", upload_body(str(uuid.uuid4()), 1), "PATCH", "/files/x")
    refused = await seeded_lake_api.client.post(
        HOOKS, json=body, headers={"Authorization": "Bearer not-a-token"}
    )
    problem = problem_of(refused)
    assert (problem["status"], problem["code"]) == (401, "TOKEN_INVALID")


async def test_another_users_upload_is_not_found(target: UploadTarget) -> None:
    upload_id = await target.tusd.begin("dave", target.collection_id, "c.bin", DATA)
    finished = await target.tusd.finish("frank", upload_id, len(DATA))
    assert problem_of(finished)["code"] == "UPLOAD_NOT_FOUND"
    terminated = await target.tusd.terminate("frank", upload_id)
    assert set(terminated.json()) == {"HTTPResponse", "RejectTermination"}
    assert terminated.json()["RejectTermination"] is True
    assert problem_of(terminated)["code"] == "UPLOAD_NOT_FOUND"
    assert (target.tusd.upload_dir / upload_id).exists()


@pytest.mark.parametrize("upload_id", ["not-a-uuid", "0192B6A0-0000-7000-8000-0000000000AA"])
async def test_a_hook_for_an_id_that_is_not_a_uuid_is_refused(
    target: UploadTarget, upload_id: str
) -> None:
    finished = await target.tusd.finish("dave", upload_id, 0)
    assert problem_of(finished)["code"] == "REQUEST_INVALID"


async def test_an_upload_is_read_by_its_creator_only(
    seeded_lake_api: Service, target: UploadTarget
) -> None:
    upload_id = await target.tusd.begin("dave", target.collection_id, "c.bin", DATA)
    for user, path in (("frank", upload_id), ("dave", str(uuid.uuid4()))):
        read = await seeded_lake_api.client.get(
            f"/api/v1/uploads/{path}", headers=await seeded_lake_api.headers(user)
        )
        assert (read.status_code, read.json()["code"]) == (404, "UPLOAD_NOT_FOUND")


async def test_upload_routes_need_a_lake(seeded_api: Service) -> None:
    body = hook_body("pre-create", upload_body(), "POST", "/files/")
    headers = await seeded_api.headers("dave")
    for response in (
        await seeded_api.client.post(HOOKS, json=body, headers=headers),
        await seeded_api.client.get(f"/api/v1/uploads/{uuid.uuid4()}", headers=headers),
    ):
        assert (response.status_code, response.json()["code"]) == (404, "UPLOADS_DISABLED")
