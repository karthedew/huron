"""The read of an upload attempt, which seals a complete upload, and the cancel of an upload."""

import hashlib
import uuid
from pathlib import Path

import httpx

from huron.applications.api.app import create_app
from huron.applications.api.runtime import build_runtime
from huron.core.lake.publications.models import CommitAdd, CommitRequest
from huron.core.metastore.store import MemoryStore
from tests.fakes.groups import FakeGroups
from tests.support.api import USERS, Service, seed_service, service, settings
from tests.support.lake import CONTRIBUTOR
from tests.support.tusd import UploadTarget, upload_target

DATA = b"0123456789"
ATTEMPT = "0190d5a4-0000-7000-8000-0000000000c1"


async def read(api: Service, attempt_id: str = ATTEMPT, user: str = "dave") -> httpx.Response:
    return await api.client.get(
        f"/api/v1/upload-attempts/{attempt_id}", headers=await api.headers(user)
    )


async def cancel(api: Service, upload_id: str, user: str = "dave") -> httpx.Response:
    return await api.client.post(
        f"/api/v1/uploads/{upload_id}/cancel", headers=await api.headers(user)
    )


async def created(target: UploadTarget) -> str:
    answer = await target.tusd.create(
        "dave", target.collection_id, "d.bin", len(DATA), attempt_id=ATTEMPT
    )
    upload_id: str = answer.json()["ChangeFileInfo"]["ID"]
    return upload_id


async def test_the_owner_reads_the_state_and_the_current_upload_id(target: UploadTarget) -> None:
    api = target.tusd.api
    upload_id = await created(target)
    answer = await read(api)
    assert answer.status_code == 200
    assert answer.json() == {
        "attempt_id": ATTEMPT,
        "collection_id": target.collection_id,
        "rel_path": "d.bin",
        "size": len(DATA),
        "state": "receiving",
        "upload_id": upload_id,
        "failure": None,
    }


async def test_another_user_and_an_unknown_attempt_are_not_found(target: UploadTarget) -> None:
    api = target.tusd.api
    await created(target)
    for attempt_id, user in ((ATTEMPT, "frank"), (str(uuid.uuid4()), "dave")):
        answer = await read(api, attempt_id, user)
        assert (answer.status_code, answer.json()["code"]) == (404, "NOT_FOUND")
        assert answer.json()["context"] == {"attempt_id": attempt_id}


async def test_the_read_seals_a_complete_upload_that_no_hook_reported(
    target: UploadTarget, lake: Path
) -> None:
    api = target.tusd.api
    upload_id = await created(target)
    target.tusd.receive(upload_id, DATA)
    answer = await read(api)
    assert answer.json()["state"] == "ready"
    assert (lake / "helio" / ".huron-objects" / upload_id).read_bytes() == DATA


async def test_the_read_skips_an_upload_that_tusd_still_works_on(
    target: UploadTarget, lake: Path
) -> None:
    api = target.tusd.api
    upload_id = await created(target)
    target.tusd.receive(upload_id, DATA, locked=True)
    assert (await read(api)).json()["state"] == "receiving"
    assert not (lake / "helio" / ".huron-objects" / upload_id).exists()


async def test_a_read_only_process_answers_from_the_database_and_starts_no_seal(
    lake: Path,
) -> None:
    store = MemoryStore()
    async with service(store=store, lake_path=lake) as writer:
        target = await upload_target(await seed_service(writer), lake)
        upload_id = await created(target)
        target.tusd.receive(upload_id, DATA)
        reader = await build_runtime(
            settings(lake_path=lake),
            store=store,
            http=httpx.AsyncClient(transport=writer.issuer.transport()),
            groups=FakeGroups(USERS),
            clock=writer.clock,
        )
        try:
            assert reader.orchestration is not None
            assert not reader.orchestration.ownership.writable
            transport = httpx.ASGITransport(app=create_app(runtime=reader))
            async with httpx.AsyncClient(transport=transport, base_url="http://huron.test") as c:
                answer = await c.get(
                    f"/api/v1/upload-attempts/{ATTEMPT}", headers=await writer.headers("dave")
                )
        finally:
            await reader.close()
        assert answer.json()["state"] == "receiving"
        assert not (lake / "helio" / ".huron-objects" / upload_id).exists()
        assert (await read(writer)).json()["state"] == "ready"


async def test_the_read_needs_a_lake(seeded_api: Service) -> None:
    answer = await read(seeded_api)
    assert (answer.status_code, answer.json()["code"]) == (404, "UPLOADS_DISABLED")


async def test_a_cancel_ends_the_attempt_and_removes_the_files_of_every_upload_id(
    target: UploadTarget,
) -> None:
    api = target.tusd.api
    first = await created(target)
    target.tusd.upload_dir.joinpath(first).write_bytes(b"orphan")
    second = await created(target)
    target.tusd.receive(second, DATA[:4])
    answer = await cancel(api, first)
    assert answer.status_code == 200
    assert answer.json()["state"] == "cancelled"
    assert answer.json()["upload_id"] == second
    assert sorted(path.name for path in target.tusd.upload_dir.iterdir()) == []


async def test_a_cancel_of_an_ended_attempt_changes_nothing(target: UploadTarget) -> None:
    api = target.tusd.api
    upload_id = await created(target)
    first = await cancel(api, upload_id)
    again = await cancel(api, upload_id)
    assert again.status_code == 200 and again.json() == first.json()


async def test_a_cancel_of_another_users_upload_is_not_found(target: UploadTarget) -> None:
    api = target.tusd.api
    upload_id = await created(target)
    for named, user in ((upload_id, "frank"), (str(uuid.uuid4()), "dave")):
        answer = await cancel(api, named, user)
        assert (answer.status_code, answer.json()["code"]) == (404, "UPLOAD_NOT_FOUND")
    assert (await read(api)).json()["state"] == "receiving"


async def test_a_cancel_of_an_upload_that_a_commit_holds_is_a_conflict(
    target: UploadTarget,
) -> None:
    api = target.tusd.api
    upload_id = await created(target)
    target.tusd.receive(upload_id, DATA)
    await target.tusd.finish("dave", upload_id, len(DATA))
    add = CommitAdd("d.bin", len(DATA), hashlib.sha256(DATA).hexdigest(), uuid.UUID(upload_id))
    request = CommitRequest(
        uuid.uuid4(), uuid.UUID(target.collection_id), target.version, (add,), (), "h"
    )
    await api.runtime.publications.submit(CONTRIBUTOR, request)
    answer = await cancel(api, upload_id)
    assert (answer.status_code, answer.json()["code"]) == (409, "STATE_CONFLICT")
    assert answer.json()["context"] == {
        "attempt_id": ATTEMPT,
        "state": "ready",
        "allowed": ["receiving", "sealing"],
    }
    assert target.tusd.upload_dir.joinpath(upload_id).exists()


async def test_a_cancel_in_a_read_only_process_leaves_the_files_to_the_writer(
    lake: Path,
) -> None:
    store = MemoryStore()
    async with service(store=store, lake_path=lake) as writer:
        target = await upload_target(await seed_service(writer), lake)
        upload_id = await created(target)
        target.tusd.receive(upload_id, DATA[:2])
        reader = await build_runtime(
            settings(lake_path=lake),
            store=store,
            http=httpx.AsyncClient(transport=writer.issuer.transport()),
            groups=FakeGroups(USERS),
            clock=writer.clock,
        )
        try:
            transport = httpx.ASGITransport(app=create_app(runtime=reader))
            async with httpx.AsyncClient(transport=transport, base_url="http://huron.test") as c:
                answer = await c.post(
                    f"/api/v1/uploads/{upload_id}/cancel", headers=await writer.headers("dave")
                )
        finally:
            await reader.close()
        assert answer.json()["state"] == "cancelled"
        assert target.tusd.upload_dir.joinpath(upload_id).exists()
