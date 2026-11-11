"""Commit request errors."""

from __future__ import annotations

from typing import TYPE_CHECKING

from huron.pkg.errors import HuronError, register

if TYPE_CHECKING:
    import uuid

__all__ = ["CollectionBusy", "CommitRequestNotFound", "PublicationBlocked", "RequestIdConflict"]

REQUEST_ID_CONFLICT = register("REQUEST_ID_CONFLICT", 409, "Request ID conflict")
COMMIT_REQUEST_NOT_FOUND = register("COMMIT_REQUEST_NOT_FOUND", 404, "Commit request not found")
COLLECTION_BUSY = register("COLLECTION_BUSY", 409, "Collection busy")
PUBLICATION_BLOCKED = register("PUBLICATION_BLOCKED", 409, "Publication blocked")


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
    """The collection has a pending commit request, so it accepts no other request now.

    A collection delete gets this refusal too. A commit request keeps it under its request ID,
    so the client sends the commit again with a new request ID.
    """

    error_code = COLLECTION_BUSY

    def __init__(self, collection_id: uuid.UUID) -> None:
        super().__init__(
            "the collection has a pending commit. Wait until that commit ends."
            " A new commit needs a new request ID",
            {"collection_id": str(collection_id)},
        )


class PublicationBlocked(HuronError):
    """A filesystem step of an accepted request found an entry that the request does not expect.

    The request is ``blocked`` with this refusal until a platform administrator resolves it.
    ``detail`` tells the operator what the step found at ``path``. ``reason`` names the kind of
    entry, and ``ordinal`` names the entry of the request.
    """

    error_code = PUBLICATION_BLOCKED

    def __init__(self, ordinal: int, reason: str, path: str, detail: str) -> None:
        super().__init__(
            f"{detail} A platform administrator must resolve the commit request",
            {"ordinal": ordinal, "reason": reason, "path": path},
        )
