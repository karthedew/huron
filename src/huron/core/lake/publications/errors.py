"""Commit request errors."""

from __future__ import annotations

from typing import TYPE_CHECKING

from huron.pkg.errors import HuronError, register

if TYPE_CHECKING:
    import uuid

__all__ = ["CollectionBusy", "CommitRequestNotFound", "RequestIdConflict"]

REQUEST_ID_CONFLICT = register("REQUEST_ID_CONFLICT", 409, "Request ID conflict")
COMMIT_REQUEST_NOT_FOUND = register("COMMIT_REQUEST_NOT_FOUND", 404, "Commit request not found")
COLLECTION_BUSY = register("COLLECTION_BUSY", 409, "Collection busy")


class RequestIdConflict(HuronError):
    """The caller sent a different body with a request ID that it used before."""

    error_code = REQUEST_ID_CONFLICT

    def __init__(self, request_id: uuid.UUID) -> None:
        super().__init__(
            f"request {request_id} has a different body. Use a new request ID for a new commit",
            {"request_id": str(request_id)},
        )


class CommitRequestNotFound(HuronError):
    """The commit request does not exist, or the caller did not send it."""

    error_code = COMMIT_REQUEST_NOT_FOUND

    def __init__(self, request_id: uuid.UUID) -> None:
        super().__init__("commit request not found", {"request_id": str(request_id)})


class CollectionBusy(HuronError):
    """The collection has a pending commit request, so it accepts no other request now."""

    error_code = COLLECTION_BUSY

    def __init__(self, collection_id: uuid.UUID) -> None:
        super().__init__(
            "the collection has a pending commit. Send the commit again when that commit ends",
            {"collection_id": str(collection_id)},
        )
