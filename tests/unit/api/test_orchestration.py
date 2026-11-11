"""The runtime's work on the lake: the writer lock, recovery at startup, the readers."""

import asyncio
import os
import signal
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

import pytest

from huron.applications.api import runtime as runtime_module
from huron.core.lake.publications.models import CommitAdd, CommitRequest, CommitState
from huron.core.lake.uploads.errors import CapacityExceeded, UploadTooLarge
from huron.core.lake.uploads.models import AttemptState
from huron.core.metastore.store import MemoryStore, MemoryTransaction
from huron.core.storage import MARKER_FILE, LakePath, LakeUnavailable
from huron.core.storage.memory import MemoryStorage
from huron.pkg.errors import Unavailable
from huron.pkg.identifiers import new_id
from tests.support.api import ROOT_MARKER, Service, active_collection, seed_service, service
from tests.support.disk import LAKE, memory_lake
from tests.support.lake import CONTRIBUTOR
from tests.support.orchestration import receive
from tests.support.publication import sha256

DATA = b"solar wind"


async def accepted_request(api: Service, storage: MemoryStorage) -> tuple[uuid.UUID, CommitRequest]:
    """A sealed upload of ``a.cdf`` and an accepted request that adds it; nothing published."""
    await seed_service(api)
    collection = await active_collection(api)
    runtime = api.runtime
    assert runtime.orchestration is not None
    collection_id = uuid.UUID(collection["id"])
    attempt = await runtime.attempts.begin(CONTRIBUTOR, new_id(), collection_id, "a.cdf", len(DATA))
    receive(storage, attempt.current_upload_id, DATA)
    sealed = await runtime.orchestration.sealing.check(attempt.current_upload_id)
    assert sealed.state is AttemptState.READY
    add = CommitAdd("a.cdf", len(DATA), sha256(DATA), attempt.current_upload_id)
    request = CommitRequest(new_id(), collection_id, collection["version"], (add,), (), "h")
    outcome = await runtime.publications.submit(CONTRIBUTOR, request)
    return outcome.id, request


async def test_the_writer_continues_a_pending_request_at_startup() -> None:
    store, storage = MemoryStore(), memory_lake()
    async with service(store=store, storage=storage, lake_path=LAKE) as first:
        row_id, request = await accepted_request(first, storage)
    assert store.writer is None
    async with service(store=store, storage=storage, lake_path=LAKE) as second:
        (recovery,) = [
            task for task in asyncio.all_tasks() if task.get_name() == f"publication:{row_id}"
        ]
        done = await recovery
        assert done.state is CommitState.SUCCEEDED
        status = await second.runtime.publications.status(CONTRIBUTOR, request.request_id)
        assert status == done
    run7 = LakePath.of("helio", "heliophysics", "solar-wind", "run7", "a.cdf")
    assert storage.read_bytes(run7) == DATA
    (sealed,) = list(storage.walk(LakePath.of("helio", ".huron-objects")))
    assert (
        storage.stat(run7).inode
        == storage.stat(LakePath.of("helio", ".huron-objects", *sealed.names)).inode
    )


async def test_a_second_runtime_on_the_same_store_serves_reads_only() -> None:
    store, storage = MemoryStore(), memory_lake()
    async with service(store=store, storage=storage, lake_path=LAKE) as writer:
        orchestration = writer.runtime.orchestration
        assert orchestration is not None and orchestration.ownership.writable
        assert orchestration.background.running("maintenance")
        async with service(store=store, storage=storage, lake_path=LAKE) as reader:
            readers = reader.runtime.orchestration
            assert readers is not None and not readers.ownership.writable
            assert not readers.background.running("maintenance")
            assert await reader.runtime.ready() == {
                "database": True,
                "signing_keys": True,
                "lake": True,
            }
            assert reader.runtime.disk is not None
            with pytest.raises(LakeUnavailable) as refused:
                await reader.runtime.disk.work(reader.runtime.disk.locate("helio"), lambda: None)
            assert refused.value.context == {"reason": "writer_lock"}
            listed = await reader.client.get(
                "/api/v1/organizations", headers=await reader.headers("alice")
            )
            assert listed.status_code == 200
        assert store.writer is not None
    assert store.writer is None


async def test_the_writer_stops_its_process_when_it_loses_the_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signals: list[tuple[int, int]] = []
    monkeypatch.setattr(runtime_module.os, "kill", lambda pid, sig: signals.append((pid, sig)))
    store = MemoryStore()
    async with service(store=store, storage=memory_lake(), lake_path=LAKE) as api:
        orchestration = api.runtime.orchestration
        assert orchestration is not None
        store.writer = None
        assert await orchestration.ownership.check() is False
    assert signals == [(os.getpid(), signal.SIGTERM)]


async def test_a_lake_that_does_not_open_gives_the_writer_lock_back() -> None:
    store, storage = MemoryStore(), memory_lake()
    storage.denied.add(LakePath())
    with pytest.raises(LakeUnavailable, match="cannot write the lake"):
        async with service(store=store, storage=storage, lake_path=LAKE):
            pass
    assert store.writer is None


async def test_the_runtime_builds_the_attempts_with_their_own_settings() -> None:
    size = len(DATA)
    async with service(attempt_ttl="3600", max_upload_bytes=size, max_staged_bytes=2 * size) as api:
        assert api.runtime.orchestration is None
        await seed_service(api)
        collection_id = uuid.UUID((await active_collection(api))["id"])
        attempts = api.runtime.attempts
        with pytest.raises(UploadTooLarge):
            await attempts.begin(CONTRIBUTOR, new_id(), collection_id, "a.cdf", size + 1)
        attempt = await attempts.begin(CONTRIBUTOR, new_id(), collection_id, "a.cdf", size)
        with pytest.raises(CapacityExceeded):
            await attempts.begin(CONTRIBUTOR, new_id(), collection_id, "b.cdf", size)
        api.clock.advance(timedelta(seconds=3600))
        assert await attempts.expire() == []
        api.clock.advance(timedelta(microseconds=1))
        assert [row.id for row in await attempts.expire()] == [attempt.id]


async def test_the_periodic_run_completes_a_request_that_a_storage_error_left_accepted() -> None:
    store, storage = MemoryStore(), memory_lake()
    async with service(store=store, storage=storage, lake_path=LAKE) as api:
        row_id, request = await accepted_request(api, storage)
        orchestration = api.runtime.orchestration
        assert orchestration is not None
        storage.remove_file(LakePath.of(MARKER_FILE))
        outcome = await api.runtime.publications.status(CONTRIBUTOR, request.request_id)
        with pytest.raises(LakeUnavailable):
            await orchestration.materializer.start(outcome)
        storage.write_bytes(LakePath.of(MARKER_FILE), ROOT_MARKER, 0o644)
        await orchestration.maintain()
        (resumed,) = [
            task for task in asyncio.all_tasks() if task.get_name() == f"publication:{row_id}"
        ]
        assert (await resumed).state is CommitState.SUCCEEDED
        assert store.writer is not None


class DroppingStore(MemoryStore):
    """An in-memory store whose transactions fail once a writer holds its lock."""

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[MemoryTransaction]:
        if self.writer is not None:
            raise Unavailable("the database is unreachable")
        async with super().transaction() as tx:
            yield tx


async def test_a_failure_after_the_writer_lock_gives_the_lock_back() -> None:
    store = DroppingStore()
    with pytest.raises(Unavailable):
        async with service(store=store, storage=memory_lake(), lake_path=LAKE):
            pass
    assert store.writer is None
