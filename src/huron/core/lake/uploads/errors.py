"""Upload errors."""

from __future__ import annotations

from typing import TYPE_CHECKING

from huron.core.lake.uploads.models import AttemptState
from huron.pkg.errors import HuronError, register

if TYPE_CHECKING:
    import uuid
    from collections.abc import Iterable

    from huron.core.lake.uploads.models import UploadAttempt, UploadState

__all__ = [
    "CapacityExceeded",
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


class UploadIneligible(HuronError):
    """A commit names an upload that is not ready, so the commit cannot publish it."""

    error_code = UPLOAD_INELIGIBLE

    def __init__(self, upload_id: uuid.UUID, state: AttemptState) -> None:
        super().__init__(
            f"upload {upload_id} is {state}. A commit can publish only a ready upload."
            " Read the upload attempt, then send the commit again",
            {"upload_id": str(upload_id), "state": str(state)},
        )
        self.state = state


class CapacityExceeded(HuronError):
    """The service has not enough space for the upload now."""

    error_code = CAPACITY_EXCEEDED

    def __init__(self, limit: str, requested: int, available: int) -> None:
        super().__init__(
            f"the upload needs {requested} bytes, but {limit} permits only {available} bytes."
            " Send the upload again later",
            {"limit": limit, "requested": requested, "available": available},
        )


def _refusal(state: AttemptState, upload_id: uuid.UUID | None) -> str:
    if upload_id is None:
        return f"the upload attempt is {state}. Start a new upload with a new attempt_id"
    if state is AttemptState.RECEIVING:
        return f"the upload attempt is receiving. Continue upload {upload_id}"
    return (
        f"the upload attempt is {state} with upload {upload_id}."
        " Read the upload attempt. Do not upload the file again"
    )
