"""Upload attempt operations: the creation cases, the seal, cancel and expiry, on both stores."""

import uuid
from dataclasses import replace
from datetime import timedelta

import pytest

from huron.core.lake.errors import NameTaken
from huron.core.lake.uploads import attempts as attempts_module
from huron.core.lake.uploads.attempts import Attempts
from huron.core.lake.uploads.errors import (
    AttemptIdConflict,
    CapacityExceeded,
    IneligibleReason,
    UploadAttemptRefused,
    UploadIneligible,
    UploadNotFound,
    UploadTooLarge,
)
from huron.core.lake.uploads.models import AttemptState, Failure, ObjectState, UploadAttempt
from huron.core.security.rbac import Actor
from huron.pkg.errors import Conflict, Forbidden, Invalid, NotFound
from huron.pkg.identifiers import new_id
from huron.schema.naming import RelPathError
from tests.support.clock import START
from tests.support.lake import CONTRIBUTOR, OTHER_CONTRIBUTOR, READER, STRANGER, VALID_METADATA
from tests.support.publication import OBJECT_DIR, TTL, Publishing, sha256

DATA = b"solar wind, day one"
ATTEMPT_ID = uuid.UUID("0190d5a4-0000-7000-8000-00000000000a")


async def begin(
    publishing: Publishing,
    *,
    actor: Actor = CONTRIBUTOR,
    collection_id: uuid.UUID | None = None,
    rel_path: str = "solar/day1.cdf",
    size: int = len(DATA),
    with_info: uuid.UUID | None = None,
) -> UploadAttempt:
    """``begin`` of the attempt :data:`ATTEMPT_ID` for :data:`DATA` in the collection."""
    return await publishing.attempts.begin(
        actor,
        ATTEMPT_ID,
        collection_id or publishing.collection_id,
        rel_path,
        size,
        with_info=with_info,
    )


def limited(publishing: Publishing, **limits: int) -> Attempts:
    """The attempts of ``publishing`` with capacity limits."""
    return Attempts(publishing.store, publishing.clock, ttl=TTL, object_dir=OBJECT_DIR, **limits)


# The creation cases.


async def test_a_first_creation_makes_a_receiving_attempt_with_one_new_upload_id(
    publishing: Publishing,
) -> None:
    attempt = await begin(publishing)
    assert (attempt.subject, attempt.attempt_id, attempt.collection_id) == (
        CONTRIBUTOR.subject,
        ATTEMPT_ID,
        publishing.collection_id,
    )
    assert (attempt.rel_path, attempt.size, attempt.state) == (
        "solar/day1.cdf",
        len(DATA),
        AttemptState.RECEIVING,
    )
    assert attempt.upload_ids == (attempt.current_upload_id,)
    assert (attempt.created_at, attempt.active_at) == (START, START)
    assert attempt.commit_request_id is None
    assert await publishing.attempt(attempt) == attempt


async def test_a_creation_with_other_fields_is_an_attempt_id_conflict(
    publishing: Publishing,
) -> None:
    first = await begin(publishing)
    with pytest.raises(AttemptIdConflict) as raised:
        await begin(publishing, size=len(DATA) + 1)
    assert (raised.value.code, raised.value.status) == ("ATTEMPT_ID_CONFLICT", 409)
    assert raised.value.context == {"attempt_id": str(ATTEMPT_ID)}
    assert await publishing.attempt(first) == first


async def test_a_receiving_attempt_whose_current_id_has_an_info_file_names_that_id(
    publishing: Publishing,
) -> None:
    first = await begin(publishing)
    with pytest.raises(UploadAttemptRefused) as raised:
        await begin(publishing, with_info=first.current_upload_id)
    assert (raised.value.state, raised.value.upload_id) == (
        AttemptState.RECEIVING,
        first.current_upload_id,
    )
    assert await publishing.attempt(first) == first


async def test_a_receiving_attempt_without_an_info_file_gets_a_new_current_id(
    publishing: Publishing,
) -> None:
    first = await begin(publishing)
    second = await begin(publishing)
    third = await begin(publishing, with_info=first.current_upload_id)
    assert second.current_upload_id not in first.upload_ids
    assert set(second.upload_ids) == {first.current_upload_id, second.current_upload_id}
    assert third.current_upload_id not in second.upload_ids
    assert len(set(third.upload_ids)) == 3
    assert (third.id, third.state) == (first.id, AttemptState.RECEIVING)
    assert await publishing.attempt(first) == third


@pytest.mark.parametrize("state", [AttemptState.SEALING, AttemptState.READY, AttemptState.CONSUMED])
async def test_a_sealing_ready_or_consumed_attempt_is_refused_with_its_state_and_upload(
    publishing: Publishing, state: AttemptState
) -> None:
    attempt = await begin(publishing)
    await publishing.attempts.start_seal(attempt.current_upload_id)
    if state is not AttemptState.SEALING:
        attempt = await publishing.attempts.finish_seal(
            attempt.current_upload_id, len(DATA), sha256(DATA), 7
        )
    if state is AttemptState.CONSUMED:
        request = publishing.request(2, [(attempt, DATA)])
        await publishing.publish(await publishing.publications.submit(CONTRIBUTOR, request))
    with pytest.raises(UploadAttemptRefused) as raised:
        await begin(publishing)
    assert (raised.value.state, raised.value.upload_id) == (state, attempt.current_upload_id)
    assert (await publishing.attempt(attempt)).upload_ids == attempt.upload_ids


@pytest.mark.parametrize(
    "state", [AttemptState.FAILED, AttemptState.CANCELLED, AttemptState.EXPIRED]
)
async def test_an_ended_attempt_is_refused_with_its_state_only(
    publishing: Publishing, state: AttemptState
) -> None:
    attempt = await begin(publishing)
    if state is AttemptState.FAILED:
        await publishing.attempts.start_seal(attempt.current_upload_id)
        await publishing.attempts.finish_seal(attempt.current_upload_id, 1, sha256(b"x"), 7)
    elif state is AttemptState.CANCELLED:
        await publishing.attempts.cancel(CONTRIBUTOR, ATTEMPT_ID)
    else:
        publishing.clock.advance(TTL + timedelta(seconds=1))
        await publishing.attempts.expire()
    with pytest.raises(UploadAttemptRefused) as raised:
        await begin(publishing)
    assert (raised.value.state, raised.value.upload_id) == (state, None)
    assert (await publishing.attempt(attempt)).upload_ids == attempt.upload_ids


async def test_an_upload_id_that_huron_issued_is_never_issued_again(
    publishing: Publishing, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = await begin(publishing)
    monkeypatch.setattr(attempts_module, "new_id", lambda: first.current_upload_id)
    with pytest.raises(NameTaken):
        await begin(publishing)
    assert await publishing.attempt(first) == first


async def test_a_receiving_attempt_past_the_ttl_is_expired_by_a_creation(
    publishing: Publishing,
) -> None:
    attempt = await begin(publishing)
    publishing.clock.advance(TTL + timedelta(microseconds=1))
    with pytest.raises(UploadAttemptRefused) as raised:
        await begin(publishing)
    assert raised.value.state is AttemptState.EXPIRED
    assert (await publishing.attempt(attempt)).state is AttemptState.EXPIRED


async def test_a_receiving_attempt_at_the_ttl_is_not_expired(publishing: Publishing) -> None:
    attempt = await begin(publishing)
    publishing.clock.advance(TTL)
    again = await begin(publishing)
    assert (again.state, len(again.upload_ids)) == (AttemptState.RECEIVING, 2)
    assert again.id == attempt.id


async def test_a_creation_needs_the_right_to_write_to_a_settled_collection(
    publishing: Publishing,
) -> None:
    with pytest.raises(Forbidden):
        await begin(publishing, actor=READER)
    with pytest.raises(NotFound):
        await begin(publishing, actor=STRANGER)
    with pytest.raises(NotFound):
        await begin(publishing, collection_id=uuid.uuid4())
    draft = await publishing.lake.collections.create(
        CONTRIBUTOR, "heliophysics", "solar-wind", "draft", dict(VALID_METADATA)
    )
    with pytest.raises(Conflict) as raised:
        await begin(publishing, collection_id=draft.collection.id)
    assert raised.value.message == "you can upload files only to an active or incomplete collection"


async def test_a_creation_refuses_a_bad_path_and_a_negative_size(publishing: Publishing) -> None:
    with pytest.raises(RelPathError) as bad_path:
        await begin(publishing, rel_path="../escape")
    assert bad_path.value.rule == "rel_path_separator"
    with pytest.raises(RelPathError) as long_name:
        await begin(publishing, rel_path="d/" + "n" * 207)
    assert long_name.value.rule == "rel_path_segment"
    with pytest.raises(Invalid) as raised:
        await begin(publishing, size=-1)
    assert raised.value.context == {"size": -1}
    with pytest.raises(NotFound):
        await publishing.attempts.get(CONTRIBUTOR, ATTEMPT_ID)


async def test_a_creation_takes_an_empty_file_and_any_size_without_a_maximum(
    publishing: Publishing,
) -> None:
    empty = await publishing.attempts.begin(
        CONTRIBUTOR, new_id(), publishing.collection_id, "empty", 0
    )
    huge = await publishing.attempts.begin(
        CONTRIBUTOR, new_id(), publishing.collection_id, "huge", 2**50
    )
    assert (empty.size, huge.size) == (0, 2**50)


async def test_a_creation_larger_than_the_maximum_upload_is_refused(publishing: Publishing) -> None:
    attempts = limited(publishing, max_upload_bytes=100)
    largest = await attempts.begin(CONTRIBUTOR, new_id(), publishing.collection_id, "a", 100)
    assert largest.size == 100
    with pytest.raises(UploadTooLarge) as raised:
        await attempts.begin(CONTRIBUTOR, new_id(), publishing.collection_id, "b", 101)
    assert raised.value.context == {"size": 101, "maximum": 100}


async def test_staged_bytes_count_two_times_against_the_staged_limit(
    publishing: Publishing,
) -> None:
    attempts = limited(publishing, max_staged_bytes=100)
    first = await attempts.begin(CONTRIBUTOR, ATTEMPT_ID, publishing.collection_id, "a", 50)
    with pytest.raises(CapacityExceeded) as raised:
        await attempts.begin(CONTRIBUTOR, new_id(), publishing.collection_id, "b", 1)
    assert raised.value.context == {"limit": "max_staged_bytes", "requested": 2, "available": 0}
    again = await attempts.begin(CONTRIBUTOR, ATTEMPT_ID, publishing.collection_id, "a", 50)
    assert len(again.upload_ids) == 2
    await attempts.cancel(CONTRIBUTOR, first.attempt_id)
    second = await attempts.begin(CONTRIBUTOR, new_id(), publishing.collection_id, "b", 50)
    assert second.state is AttemptState.RECEIVING


async def test_a_refused_creation_for_capacity_stores_no_attempt(publishing: Publishing) -> None:
    attempts = limited(publishing, max_staged_bytes=10)
    with pytest.raises(CapacityExceeded) as raised:
        await attempts.begin(CONTRIBUTOR, ATTEMPT_ID, publishing.collection_id, "a", 6)
    assert raised.value.context == {"limit": "max_staged_bytes", "requested": 12, "available": 10}
    with pytest.raises(NotFound):
        await publishing.attempts.get(CONTRIBUTOR, ATTEMPT_ID)


# The seal.


async def test_a_seal_starts_for_the_current_id_of_a_receiving_attempt(
    publishing: Publishing,
) -> None:
    attempt = await begin(publishing)
    seal = await publishing.attempts.start_seal(attempt.current_upload_id)
    assert seal.attempt == replace(attempt, state=AttemptState.SEALING)
    assert (seal.upload_id, seal.size) == (attempt.current_upload_id, len(DATA))
    assert seal.stored.path == f"helio/{OBJECT_DIR}/{attempt.current_upload_id}"
    assert (seal.stored.state, seal.stored.created_at) == (ObjectState.SEALING, START)
    assert await publishing.attempt(attempt) == seal.attempt
    assert await publishing.stored(attempt.current_upload_id) == seal.stored


async def test_a_seal_of_an_id_that_is_not_current_is_refused(publishing: Publishing) -> None:
    first = await begin(publishing)
    second = await begin(publishing)
    with pytest.raises(UploadIneligible) as raised:
        await publishing.attempts.start_seal(first.current_upload_id)
    assert (raised.value.reason, raised.value.state) == (
        IneligibleReason.SUPERSEDED,
        AttemptState.RECEIVING,
    )
    assert await publishing.attempt(first) == second
    assert raised.value.message == (
        f"upload {first.current_upload_id} is not the current upload of its attempt."
        " Huron cannot start a seal of it. Read the upload attempt"
    )


async def test_a_seal_of_an_id_that_huron_never_issued_is_not_found(
    publishing: Publishing,
) -> None:
    unknown = new_id()
    with pytest.raises(UploadNotFound):
        await publishing.attempts.start_seal(unknown)
    with pytest.raises(UploadNotFound):
        await publishing.attempts.finish_seal(unknown, 1, sha256(b"x"), 7)


async def test_a_sealing_attempt_starts_a_new_seal_only_without_a_task(
    publishing: Publishing,
) -> None:
    attempt = await begin(publishing)
    first = await publishing.attempts.start_seal(attempt.current_upload_id)
    with pytest.raises(UploadIneligible) as raised:
        await publishing.attempts.start_seal(attempt.current_upload_id)
    assert (raised.value.reason, raised.value.state) == (
        IneligibleReason.STATE,
        AttemptState.SEALING,
    )
    again = await publishing.attempts.start_seal(attempt.current_upload_id, orphaned=True)
    assert again == first


async def test_a_seal_of_a_ready_attempt_is_refused(publishing: Publishing) -> None:
    attempt = await publishing.ready(CONTRIBUTOR, "a", DATA)
    with pytest.raises(UploadIneligible) as raised:
        await publishing.attempts.start_seal(attempt.current_upload_id, orphaned=True)
    assert raised.value.state is AttemptState.READY
    assert raised.value.message == (
        f"upload {attempt.current_upload_id} is ready. Huron cannot start a seal of it."
        " Read the upload attempt"
    )


@pytest.mark.parametrize("sealing", [False, True])
async def test_a_receiving_or_sealing_attempt_past_the_ttl_is_expired_by_a_seal(
    publishing: Publishing, sealing: bool
) -> None:
    attempt = await begin(publishing)
    if sealing:
        await publishing.attempts.start_seal(attempt.current_upload_id)
    publishing.clock.advance(TTL + timedelta(microseconds=1))
    with pytest.raises(UploadIneligible) as raised:
        await publishing.attempts.start_seal(attempt.current_upload_id, orphaned=True)
    assert raised.value.state is AttemptState.EXPIRED
    assert (await publishing.attempt(attempt)).state is AttemptState.EXPIRED


async def test_a_seal_for_a_deleted_collection_is_not_found(publishing: Publishing) -> None:
    attempt = await begin(publishing)
    await publishing.lake.collections.delete(CONTRIBUTOR, publishing.collection_id, 2)
    with pytest.raises(NotFound) as raised:
        await publishing.attempts.start_seal(attempt.current_upload_id)
    assert raised.value.context == {"upload_id": str(attempt.current_upload_id)}
    assert (await publishing.attempt(attempt)).state is AttemptState.RECEIVING


async def test_the_end_of_a_seal_makes_the_attempt_ready_with_its_measured_object(
    publishing: Publishing,
) -> None:
    attempt = await begin(publishing)
    await publishing.attempts.start_seal(attempt.current_upload_id)
    publishing.clock.advance(timedelta(minutes=5))
    ready = await publishing.attempts.finish_seal(
        attempt.current_upload_id, len(DATA), sha256(DATA), 2**64 - 1
    )
    later = START + timedelta(minutes=5)
    assert ready == replace(attempt, state=AttemptState.READY, active_at=later)
    stored = await publishing.stored(attempt.current_upload_id)
    assert (stored.state, stored.size, stored.sha256, stored.inode, stored.sealed_at) == (
        ObjectState.SEALED,
        len(DATA),
        sha256(DATA),
        2**64 - 1,
        START + timedelta(minutes=5),
    )
    assert await publishing.attempt(attempt) == ready


async def test_a_seal_that_ends_two_times_changes_nothing_the_second_time(
    publishing: Publishing,
) -> None:
    attempt = await publishing.ready(CONTRIBUTOR, "a", DATA)
    stored = await publishing.stored(attempt.current_upload_id)
    again = await publishing.attempts.finish_seal(attempt.current_upload_id, 1, sha256(b"x"), 9)
    assert again == attempt
    assert await publishing.stored(attempt.current_upload_id) == stored


async def test_a_seal_with_a_copy_of_another_size_fails_the_attempt(
    publishing: Publishing,
) -> None:
    attempt = await begin(publishing)
    await publishing.attempts.start_seal(attempt.current_upload_id)
    failed = await publishing.attempts.finish_seal(attempt.current_upload_id, 3, sha256(b"abc"), 7)
    assert failed.state is AttemptState.FAILED
    assert failed.failure == Failure(
        "UPLOAD_SIZE_MISMATCH",
        f"the upload declared {len(DATA)} bytes, but the file has 3 bytes",
    )
    assert await publishing.attempt(attempt) == failed


async def test_a_seal_that_ends_after_a_cancel_leaves_the_attempt_cancelled(
    publishing: Publishing,
) -> None:
    attempt = await begin(publishing)
    await publishing.attempts.start_seal(attempt.current_upload_id)
    cancelled = await publishing.attempts.cancel(CONTRIBUTOR, ATTEMPT_ID)
    late = await publishing.attempts.finish_seal(
        attempt.current_upload_id, len(DATA), sha256(DATA), 7
    )
    assert late == cancelled
    assert late.state is AttemptState.CANCELLED
    assert (await publishing.stored(attempt.current_upload_id)).state is ObjectState.SEALED


async def test_a_cancel_after_the_end_of_a_seal_cancels_the_ready_attempt(
    publishing: Publishing,
) -> None:
    attempt = await publishing.ready(CONTRIBUTOR, "a", DATA)
    cancelled = await publishing.attempts.cancel(CONTRIBUTOR, attempt.attempt_id)
    assert cancelled == replace(attempt, state=AttemptState.CANCELLED)


async def test_a_seal_that_ends_after_an_expiry_leaves_the_attempt_expired(
    publishing: Publishing,
) -> None:
    attempt = await begin(publishing)
    await publishing.attempts.start_seal(attempt.current_upload_id)
    publishing.clock.advance(TTL + timedelta(seconds=1))
    await publishing.attempts.expire()
    late = await publishing.attempts.finish_seal(
        attempt.current_upload_id, len(DATA), sha256(DATA), 7
    )
    assert (late.state, late.active_at) == (AttemptState.EXPIRED, START)


# Cancel, expiry and reads.


async def test_a_cancel_of_an_ended_attempt_changes_nothing(publishing: Publishing) -> None:
    await begin(publishing)
    first = await publishing.attempts.cancel(CONTRIBUTOR, ATTEMPT_ID)
    assert await publishing.attempts.cancel(CONTRIBUTOR, ATTEMPT_ID) == first


async def test_a_cancel_of_an_attempt_that_a_commit_uses_is_refused(
    publishing: Publishing,
) -> None:
    held = await publishing.ready(CONTRIBUTOR, "held", DATA)
    outcome = await publishing.publications.submit(
        CONTRIBUTOR, publishing.request(2, [(held, DATA)])
    )
    with pytest.raises(Conflict) as raised:
        await publishing.attempts.cancel(CONTRIBUTOR, held.attempt_id)
    assert raised.value.context == {
        "attempt_id": str(held.attempt_id),
        "state": "ready",
        "allowed": ["receiving", "sealing"],
    }
    assert raised.value.message == (
        "a commit uses the upload attempt. You can cancel only an attempt that no commit uses"
    )
    await publishing.publish(outcome)
    with pytest.raises(Conflict) as consumed:
        await publishing.attempts.cancel(CONTRIBUTOR, held.attempt_id)
    assert consumed.value.context["state"] == "consumed"


async def test_a_cancel_and_a_read_of_another_actors_attempt_are_not_found(
    publishing: Publishing,
) -> None:
    attempt = await begin(publishing)
    with pytest.raises(NotFound) as raised:
        await publishing.attempts.cancel(OTHER_CONTRIBUTOR, ATTEMPT_ID)
    assert raised.value.context == {"attempt_id": str(ATTEMPT_ID)}
    with pytest.raises(NotFound):
        await publishing.attempts.get(OTHER_CONTRIBUTOR, ATTEMPT_ID)
    assert await publishing.attempts.get(CONTRIBUTOR, ATTEMPT_ID) == attempt


async def test_expiry_ends_receiving_sealing_and_free_ready_attempts_past_the_ttl(
    publishing: Publishing,
) -> None:
    receiving = await publishing.receiving(CONTRIBUTOR, "receiving", DATA)
    sealing = await publishing.receiving(CONTRIBUTOR, "sealing", DATA)
    await publishing.attempts.start_seal(sealing.current_upload_id)
    ready = await publishing.ready(CONTRIBUTOR, "ready", DATA)
    held = await publishing.ready(CONTRIBUTOR, "held", DATA)
    await publishing.publications.submit(CONTRIBUTOR, publishing.request(2, [(held, DATA)]))
    publishing.clock.advance(TTL + timedelta(microseconds=1))
    expired = await publishing.attempts.expire()
    assert {attempt.rel_path for attempt in expired} == {"receiving", "sealing", "ready"}
    assert all(attempt.state is AttemptState.EXPIRED for attempt in expired)
    for attempt in (receiving, sealing, ready):
        assert (await publishing.attempt(attempt)).state is AttemptState.EXPIRED
    assert (await publishing.attempt(held)).state is AttemptState.READY


async def test_expiry_at_the_boundary_of_the_ttl(publishing: Publishing) -> None:
    attempt = await begin(publishing)
    publishing.clock.advance(TTL)
    assert await publishing.attempts.expire() == []
    publishing.clock.advance(timedelta(microseconds=1))
    assert await publishing.attempts.expire() == [replace(attempt, state=AttemptState.EXPIRED)]
    assert await publishing.attempts.expire() == []


async def test_expiry_takes_at_most_the_limit_the_oldest_activity_first(
    publishing: Publishing,
) -> None:
    older = await publishing.receiving(CONTRIBUTOR, "older", DATA)
    publishing.clock.advance(timedelta(seconds=1))
    await publishing.receiving(CONTRIBUTOR, "newer", DATA)
    publishing.clock.advance(TTL + timedelta(seconds=1))
    assert [attempt.id for attempt in await publishing.attempts.expire(1)] == [older.id]
    assert [attempt.rel_path for attempt in await publishing.attempts.expire(1)] == ["newer"]


# A failed upload.


async def test_fail_ends_a_receiving_or_sealing_attempt_with_the_size_mismatch(
    publishing: Publishing,
) -> None:
    receiving = await begin(publishing)
    failed = await publishing.attempts.fail(receiving.current_upload_id, len(DATA) + 3)
    message = f"the upload declared {len(DATA)} bytes, but the file has {len(DATA) + 3} bytes"
    assert failed == replace(
        receiving,
        state=AttemptState.FAILED,
        failure=Failure("UPLOAD_SIZE_MISMATCH", message),
    )
    assert await publishing.attempt(receiving) == failed
    sealing = await publishing.receiving(CONTRIBUTOR, "b.cdf", DATA)
    await publishing.attempts.start_seal(sealing.current_upload_id)
    ended = await publishing.attempts.fail(sealing.current_upload_id, 0)
    assert ended.state is AttemptState.FAILED


async def test_fail_leaves_another_state_and_an_id_that_is_not_current(
    publishing: Publishing,
) -> None:
    first = await begin(publishing)
    current = await begin(publishing)
    assert await publishing.attempts.fail(first.current_upload_id, 1) == current
    ready = await publishing.ready(CONTRIBUTOR, "b.cdf", DATA)
    assert await publishing.attempts.fail(ready.current_upload_id, 1) == ready
    assert await publishing.attempt(current) == current
    unknown = new_id()
    with pytest.raises(UploadNotFound) as missing:
        await publishing.attempts.fail(unknown, 1)
    assert missing.value.context == {"upload": str(unknown)}


# The reads and the activity of the upload proxy's authorization.


async def test_find_reads_the_attempt_of_any_issued_upload_id(publishing: Publishing) -> None:
    first = await begin(publishing)
    reissued = await begin(publishing)
    assert await publishing.attempts.find(first.current_upload_id) == reissued
    assert await publishing.attempts.find(reissued.current_upload_id) == reissued
    with pytest.raises(UploadNotFound) as missing:
        await publishing.attempts.find(ATTEMPT_ID)
    assert missing.value.context == {"upload": str(ATTEMPT_ID)}


async def test_only_the_owner_sends_bytes_to_the_current_id_of_a_receiving_attempt(
    publishing: Publishing,
) -> None:
    first = await begin(publishing)
    reissued = await begin(publishing)
    accepts = publishing.attempts.accepts
    assert await accepts(CONTRIBUTOR, reissued.current_upload_id) is True
    assert await accepts(OTHER_CONTRIBUTOR, reissued.current_upload_id) is False
    assert await accepts(CONTRIBUTOR, first.current_upload_id) is False
    assert await accepts(CONTRIBUTOR, new_id()) is False
    await publishing.seal(reissued, DATA)
    assert await accepts(CONTRIBUTOR, reissued.current_upload_id) is False


async def test_a_lapsed_attempt_takes_no_bytes_and_the_read_changes_nothing(
    publishing: Publishing,
) -> None:
    attempt = await begin(publishing)
    publishing.clock.advance(TTL)
    assert await publishing.attempts.accepts(CONTRIBUTOR, attempt.current_upload_id) is True
    publishing.clock.advance(timedelta(microseconds=1))
    assert await publishing.attempts.accepts(CONTRIBUTOR, attempt.current_upload_id) is False
    assert (await publishing.attempt(attempt)).state is AttemptState.RECEIVING


async def test_touch_records_activity_on_the_current_id_of_a_receiving_attempt(
    publishing: Publishing,
) -> None:
    attempt = await begin(publishing)
    publishing.clock.advance(timedelta(days=6))
    assert await publishing.attempts.touch(attempt.current_upload_id) is True
    touched = await publishing.attempt(attempt)
    assert touched == replace(attempt, active_at=START + timedelta(days=6))
    publishing.clock.advance(timedelta(days=6))
    assert await publishing.attempts.accepts(CONTRIBUTOR, attempt.current_upload_id) is True


async def test_touch_gives_no_activity_to_an_id_that_is_not_current_or_not_receiving(
    publishing: Publishing,
) -> None:
    first = await begin(publishing)
    reissued = await begin(publishing)
    publishing.clock.advance(timedelta(hours=1))
    assert await publishing.attempts.touch(first.current_upload_id) is False
    assert await publishing.attempt(reissued) == reissued
    sealed = await publishing.seal(reissued, DATA)
    assert await publishing.attempts.touch(reissued.current_upload_id) is False
    assert await publishing.attempt(sealed) == sealed
    with pytest.raises(UploadNotFound):
        await publishing.attempts.touch(new_id())


async def test_touch_expires_a_lapsed_attempt(publishing: Publishing) -> None:
    attempt = await begin(publishing)
    publishing.clock.advance(TTL + timedelta(microseconds=1))
    assert await publishing.attempts.touch(attempt.current_upload_id) is False
    assert (await publishing.attempt(attempt)).state is AttemptState.EXPIRED


async def test_unsealed_names_the_current_ids_of_receiving_and_sealing_attempts(
    publishing: Publishing,
) -> None:
    receiving = await publishing.receiving(CONTRIBUTOR, "a", DATA)
    sealing = await publishing.receiving(CONTRIBUTOR, "b", DATA)
    await publishing.attempts.start_seal(sealing.current_upload_id)
    ready = await publishing.ready(CONTRIBUTOR, "c", DATA)
    first = await begin(publishing)
    await begin(publishing)
    named = [
        ready.current_upload_id,
        sealing.current_upload_id,
        first.current_upload_id,
        new_id(),
        receiving.current_upload_id,
    ]
    assert await publishing.attempts.unsealed(CONTRIBUTOR, named) == [
        sealing.current_upload_id,
        receiving.current_upload_id,
    ]
    assert await publishing.attempts.unsealed(CONTRIBUTOR, []) == []


async def test_unsealed_names_no_upload_of_another_actor(publishing: Publishing) -> None:
    foreign = await publishing.receiving(OTHER_CONTRIBUTOR, "a", DATA)
    own = await publishing.receiving(CONTRIBUTOR, "b", DATA)
    named = [foreign.current_upload_id, own.current_upload_id]
    assert await publishing.attempts.unsealed(CONTRIBUTOR, named) == [own.current_upload_id]
    assert await publishing.attempts.unsealed(OTHER_CONTRIBUTOR, named) == [
        foreign.current_upload_id
    ]


@pytest.mark.parametrize(("size", "error"), [(-1, Invalid), (11, UploadTooLarge)])
async def test_check_size_refuses_a_size_that_can_never_start(
    publishing: Publishing, size: int, error: type[Exception]
) -> None:
    attempts = limited(publishing, max_upload_bytes=10)
    with pytest.raises(error):
        attempts.check_size(size)
    attempts.check_size(0)
    attempts.check_size(10)


def test_an_attempt_renders_its_state_and_current_upload_id_for_its_owner() -> None:
    upload_id = new_id()
    attempt = UploadAttempt(
        id=new_id(),
        subject="dave",
        attempt_id=ATTEMPT_ID,
        collection_id=None,
        rel_path="a.cdf",
        size=4,
        state=AttemptState.FAILED,
        current_upload_id=upload_id,
        upload_ids=(upload_id,),
        created_at=START,
        active_at=START,
        failure=Failure("UPLOAD_SIZE_MISMATCH", "short"),
    )
    assert attempt.as_dict() == {
        "attempt_id": str(ATTEMPT_ID),
        "collection_id": None,
        "rel_path": "a.cdf",
        "size": 4,
        "state": "failed",
        "upload_id": str(upload_id),
        "failure": {"code": "UPLOAD_SIZE_MISMATCH", "message": "short"},
    }
    collection_id = new_id()
    assert replace(attempt, collection_id=collection_id, failure=None).as_dict() | {
        "state": "x"
    } == attempt.as_dict() | {"collection_id": str(collection_id), "failure": None, "state": "x"}
