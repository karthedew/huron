"""Cleanup of the lake: the objects and tusd files that no row needs, chosen by database ID."""

import asyncio
import threading
from collections.abc import AsyncIterator

import pytest
import structlog

from huron.core.lake.publications.models import CommitState
from huron.core.lake.uploads.models import AttemptState, ObjectState, UploadAttempt
from huron.core.storage import UPLOADS, LakePath, SealedFile
from huron.pkg.identifiers import new_id
from tests.support.disk import SIGNAL_TIMEOUT
from tests.support.lake import CONTRIBUTOR
from tests.support.orchestration import COLLECTION, OBJECTS, Bench, bench, receive, tus_file
from tests.support.publication import TTL

WIND, SUN, RAIN = b"solar wind", b"sunspots", b"rain"


@pytest.fixture
async def lab() -> AsyncIterator[Bench]:
    async with bench() as built:
        yield built


def has_files(lab: Bench, attempt: UploadAttempt, upload_id: object = None) -> bool:
    """Whether tusd's data file and ``.info`` file of the upload ID are on the lake."""
    upload = upload_id or attempt.current_upload_id
    return all(
        lab.storage.stat(UPLOADS.joinpath(f"{upload}{suffix}")) is not None
        for suffix in ("", ".info")
    )


def object_of(lab: Bench, attempt: UploadAttempt) -> LakePath:
    return OBJECTS.joinpath(str(attempt.current_upload_id))


async def publish(lab: Bench, base_version: int, path: str, data: bytes) -> UploadAttempt:
    """Seal ``data`` for ``path`` and publish it in one request."""
    sealed = await lab.sealed(path, data)
    request = lab.publishing.request(base_version, [(sealed, data)])
    accepted = await lab.publishing.publications.submit(CONTRIBUTOR, request)
    assert (await lab.materializer.start(accepted)).state is CommitState.SUCCEEDED
    return sealed


async def test_cleanup_removes_only_what_no_row_needs(lab: Bench) -> None:
    replaced = await publish(lab, 2, "a.cdf", WIND)
    published = await publish(lab, 3, "a.cdf", SUN)
    ready = await lab.sealed("ready.cdf", RAIN)
    receiving = await lab.received("receiving.cdf", RAIN)
    cancelled = await lab.sealed("cancelled.cdf", RAIN)
    await lab.publishing.attempts.cancel(CONTRIBUTOR, cancelled.attempt_id)
    reissued = await lab.received("reissued.cdf", RAIN)
    current = await lab.publishing.attempts.begin(
        CONTRIBUTOR, reissued.attempt_id, reissued.collection_id, "reissued.cdf", len(RAIN)
    )
    receive(lab.storage, current.current_upload_id, RAIN)
    unknown = new_id()
    receive(lab.storage, unknown, RAIN)
    lab.storage.write_bytes(UPLOADS.joinpath("notes.txt"), b"keep", 0o600)
    await lab.cleanup.run()
    for gone in (replaced, cancelled):
        assert lab.storage.stat(object_of(lab, gone)) is None
        assert (await lab.publishing.stored(gone.current_upload_id)).state is ObjectState.REMOVED
    for attempt in (replaced, published, cancelled):
        assert not has_files(lab, attempt)
    assert not has_files(lab, reissued, reissued.current_upload_id)
    for attempt in (ready, receiving, current):
        assert has_files(lab, attempt)
    for kept in (published, ready):
        assert lab.storage.read_bytes(object_of(lab, kept)) in (SUN, RAIN)
        assert (await lab.publishing.stored(kept.current_upload_id)).state is ObjectState.SEALED
    assert lab.storage.read_bytes(COLLECTION.joinpath("a.cdf")) == SUN
    assert has_files(lab, receiving, unknown)
    assert lab.storage.read_bytes(UPLOADS.joinpath("notes.txt")) == b"keep"


async def test_an_upload_that_a_pending_request_holds_keeps_its_object(lab: Bench) -> None:
    sealed = await lab.sealed("a.cdf", WIND)
    request = lab.publishing.request(2, [(sealed, WIND)])
    accepted = await lab.publishing.publications.submit(CONTRIBUTOR, request)
    await lab.cleanup.run()
    assert lab.storage.read_bytes(object_of(lab, sealed)) == WIND
    assert (await lab.materializer.start(accepted)).state is CommitState.SUCCEEDED


async def test_a_run_expires_the_lapsed_attempts_and_removes_their_files(lab: Bench) -> None:
    attempts = [await lab.received(f"{index}.cdf", WIND) for index in range(3)]
    sealing = attempts[2]
    await lab.publishing.attempts.start_seal(sealing.current_upload_id)
    lab.storage.make_directory(OBJECTS, 0o700)
    lab.storage.write_bytes(object_of(lab, sealing), WIND[:2], 0o644)
    lab.publishing.clock.advance(TTL * 2)
    await lab.cleanup.run()
    for attempt in attempts:
        assert (await lab.publishing.attempt(attempt)).state is AttemptState.EXPIRED
        assert not has_files(lab, attempt)
    assert lab.storage.stat(object_of(lab, sealing)) is None


async def test_a_run_expires_every_page_of_lapsed_attempts(lab: Bench) -> None:
    attempts = [
        await lab.publishing.receiving(CONTRIBUTOR, f"{index}.cdf", WIND) for index in range(501)
    ]
    lab.publishing.clock.advance(TTL * 2)
    await lab.cleanup.run()
    for attempt in (attempts[0], attempts[-1]):
        assert (await lab.publishing.attempt(attempt)).state is AttemptState.EXPIRED


async def test_an_upload_whose_seal_runs_is_left_for_the_next_run(
    lab: Bench, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempt = await lab.received("a.cdf", WIND)
    copying, release = threading.Event(), threading.Event()
    copy = lab.storage.copy_sealed

    def paused(source: LakePath, destination: LakePath, size: int) -> SealedFile:
        copying.set()
        assert release.wait(SIGNAL_TIMEOUT)
        return copy(source, destination, size)

    monkeypatch.setattr(lab.storage, "copy_sealed", paused)
    task = lab.sealing.start(attempt.current_upload_id)
    assert await asyncio.to_thread(copying.wait, SIGNAL_TIMEOUT)
    await lab.publishing.attempts.cancel(CONTRIBUTOR, attempt.attempt_id)
    await lab.cleanup.run()
    assert has_files(lab, attempt)
    release.set()
    assert (await task).state is AttemptState.CANCELLED
    await asyncio.sleep(0)
    await lab.cleanup.run()
    assert not has_files(lab, attempt)
    assert lab.storage.stat(object_of(lab, attempt)) is None


async def test_a_failed_removal_is_logged_and_the_next_run_tries_again(lab: Bench) -> None:
    attempt = await lab.sealed("a.cdf", WIND)
    await lab.publishing.attempts.cancel(CONTRIBUTOR, attempt.attempt_id)
    lab.storage.denied |= {OBJECTS, UPLOADS}
    with structlog.testing.capture_logs() as captured:
        await lab.cleanup.run()
    assert [(entry["event"], entry["path"]) for entry in captured] == [
        ("cleanup.failed", str(object_of(lab, attempt))),
        ("cleanup.failed", str(tus_file(attempt.current_upload_id))),
    ]
    assert captured[0]["code"] == "STORAGE_FAILED"
    assert (await lab.publishing.stored(attempt.current_upload_id)).state is ObjectState.SEALED
    lab.storage.denied.clear()
    await lab.cleanup.run()
    assert lab.storage.stat(object_of(lab, attempt)) is None
    assert not has_files(lab, attempt)


async def test_an_object_path_that_holds_another_file_keeps_that_file(lab: Bench) -> None:
    attempt = await lab.sealed("a.cdf", WIND)
    await lab.publishing.attempts.cancel(CONTRIBUTOR, attempt.attempt_id)
    lab.storage.remove_file(object_of(lab, attempt))
    lab.storage.write_bytes(object_of(lab, attempt), b"other", 0o644)
    await lab.cleanup.run()
    assert lab.storage.read_bytes(object_of(lab, attempt)) == b"other"
    assert (await lab.publishing.stored(attempt.current_upload_id)).state is ObjectState.REMOVED
