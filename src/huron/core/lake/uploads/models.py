"""Upload attempts and the objects that seals make."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import uuid
    from datetime import datetime

__all__ = [
    "AttemptState",
    "Failure",
    "ObjectState",
    "Seal",
    "StoredObject",
    "UploadAttempt",
    "file_path",
]


def file_path(directory: str, rel_path: str) -> str:
    """The path of ``rel_path`` in the collection directory ``directory``, in the API's form."""
    return f"{directory}/{rel_path}"


class AttemptState(StrEnum):
    """Where an upload attempt is in its life.

    An attempt is ``receiving`` while tusd takes its bytes, ``sealing`` while the API copies the
    complete upload into the object area, ``ready`` once the sealed object waits for a commit and
    ``consumed`` by the commit that published it. ``failed``, ``cancelled`` and ``expired`` end an
    attempt before a commit. Only a ``ready`` attempt can be published.
    """

    RECEIVING = "receiving"
    SEALING = "sealing"
    READY = "ready"
    CONSUMED = "consumed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"

    @property
    def ended(self) -> bool:
        """Whether the attempt ended before a commit, so that a new upload needs a new attempt."""
        return self in _ENDED


class ObjectState(StrEnum):
    """Where a stored object is in its life.

    An object is ``sealing`` while the API copies the bytes of its upload into the object area,
    ``sealed`` once the copy has its measured size and SHA-256, and ``removed`` after cleanup
    removed its file.
    """

    SEALING = "sealing"
    SEALED = "sealed"
    REMOVED = "removed"


@dataclass(frozen=True, slots=True)
class Failure:
    """Why an upload attempt failed."""

    code: str
    message: str

    def as_dict(self) -> dict[str, str]:
        """Render for the API and the ``failure`` column."""
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True, slots=True)
class UploadAttempt:
    """One user's attempt to upload one file to one path of a collection.

    ``subject`` and ``attempt_id`` are the key: the client chooses ``attempt_id`` when it creates
    the upload. ``upload_ids`` holds every tusd upload ID that Huron issued for the attempt, in
    the order of their time of issue (the ID orders two that Huron issued at one time), and
    ``current_upload_id`` is one of them. Huron never issues one upload ID two times, and only
    the current ID is authorized, sealed or published. ``collection_id`` is ``None`` once the
    collection is deleted. ``active_at`` is the time of the last activity, from which the time
    to live of the attempt counts. ``commit_request_id`` names the commit request that holds or
    consumed the attempt. ``failure`` says why a ``failed`` attempt ended.
    """

    id: uuid.UUID
    subject: str
    attempt_id: uuid.UUID
    collection_id: uuid.UUID | None
    rel_path: str
    size: int
    state: AttemptState
    current_upload_id: uuid.UUID
    upload_ids: tuple[uuid.UUID, ...]
    created_at: datetime
    active_at: datetime
    commit_request_id: uuid.UUID | None = None
    failure: Failure | None = None

    def __post_init__(self) -> None:
        if self.current_upload_id not in self.upload_ids:
            raise ValueError("the current upload ID must be one of the issued upload IDs")

    def has_fields(self, collection_id: uuid.UUID, rel_path: str, size: int) -> bool:
        """Whether a creation with these fields names this attempt and not a different file."""
        return (self.collection_id, self.rel_path, self.size) == (collection_id, rel_path, size)

    @property
    def idle(self) -> bool:
        """Whether the attempt can expire: ``receiving`` or ``sealing``, or ``ready`` and held by
        no commit request.
        """
        return self.state in _UNSEALED or (
            self.state is AttemptState.READY and self.commit_request_id is None
        )

    def lapsed(self, before: datetime) -> bool:
        """Whether the attempt is idle and its last activity is before ``before``.

        ``before`` is the current time minus the time to live, so a lapsed attempt is expired.
        """
        return self.idle and self.active_at < before

    def as_dict(self) -> dict[str, Any]:
        """Render for the API: the attempt with its current upload ID, for its owner."""
        return {
            "attempt_id": str(self.attempt_id),
            "collection_id": None if self.collection_id is None else str(self.collection_id),
            "rel_path": self.rel_path,
            "size": self.size,
            "state": str(self.state),
            "upload_id": str(self.current_upload_id),
            "failure": None if self.failure is None else self.failure.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class Seal:
    """A seal that may run: copy the tusd file of ``attempt``'s current upload ID to the path
    of ``stored``, and measure the copy.

    ``attempt`` is ``sealing``. ``stored`` is the one object of the upload ID, so a seal that
    runs again has the same path.
    """

    attempt: UploadAttempt
    stored: StoredObject

    @property
    def upload_id(self) -> uuid.UUID:
        """The tusd upload ID whose file the seal copies."""
        return self.stored.upload_id

    @property
    def size(self) -> int:
        """The number of bytes that the tusd file and the copy must have."""
        return self.attempt.size


@dataclass(frozen=True, slots=True)
class StoredObject:
    """The private copy that the seal of one upload ID makes in its organization's object area.

    ``upload_id`` is the issued upload ID whose bytes the seal copies, and one upload ID has one
    object: a seal that runs again uses the same object. ``path`` is the path of the copy in the
    API's form. A ``sealed`` object has its ``size``, ``sha256``, ``inode`` (the unsigned 64-bit
    inode number of the copy) and ``sealed_at``.
    """

    id: uuid.UUID
    upload_id: uuid.UUID
    path: str
    state: ObjectState
    created_at: datetime
    size: int | None = None
    sha256: str | None = None
    inode: int | None = None
    sealed_at: datetime | None = None


_ENDED = frozenset({AttemptState.FAILED, AttemptState.CANCELLED, AttemptState.EXPIRED})
_UNSEALED = frozenset({AttemptState.RECEIVING, AttemptState.SEALING})
