"""Seals on the lake: the hook and the API's own check share one task for each upload ID."""

import asyncio
import errno
import hashlib
import threading
from collections.abc import AsyncIterator
from typing import Any

import pytest
import structlog

from huron.applications.api.disk import SEAL_WAIT, wait_for
from huron.core.lake.uploads.errors import UploadNotFound
from huron.core.lake.uploads.models import AttemptState, ObjectState
from huron.core.storage import UPLOADS, LakePath, StorageError
from huron.core.storage.memory import MemoryStorage
from huron.pkg.identifiers import new_id
from tests.support.clock import LoopClock, run_ready
from tests.support.disk import SIGNAL_TIMEOUT
from tests.support.lake import CONTRIBUTOR
from tests.support.orchestration import OBJECTS, Bench, bench, receive, tus_file
from tests.support.publication import TTL

DATA = b"solar wind, day one"


@pytest.fixture
async def lab() -> AsyncIterator[Bench]:
    async with bench() as built:
        yield built


def copies(storage: MemoryStorage) -> list[LakePath]:
    return [place for call, place in storage.calls if call == "copy"]


def pause_first(
    storage: MemoryStorage, monkeypatch: pytest.MonkeyPatch, method: str
) -> tuple[threading.Event, threading.Event]:
    """Make the first call of ``method`` wait until the second event is set.

    The first event is set when that call waits.
    """
    waiting, release = threading.Event(), threading.Event()
    real = getattr(storage, method)
    calls = 0

    def paused(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 1:
            waiting.set()
            assert release.wait(SIGNAL_TIMEOUT)
        return real(*args, **kwargs)

    monkeypatch.setattr(storage, method, paused)
    return waiting, release


async def test_the_hook_seals_a_complete_upload_into_the_object_area(lab: Bench) -> None:
    attempt = await lab.received("a.cdf", DATA)
    upload_id = attempt.current_upload_id
    ready = await lab.sealing.start(upload_id)
    stored = await lab.publishing.stored(upload_id)
    place = OBJECTS.joinpath(str(upload_id))
    found = lab.storage.stat(place)
    assert ready == await lab.publishing.attempt(attempt)
    assert ready.state is AttemptState.READY
    assert found is not None
    assert (stored.state, stored.path, stored.inode) == (
        ObjectState.SEALED,
        f"helio/.huron-objects/{upload_id}",
        found.inode,
    )
    assert (stored.size, stored.sha256) == (len(DATA), hashlib.sha256(DATA).hexdigest())
    assert lab.storage.read_bytes(place) == DATA


async def test_the_hook_seals_although_tusd_still_holds_the_lock_file(lab: Bench) -> None:
    attempt = await lab.publishing.receiving(CONTRIBUTOR, "a.cdf", DATA)
    receive(lab.storage, attempt.current_upload_id, DATA, locked=True)
    assert (await lab.sealing.start(attempt.current_upload_id)).state is AttemptState.READY


async def test_the_check_seals_a_complete_upload_that_no_hook_reported(lab: Bench) -> None:
    attempt = await lab.received("a.cdf", DATA)
    sealed = await lab.sealing.check(attempt.current_upload_id)
    assert sealed.state is AttemptState.READY
    assert lab.storage.read_bytes(OBJECTS.joinpath(str(attempt.current_upload_id))) == DATA


@pytest.mark.parametrize(
    ("files", "reason"),
    [
        ({"locked": True}, "locked"),
        ({"info": {"Size": 0, "SizeIsDeferred": True}}, "deferred"),
        ({"data": DATA[:-1]}, "incomplete"),
        ({"info": None, "data": None}, "no_info"),
    ],
)
async def test_the_check_skips_an_upload_that_is_not_complete(
    lab: Bench, files: dict[str, Any], reason: str
) -> None:
    attempt = await lab.publishing.receiving(CONTRIBUTOR, "a.cdf", DATA)
    upload_id = attempt.current_upload_id
    data = files.pop("data", DATA)
    if data is not None:
        receive(lab.storage, upload_id, DATA, **files)
        lab.storage.write_bytes(tus_file(upload_id), data, 0o600)
    with structlog.testing.capture_logs() as captured:
        skipped = await lab.sealing.check(upload_id)
    assert skipped == attempt
    assert await lab.publishing.attempt(attempt) == attempt
    assert copies(lab.storage) == []
    assert captured == [
        {
            "event": "seal.skipped",
            "log_level": "info",
            "upload_id": str(upload_id),
            "reason": reason,
        }
    ]


async def test_two_callers_get_one_seal(lab: Bench) -> None:
    attempt = await lab.received("a.cdf", DATA)
    upload_id = attempt.current_upload_id
    hook = lab.sealing.start(upload_id)
    check = lab.sealing.check(upload_id)
    assert check is hook
    assert lab.sealing.running(upload_id)
    assert (await hook).state is AttemptState.READY
    assert copies(lab.storage) == [OBJECTS.joinpath(str(upload_id))]
    assert (await lab.sealing.check(upload_id)).state is AttemptState.READY
    assert len(copies(lab.storage)) == 1


async def test_a_seal_that_a_stop_left_starts_again_over_its_partial_copy(lab: Bench) -> None:
    attempt = await lab.received("a.cdf", DATA)
    upload_id = attempt.current_upload_id
    seal = await lab.publishing.attempts.start_seal(upload_id)
    lab.storage.make_directory(OBJECTS, 0o700)
    lab.storage.write_bytes(OBJECTS.joinpath(str(upload_id)), DATA[:4], 0o644)
    sealed = await lab.sealing.check(upload_id)
    assert sealed.state is AttemptState.READY
    assert (await lab.publishing.stored(upload_id)).id == seal.stored.id
    assert lab.storage.read_bytes(OBJECTS.joinpath(str(upload_id))) == DATA


async def test_an_upload_id_that_is_not_current_is_never_sealed(lab: Bench) -> None:
    attempt = await lab.received("a.cdf", DATA)
    old = attempt.current_upload_id
    reissued = await lab.publishing.attempts.begin(
        CONTRIBUTOR, attempt.attempt_id, attempt.collection_id, "a.cdf", len(DATA)
    )
    assert (await lab.sealing.start(old)) == reissued
    assert (await lab.sealing.check(old)) == reissued
    assert copies(lab.storage) == []


async def test_an_attempt_that_ended_is_never_sealed(lab: Bench) -> None:
    attempt = await lab.received("a.cdf", DATA)
    cancelled = await lab.publishing.attempts.cancel(CONTRIBUTOR, attempt.attempt_id)
    assert (await lab.sealing.start(attempt.current_upload_id)) == cancelled
    assert copies(lab.storage) == []


async def test_an_attempt_that_lapsed_before_its_seal_starts_is_expired(lab: Bench) -> None:
    attempt = await lab.received("a.cdf", DATA)
    lab.publishing.clock.advance(TTL + TTL)
    sealed = await lab.sealing.start(attempt.current_upload_id)
    assert sealed.state is AttemptState.EXPIRED
    assert copies(lab.storage) == []


async def test_an_upload_id_that_huron_never_issued_is_not_found(
    lab: Bench, loop_errors: list[dict[str, object]]
) -> None:
    unknown = new_id()
    with structlog.testing.capture_logs() as captured, pytest.raises(UploadNotFound):
        await lab.sealing.check(unknown)
    await asyncio.sleep(0)
    assert [entry["event"] for entry in captured] == ["task.failed"]
    assert loop_errors == []


async def test_a_missing_upload_directory_leaves_the_upload_to_retry(lab: Bench) -> None:
    attempt = await lab.received("a.cdf", DATA)
    upload_id = attempt.current_upload_id
    lab.storage.remove_file(tus_file(upload_id))
    lab.storage.remove_file(tus_file(upload_id, ".info"))
    lab.storage.remove_directory(UPLOADS)
    for start in (lab.sealing.start, lab.sealing.check):
        with pytest.raises(StorageError) as refused:
            await start(upload_id)
        assert refused.value.context == {"path": ".tus-uploads"}
    assert await lab.publishing.attempt(attempt) == attempt
    lab.storage.make_directory(UPLOADS, 0o700)
    receive(lab.storage, upload_id, DATA)
    assert (await lab.sealing.start(upload_id)).state is AttemptState.READY


async def test_a_copy_that_fails_leaves_the_attempt_sealing_for_the_next_check(
    lab: Bench,
) -> None:
    attempt = await lab.received("a.cdf", DATA)
    upload_id = attempt.current_upload_id
    lab.storage.faults[("write", OBJECTS.joinpath(str(upload_id)))] = errno.ENOSPC
    with pytest.raises(StorageError):
        await lab.sealing.start(upload_id)
    assert (await lab.publishing.attempt(attempt)).state is AttemptState.SEALING
    assert (await lab.sealing.check(upload_id)).state is AttemptState.READY


async def test_a_hook_for_a_short_upload_starts_no_seal(lab: Bench) -> None:
    attempt = await lab.publishing.receiving(CONTRIBUTOR, "a.cdf", DATA)
    receive(lab.storage, attempt.current_upload_id, DATA)
    lab.storage.write_bytes(tus_file(attempt.current_upload_id), DATA[:-1], 0o600)
    assert await lab.sealing.start(attempt.current_upload_id) == attempt
    assert await lab.publishing.attempt(attempt) == attempt
    assert copies(lab.storage) == []


@pytest.mark.parametrize("checked", [False, True])
@pytest.mark.parametrize(
    ("data", "info", "received"),
    [(DATA + b"!", None, len(DATA) + 1), (DATA, {"Size": len(DATA) - 1}, len(DATA) - 1)],
)
async def test_files_that_can_never_get_the_declared_size_fail_the_attempt(
    lab: Bench, checked: bool, data: bytes, info: dict[str, Any] | None, received: int
) -> None:
    attempt = await lab.publishing.receiving(CONTRIBUTOR, "a.cdf", DATA)
    upload_id = attempt.current_upload_id
    receive(lab.storage, upload_id, DATA, info=info)
    lab.storage.write_bytes(tus_file(upload_id), data, 0o600)
    failed = await (lab.sealing.check if checked else lab.sealing.start)(upload_id)
    assert failed.state is AttemptState.FAILED
    assert failed.failure is not None and failed.failure.code == "UPLOAD_SIZE_MISMATCH"
    assert failed.failure.message.endswith(f"the file has {received} bytes")
    assert copies(lab.storage) == []


async def test_a_hook_during_a_check_that_sees_the_lock_file_seals_the_upload(
    lab: Bench, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempt = await lab.publishing.receiving(CONTRIBUTOR, "a.cdf", DATA)
    upload_id = attempt.current_upload_id
    receive(lab.storage, upload_id, DATA, locked=True)
    reading, release = pause_first(lab.storage, monkeypatch, "read_bytes")
    check = lab.sealing.check(upload_id)
    assert await asyncio.to_thread(reading.wait, SIGNAL_TIMEOUT)
    hook = lab.sealing.start(upload_id)
    assert hook is not check
    assert lab.sealing.running(upload_id)
    release.set()
    assert await check == attempt
    sealed = await hook
    assert sealed.state is AttemptState.READY
    assert sealed == await lab.publishing.attempt(attempt)
    assert copies(lab.storage) == [OBJECTS.joinpath(str(upload_id))]


async def test_a_check_and_a_hook_during_a_seal_join_that_seal(
    lab: Bench, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempt = await lab.received("a.cdf", DATA)
    upload_id = attempt.current_upload_id
    copying, release = pause_first(lab.storage, monkeypatch, "copy_sealed")
    hook = lab.sealing.start(upload_id)
    assert await asyncio.to_thread(copying.wait, SIGNAL_TIMEOUT)
    assert lab.sealing.check(upload_id) is hook
    assert lab.sealing.start(upload_id) is hook
    release.set()
    assert (await hook).state is AttemptState.READY
    assert len(copies(lab.storage)) == 1


async def test_two_checks_join_one_check_and_its_seal_takes_a_hook(
    lab: Bench, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempt = await lab.received("a.cdf", DATA)
    upload_id = attempt.current_upload_id
    copying, release = pause_first(lab.storage, monkeypatch, "copy_sealed")
    check = lab.sealing.check(upload_id)
    assert lab.sealing.check(upload_id) is check
    assert await asyncio.to_thread(copying.wait, SIGNAL_TIMEOUT)
    hook = lab.sealing.start(upload_id)
    assert lab.sealing.check(upload_id) is hook
    release.set()
    assert (await check) == (await hook)
    assert (await hook).state is AttemptState.READY
    assert len(copies(lab.storage)) == 1


async def test_a_seal_that_a_check_started_goes_on_when_the_check_is_cancelled(
    lab: Bench, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempt = await lab.received("a.cdf", DATA)
    upload_id = attempt.current_upload_id
    copying, release = pause_first(lab.storage, monkeypatch, "copy_sealed")
    check = lab.sealing.check(upload_id)
    assert await asyncio.to_thread(copying.wait, SIGNAL_TIMEOUT)
    seal = lab.sealing.start(upload_id)
    check.cancel()
    release.set()
    assert (await seal).state is AttemptState.READY
    assert check.cancelled()


async def test_the_seal_goes_on_when_its_caller_stops_waiting(
    lab: Bench, loop_clock: LoopClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempt = await lab.received("a.cdf", DATA)
    copying, release = pause_first(lab.storage, monkeypatch, "copy_sealed")
    task = lab.sealing.start(attempt.current_upload_id)
    waiting = asyncio.create_task(wait_for(task, SEAL_WAIT))
    assert await asyncio.to_thread(copying.wait, SIGNAL_TIMEOUT)
    loop_clock.advance(SEAL_WAIT)
    assert await waiting is None
    caller = asyncio.create_task(wait_for(task, SEAL_WAIT))
    await asyncio.sleep(0)
    caller.cancel()
    release.set()
    assert (await task).state is AttemptState.READY


async def test_the_seal_wait_is_twenty_seconds() -> None:
    assert SEAL_WAIT == 20.0


async def test_settling_no_uploads_returns_at_once(lab: Bench, loop_clock: LoopClock) -> None:
    settling = asyncio.create_task(lab.sealing.settle([], SEAL_WAIT))
    await asyncio.sleep(0)
    assert settling.done()
    assert await settling is None
    assert copies(lab.storage) == []


async def test_settling_returns_when_every_check_ends_before_the_wait(
    lab: Bench, loop_clock: LoopClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = await lab.received("a.cdf", DATA)
    second = await lab.received("b.cdf", DATA)
    upload_ids = [first.current_upload_id, second.current_upload_id]
    copying, release = pause_first(lab.storage, monkeypatch, "copy_sealed")
    settling = asyncio.create_task(lab.sealing.settle(upload_ids, SEAL_WAIT))
    assert await asyncio.to_thread(copying.wait, SIGNAL_TIMEOUT)
    seals = {lab.sealing.check(upload_id) for upload_id in upload_ids}
    ended, going = await asyncio.wait(seals, return_when=asyncio.FIRST_COMPLETED)
    assert (len(ended), len(going)) == (1, 1)
    assert ended.pop().result().state is AttemptState.READY
    loop_clock.advance(SEAL_WAIT - 0.001)
    await run_ready()
    assert not settling.done()
    release.set()
    assert await asyncio.wait_for(settling, SIGNAL_TIMEOUT) is None
    for attempt in (first, second):
        assert (await lab.publishing.attempt(attempt)).state is AttemptState.READY
        assert not lab.sealing.running(attempt.current_upload_id)


async def test_settling_stops_waiting_after_its_timeout_and_the_seal_goes_on(
    lab: Bench, loop_clock: LoopClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempt = await lab.received("a.cdf", DATA)
    upload_id = attempt.current_upload_id
    copying, release = pause_first(lab.storage, monkeypatch, "copy_sealed")
    settling = asyncio.create_task(lab.sealing.settle([upload_id], SEAL_WAIT))
    assert await asyncio.to_thread(copying.wait, SIGNAL_TIMEOUT)
    loop_clock.advance(SEAL_WAIT - 0.001)
    await run_ready()
    assert not settling.done()
    loop_clock.advance(0.001)
    await run_ready()
    assert settling.done()
    assert settling.result() is None
    assert lab.sealing.running(upload_id)
    assert (await lab.publishing.attempt(attempt)).state is AttemptState.SEALING
    release.set()
    assert (await lab.sealing.check(upload_id)).state is AttemptState.READY
    assert lab.storage.read_bytes(OBJECTS.joinpath(str(upload_id))) == DATA


async def test_settling_cancels_no_check_that_its_timeout_finds_before_the_seal(
    lab: Bench, loop_clock: LoopClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempt = await lab.received("a.cdf", DATA)
    upload_id = attempt.current_upload_id
    reading, release = pause_first(lab.storage, monkeypatch, "read_bytes")
    settling = asyncio.create_task(lab.sealing.settle([upload_id], SEAL_WAIT))
    assert await asyncio.to_thread(reading.wait, SIGNAL_TIMEOUT)
    check = lab.sealing.check(upload_id)
    loop_clock.advance(SEAL_WAIT)
    await run_ready()
    assert settling.done()
    assert settling.result() is None
    assert (await lab.publishing.attempt(attempt)).state is AttemptState.RECEIVING
    assert copies(lab.storage) == []
    release.set()
    await asyncio.wait({check})
    assert not check.cancelled()
    assert check.result().state is AttemptState.READY
    assert lab.storage.read_bytes(OBJECTS.joinpath(str(upload_id))) == DATA


async def test_has_info_tells_whether_tusd_made_the_info_file(lab: Bench) -> None:
    attempt = await lab.received("a.cdf", DATA)
    assert await lab.sealing.has_info(attempt.current_upload_id) is True
    assert await lab.sealing.has_info(new_id()) is False
