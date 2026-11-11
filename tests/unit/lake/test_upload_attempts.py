"""Upload attempts: their states, their issued upload IDs and the refusals that name them."""

import uuid
from dataclasses import replace

import pytest

from huron.core.lake.uploads.errors import CapacityExceeded, UploadAttemptRefused, UploadIneligible
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


def test_an_ineligible_upload_names_the_upload_and_its_state() -> None:
    error = UploadIneligible(CURRENT, AttemptState.SEALING)
    assert (error.code, error.status) == ("UPLOAD_INELIGIBLE", 409)
    assert error.state is AttemptState.SEALING
    assert error.context == {"upload_id": str(CURRENT), "state": "sealing"}
    assert error.message.startswith(f"upload {CURRENT} is sealing.")


def test_exceeded_capacity_names_the_limit_and_the_bytes() -> None:
    error = CapacityExceeded("max_staged_bytes", 100, 40)
    assert (error.code, error.status) == ("CAPACITY_EXCEEDED", 429)
    assert error.context == {"limit": "max_staged_bytes", "requested": 100, "available": 40}
    assert error.message == (
        "the upload needs 100 bytes, but max_staged_bytes permits only 40 bytes."
        " Send the upload again later"
    )
