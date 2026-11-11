"""Upload errors."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from huron.core.lake.uploads.models import AttemptState
from huron.pkg.errors import HuronError, register

if TYPE_CHECKING:
    import uuid
    from collections.abc import Iterable

    from huron.core.lake.uploads.models import UploadAttempt, UploadState

__all__ = [
    "AttemptIdConflict",
    "CapacityExceeded",
    "IneligibleReason",
    "UploadAttemptRefused",
    "UploadIneligible",
    "UploadNotFound",
    "UploadReceiptMissing",
    "UploadSizeMismatch",
    "UploadStateConflict",
    "UploadTooLarge",
]

UPLOAD_NOT_FOUND = register("UPLOAD_NOT_FOUND", 404, "Upload not found")
UPLOAD_STATE_CONFLICT = register("UPLOAD_STATE_CONFLICT", 409, "Upload state conflict")
UPLOAD_SIZE_MISMATCH = register("UPLOAD_SIZE_MISMATCH", 422, "Upload size mismatch")
UPLOAD_TOO_LARGE = register("UPLOAD_TOO_LARGE", 413, "Upload too large")
UPLOAD_RECEIPT_MISSING = register("UPLOAD_RECEIPT_MISSING", 422, "Upload receipt missing")
UPLOAD_INELIGIBLE = register("UPLOAD_INELIGIBLE", 409, "Upload ineligible")
CAPACITY_EXCEEDED = register("CAPACITY_EXCEEDED", 429, "Capacity exceeded")
ATTEMPT_ID_CONFLICT = register("ATTEMPT_ID_CONFLICT", 409, "Attempt ID conflict")


class UploadNotFound(HuronError):
    """The upload does not exist, or the caller did not create it."""

    error_code = UPLOAD_NOT_FOUND

    def __init__(self, upload_id: uuid.UUID) -> None:
        super().__init__("upload not found", {"upload": str(upload_id)})


class UploadStateConflict(HuronError):
    """The state of the upload does not allow the operation."""

    error_code = UPLOAD_STATE_CONFLICT

    def __init__(self, state: UploadState, allowed: Iterable[UploadState]) -> None:
        super().__init__(
            f"the upload is {state}. This operation is not possible in that state",
            {"state": str(state), "allowed": [str(each) for each in allowed]},
        )


class UploadSizeMismatch(HuronError):
    """The placed bytes do not have the size the upload declared."""

    error_code = UPLOAD_SIZE_MISMATCH

    def __init__(self, declared: int, received: int) -> None:
        super().__init__(
            f"the upload declared {declared} bytes, but the file has {received} bytes",
            {"declared": declared, "received": received},
        )


class UploadTooLarge(HuronError):
    """The upload declares more bytes than the service accepts."""

    error_code = UPLOAD_TOO_LARGE

    def __init__(self, size: int, maximum: int) -> None:
        super().__init__(
            f"the upload has {size} bytes. The maximum is {maximum} bytes",
            {"size": size, "maximum": maximum},
        )


class UploadReceiptMissing(HuronError):
    """A commit adds a file that no placed upload of the committer proves."""

    error_code = UPLOAD_RECEIPT_MISSING

    def __init__(self, rel_path: str) -> None:
        super().__init__(
            f"{rel_path!r} has no upload receipt. Upload the file, then commit it again",
            {"rel_path": rel_path},
        )


class UploadAttemptRefused(HuronError):
    """A creation names an attempt that already has an upload, so Huron issues no new upload ID.

    ``state`` is the state of the attempt. ``upload_id`` is its current upload ID, or ``None``
    when the attempt ended: a new upload then needs a new attempt.
    """

    error_code = UPLOAD_STATE_CONFLICT

    def __init__(self, attempt: UploadAttempt) -> None:
        self.state = attempt.state
        self.upload_id = None if attempt.state.ended else attempt.current_upload_id
        context: dict[str, str] = {"attempt_id": str(attempt.attempt_id), "state": str(self.state)}
        if self.upload_id is not None:
            context["upload_id"] = str(self.upload_id)
        super().__init__(_refusal(self.state, self.upload_id), context)


class IneligibleReason(StrEnum):
    """Why a commit or a seal cannot use an upload.

    ``state``: the attempt is not in the state that the operation needs. ``superseded``: the
    upload ID is not the current upload ID of its attempt. ``held``: a pending commit request
    holds the upload. ``different_file``: the upload is for another collection or path, or its
    size or its server sha256 is not the size or the sha256 of the add.
    """

    STATE = "state"
    SUPERSEDED = "superseded"
    HELD = "held"
    DIFFERENT_FILE = "different_file"


class UploadIneligible(HuronError):
    """A commit or a seal names an upload that it cannot use.

    ``state`` is the state of the attempt of the upload, and ``reason`` tells why. With
    ``sealing`` the message is for a seal that cannot start, which has only the reasons
    ``state`` and ``superseded``. Otherwise it is for a commit request: a client that sends the
    commit again uses a new request ID, because the request ID keeps this refusal.
    """

    error_code = UPLOAD_INELIGIBLE

    def __init__(
        self,
        upload_id: uuid.UUID,
        state: AttemptState,
        reason: IneligibleReason = IneligibleReason.STATE,
        *,
        sealing: bool = False,
    ) -> None:
        messages = _SEAL_REFUSALS if sealing else _COMMIT_REFUSALS
        super().__init__(
            messages[reason].format(upload_id=upload_id, state=state),
            {"upload_id": str(upload_id), "state": str(state), "reason": str(reason)},
        )
        self.state = state
        self.reason = reason


class AttemptIdConflict(HuronError):
    """A creation names an attempt that Huron knows with another collection, path or size."""

    error_code = ATTEMPT_ID_CONFLICT

    def __init__(self, attempt_id: uuid.UUID) -> None:
        super().__init__(
            f"upload attempt {attempt_id} is for a different file."
            " Use a new attempt_id for a new upload",
            {"attempt_id": str(attempt_id)},
        )


class CapacityExceeded(HuronError):
    """The service has not enough space for the upload now."""

    error_code = CAPACITY_EXCEEDED

    def __init__(self, limit: str, requested: int, available: int) -> None:
        super().__init__(
            f"the upload needs {requested} bytes, but {limit} permits only {available} bytes."
            " Send the upload again later",
            {"limit": limit, "requested": requested, "available": available},
        )


_AGAIN = " Read the upload attempt, then send the commit again with a new request ID"
_COMMIT_REFUSALS = {
    IneligibleReason.STATE: (
        "upload {upload_id} is {state}. A commit can publish only a ready upload." + _AGAIN
    ),
    IneligibleReason.SUPERSEDED: (
        "upload {upload_id} is not the current upload of its attempt." + _AGAIN
    ),
    IneligibleReason.HELD: (
        "a pending commit holds upload {upload_id}. A commit can publish an upload one time"
    ),
    IneligibleReason.DIFFERENT_FILE: (
        "upload {upload_id} holds a different file. Its collection, path, size or sha256"
        " is not the value of the add"
    ),
}
_SEAL_REFUSALS = {
    IneligibleReason.STATE: (
        "upload {upload_id} is {state}. Huron cannot start a seal of it. Read the upload attempt"
    ),
    IneligibleReason.SUPERSEDED: (
        "upload {upload_id} is not the current upload of its attempt."
        " Huron cannot start a seal of it. Read the upload attempt"
    ),
}


def _refusal(state: AttemptState, upload_id: uuid.UUID | None) -> str:
    if upload_id is None:
        return f"the upload attempt is {state}. Start a new upload with a new attempt_id"
    if state is AttemptState.RECEIVING:
        return f"the upload attempt is receiving. Continue upload {upload_id}"
    return (
        f"the upload attempt is {state} with upload {upload_id}."
        " Read the upload attempt. Do not upload the file again"
    )
