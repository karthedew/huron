"""Upload errors."""

from __future__ import annotations

from typing import TYPE_CHECKING

from huron.pkg.errors import HuronError, register

if TYPE_CHECKING:
    import uuid
    from collections.abc import Iterable

    from huron.core.lake.uploads.models import UploadState

__all__ = [
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
