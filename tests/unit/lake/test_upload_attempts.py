"""Upload attempts: their states, their issued upload IDs and the refusals that name them."""

import uuid
from dataclasses import replace
from datetime import timedelta

import pytest

from huron.core.lake.uploads.errors import (
    AttemptIdConflict,
    CapacityExceeded,
    IneligibleReason,
    UploadAttemptRefused,
    UploadIneligible,
)
from huron.core.lake.uploads.models import AttemptState, UploadAttempt
from tests.support.clock import START

ATTEMPT_ID = uuid.UUID("0190d5a4-0000-7000-8000-00000000000a")
COLLECTION_ID = uuid.UUID("0190d5a4-0000-7000-8000-00000000000c")
FIRST = uuid.UUID("0190d5a4-0000-7000-8000-000000000001")
CURRENT = uuid.UUID("0190d5a4-0000-7000-8000-000000000002")

ATTEMPT = UploadAttempt(
    id=uuid.UUID("0190d5a4-0000-7000-8000-0000000000ff"),
    subject="alice",
    attempt_id=ATTEMPT_ID,
    collection_id=COLLECTION_ID,
    rel_path="solar/day1.cdf",
    size=10,
    state=AttemptState.RECEIVING,
    current_upload_id=CURRENT,
    upload_ids=(FIRST, CURRENT),
    created_at=START,
    active_at=START,
)


@pytest.mark.parametrize(
    ("state", "ended"),
    [
        (AttemptState.RECEIVING, False),
        (AttemptState.SEALING, False),
        (AttemptState.READY, False),
        (AttemptState.CONSUMED, False),
        (AttemptState.FAILED, True),
        (AttemptState.CANCELLED, True),
        (AttemptState.EXPIRED, True),
    ],
)
def test_only_failed_cancelled_and_expired_attempts_ended(state: AttemptState, ended: bool) -> None:
    assert state.ended is ended


def test_an_attempt_holds_no_commit_request_and_no_failure_by_default() -> None:
    assert (ATTEMPT.commit_request_id, ATTEMPT.failure) == (None, None)


def test_the_current_upload_id_must_be_one_of_the_issued_ids() -> None:
    with pytest.raises(ValueError, match="one of the issued upload IDs"):
        replace(ATTEMPT, upload_ids=(FIRST,))


def test_an_attempt_without_an_issued_id_cannot_be_made() -> None:
    with pytest.raises(ValueError, match="one of the issued upload IDs"):
        replace(ATTEMPT, upload_ids=())


def test_a_creation_with_the_same_fields_names_the_attempt() -> None:
    assert ATTEMPT.has_fields(COLLECTION_ID, "solar/day1.cdf", 10)


@pytest.mark.parametrize(
    ("collection_id", "rel_path", "size"),
    [
        pytest.param(uuid.uuid4(), "solar/day1.cdf", 10, id="collection"),
        pytest.param(COLLECTION_ID, "solar/Day1.cdf", 10, id="spelling"),
        pytest.param(COLLECTION_ID, "solar/day1.cdf", 11, id="size"),
    ],
)
def test_a_creation_with_other_fields_does_not_name_the_attempt(
    collection_id: uuid.UUID, rel_path: str, size: int
) -> None:
    assert not ATTEMPT.has_fields(collection_id, rel_path, size)


def test_an_attempt_of_a_deleted_collection_matches_no_creation() -> None:
    assert not replace(ATTEMPT, collection_id=None).has_fields(COLLECTION_ID, "solar/day1.cdf", 10)


def test_a_refusal_of_a_receiving_attempt_names_the_upload_to_continue() -> None:
    error = UploadAttemptRefused(ATTEMPT)
    assert (error.code, error.status) == ("UPLOAD_STATE_CONFLICT", 409)
    assert (error.state, error.upload_id) == (AttemptState.RECEIVING, CURRENT)
    assert error.context == {
        "attempt_id": str(ATTEMPT_ID),
        "state": "receiving",
        "upload_id": str(CURRENT),
    }
    assert error.message == f"the upload attempt is receiving. Continue upload {CURRENT}"


@pytest.mark.parametrize("state", [AttemptState.SEALING, AttemptState.READY, AttemptState.CONSUMED])
def test_a_refusal_of_a_sealing_ready_or_consumed_attempt_names_its_state_and_upload(
    state: AttemptState,
) -> None:
    error = UploadAttemptRefused(replace(ATTEMPT, state=state))
    assert (error.state, error.upload_id) == (state, CURRENT)
    assert error.context == {
        "attempt_id": str(ATTEMPT_ID),
        "state": str(state),
        "upload_id": str(CURRENT),
    }
    assert error.message == (
        f"the upload attempt is {state} with upload {CURRENT}."
        " Read the upload attempt. Do not upload the file again"
    )


@pytest.mark.parametrize(
    "state", [AttemptState.FAILED, AttemptState.CANCELLED, AttemptState.EXPIRED]
)
def test_a_refusal_of_an_ended_attempt_names_its_state_only(state: AttemptState) -> None:
    error = UploadAttemptRefused(replace(ATTEMPT, state=state))
    assert (error.state, error.upload_id) == (state, None)
    assert error.context == {"attempt_id": str(ATTEMPT_ID), "state": str(state)}
    assert error.message == (
        f"the upload attempt is {state}. Start a new upload with a new attempt_id"
    )


def test_an_ineligible_upload_names_the_upload_its_state_and_the_reason() -> None:
    error = UploadIneligible.for_commit(CURRENT, AttemptState.SEALING)
    assert (error.code, error.status) == ("UPLOAD_INELIGIBLE", 409)
    assert (error.state, error.reason) == (AttemptState.SEALING, IneligibleReason.STATE)
    assert error.context == {"upload_id": str(CURRENT), "state": "sealing", "reason": "state"}
    assert error.message == (
        f"upload {CURRENT} is sealing. A commit can publish only a ready upload."
        " Read the upload attempt, then send the commit again with a new request ID"
    )


@pytest.mark.parametrize(
    ("reason", "message"),
    [
        (
            IneligibleReason.SUPERSEDED,
            f"upload {FIRST} is not the current upload of its attempt."
            " Read the upload attempt, then send the commit again with a new request ID",
        ),
        (
            IneligibleReason.HELD,
            f"a pending commit holds upload {FIRST}. A commit can publish an upload one time",
        ),
        (
            IneligibleReason.DIFFERENT_FILE,
            f"upload {FIRST} holds a different file. Its collection, path, size or sha256"
            " is not the value of the add",
        ),
    ],
)
def test_an_ineligible_upload_tells_each_reason(reason: IneligibleReason, message: str) -> None:
    error = UploadIneligible.for_commit(FIRST, AttemptState.READY, reason)
    assert (error.message, error.reason) == (message, reason)
    assert error.context == {"upload_id": str(FIRST), "state": "ready", "reason": str(reason)}


@pytest.mark.parametrize(
    "state", [AttemptState.FAILED, AttemptState.CANCELLED, AttemptState.EXPIRED]
)
def test_a_commit_of_an_ended_upload_tells_the_client_to_start_a_new_upload(
    state: AttemptState,
) -> None:
    error = UploadIneligible.for_commit(FIRST, state)
    assert error.reason is IneligibleReason.STATE
    assert error.message == (
        f"upload {FIRST} is {state}. Start a new upload of the file with a new attempt_id,"
        " then send the commit again with a new request ID"
    )


@pytest.mark.parametrize(
    ("superseded", "reason", "message"),
    [
        (
            False,
            IneligibleReason.STATE,
            f"upload {FIRST} is cancelled. Huron cannot start a seal of it."
            " Read the upload attempt",
        ),
        (
            True,
            IneligibleReason.SUPERSEDED,
            f"upload {FIRST} is not the current upload of its attempt."
            " Huron cannot start a seal of it. Read the upload attempt",
        ),
    ],
)
def test_a_seal_that_cannot_start_tells_its_reason_without_a_commit(
    superseded: bool, reason: IneligibleReason, message: str
) -> None:
    error = UploadIneligible.for_seal(FIRST, AttemptState.CANCELLED, superseded=superseded)
    assert (error.code, error.message, error.reason) == ("UPLOAD_INELIGIBLE", message, reason)
    assert error.context == {
        "upload_id": str(FIRST),
        "state": "cancelled",
        "reason": str(reason),
    }


def test_an_attempt_id_conflict_names_the_attempt() -> None:
    error = AttemptIdConflict(ATTEMPT_ID)
    assert (error.code, error.status) == ("ATTEMPT_ID_CONFLICT", 409)
    assert error.context == {"attempt_id": str(ATTEMPT_ID)}
    assert error.message == (
        f"upload attempt {ATTEMPT_ID} is for a different file."
        " Use a new attempt_id for a new upload"
    )


@pytest.mark.parametrize(
    ("state", "held", "idle"),
    [
        (AttemptState.RECEIVING, False, True),
        (AttemptState.SEALING, False, True),
        (AttemptState.READY, False, True),
        (AttemptState.READY, True, False),
        (AttemptState.CONSUMED, True, False),
        (AttemptState.FAILED, False, False),
        (AttemptState.CANCELLED, False, False),
        (AttemptState.EXPIRED, False, False),
    ],
)
def test_only_an_unsealed_or_free_ready_attempt_is_idle(
    state: AttemptState, held: bool, idle: bool
) -> None:
    attempt = replace(ATTEMPT, state=state, commit_request_id=ATTEMPT.id if held else None)
    assert attempt.idle is idle


def test_an_idle_attempt_lapses_only_when_its_activity_is_before_the_limit() -> None:
    later = START + timedelta(microseconds=1)
    assert ATTEMPT.lapsed(later)
    assert not ATTEMPT.lapsed(START)
    assert not replace(ATTEMPT, state=AttemptState.EXPIRED).lapsed(later)


def test_exceeded_capacity_names_the_limit_and_the_bytes() -> None:
    error = CapacityExceeded("max_staged_bytes", 100, 40)
    assert (error.code, error.status) == ("CAPACITY_EXCEEDED", 429)
    assert error.context == {"limit": "max_staged_bytes", "requested": 100, "available": 40}
    assert error.message == (
        "the upload needs 100 bytes, but max_staged_bytes permits only 40 bytes."
        " Send the upload again later"
    )


def test_exceeded_capacity_of_a_doubled_upload_says_that_it_needs_its_size_two_times() -> None:
    error = CapacityExceeded("min_free_bytes", 100, 40, doubled=True)
    assert error.context == {"limit": "min_free_bytes", "requested": 100, "available": 40}
    assert error.message == (
        "the upload needs 100 bytes (two times its size: tusd keeps the file and Huron keeps a"
        " copy), but min_free_bytes permits only 40 bytes. Send the upload again later"
    )
