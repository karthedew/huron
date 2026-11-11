"""Uploads: the rows behind resumable uploads, their receipts, the removal outbox, attempts and
the objects that seals make."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from huron.pkg.identifiers import new_id

if TYPE_CHECKING:
    import uuid
    from datetime import datetime

__all__ = [
    "AttemptState",
    "Destination",
    "Failure",
    "ObjectState",
    "ReceiptMode",
    "Removal",
    "Seal",
    "StoredObject",
    "Upload",
    "UploadAttempt",
    "UploadState",
    "file_path",
]


def file_path(directory: str, rel_path: str) -> str:
    """The path of ``rel_path`` in the collection directory ``directory``, in the API's form."""
    return f"{directory}/{rel_path}"


class UploadState(StrEnum):
    """Where an upload is in its life.

    ``pending`` until its bytes are placed, then ``placed`` (it holds a receipt) and finally
    ``committed`` by the commit that recorded it. ``failed`` and ``terminated`` end an upload that
    was never placed.
    """

    PENDING = "pending"
    PLACED = "placed"
    FAILED = "failed"
    TERMINATED = "terminated"
    COMMITTED = "committed"


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


class ReceiptMode(StrEnum):
    """Whether a commit may record an add that no placed upload proves."""

    REQUIRED = "required"
    OPTIONAL = "optional"


@dataclass(frozen=True, slots=True)
class Failure:
    """Why the API could not place an upload."""

    code: str
    message: str

    def as_dict(self) -> dict[str, str]:
        """Render for the API and the ``failure`` column."""
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True, slots=True)
class Upload:
    """One upload of one file to one path of a collection, by one user.

    ``sha256``, ``placed_at`` and ``inode`` are the receipt, set once the bytes are at their
    destination. ``inode`` is the placed file's unsigned 64-bit inode number. ``commit_id`` names
    the commit that consumed the receipt. ``failure`` says why a ``failed`` upload was never
    placed.
    """

    id: uuid.UUID
    collection_id: uuid.UUID
    rel_path: str
    rel_path_key: str
    size: int
    state: UploadState
    created_by: str
    created_at: datetime
    sha256: str | None = None
    failure: Failure | None = None
    placed_at: datetime | None = None
    commit_id: uuid.UUID | None = None
    inode: int | None = None

    def proves(
        self, created_by: str, rel_path: str, size: int, sha256: str | None, placed_after: datetime
    ) -> bool:
        """Whether this placed upload is ``created_by``'s receipt for ``size`` bytes hashing to
        ``sha256`` at exactly ``rel_path``, placed after ``placed_after``.

        Callers ask only the latest placement of the path: an older one no longer describes
        the file on disk.
        """
        return (
            self.state is UploadState.PLACED
            and self.created_by == created_by
            and self.rel_path == rel_path
            and self.size == size
            and self.sha256 == sha256
            and self.placed_at is not None
            and self.placed_at > placed_after
        )

    def removal(self, directory: str, now: datetime) -> Removal:
        """The removal of this placed upload's file from its collection's ``directory``."""
        assert self.sha256 is not None
        return Removal.of(
            self.collection_id,
            directory,
            self.rel_path,
            self.rel_path_key,
            self.sha256,
            commit_id=None,
            inode=self.inode,
            now=now,
        )

    def as_dict(self) -> dict[str, Any]:
        """Render for the API."""
        return {
            "id": str(self.id),
            "collection_id": str(self.collection_id),
            "rel_path": self.rel_path,
            "size": self.size,
            "state": str(self.state),
            "sha256": self.sha256,
            "failure": None if self.failure is None else self.failure.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class UploadAttempt:
    """One user's attempt to upload one file to one path of a collection.

    ``subject`` and ``attempt_id`` are the key: the client chooses ``attempt_id`` when it creates
    the upload. ``upload_ids`` holds every tusd upload ID that Huron issued for the attempt, in
    the order of their time of issue (the ID orders two that Huron issued at one time), and
    ``current_upload_id`` is one of them. Huron never issues one upload ID two times, and only
    the current ID is authorized, sealed or published. ``collection_id``
    is ``None`` once the collection is deleted. ``active_at`` is the time of the last activity,
    from which ``upload_ttl`` counts. ``commit_request_id`` names the commit request that holds
    or consumed the attempt. ``failure`` says why a ``failed`` attempt ended.
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

        ``before`` is the current time minus ``upload_ttl``, so a lapsed attempt is expired.
        """
        return self.idle and self.active_at < before


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


@dataclass(frozen=True, slots=True)
class Removal:
    """A file the API still has to unlink.

    A commit queues one for each file it removes, and deleting a collection queues one for each
    of its placed uploads. ``path`` is the file's path in the API's form (:func:`file_path`), so a
    removal outlives its collection: ``collection_id`` becomes ``None`` when the collection is
    deleted. ``commit_id`` is the commit that removed the file, ``None`` once that commit is gone
    with its collection or when no commit removed it. ``inode`` is the inode the file had when
    Huron recorded or placed it, ``None`` when Huron never learned it. A removal unlinks only the
    file that still has that inode.
    """

    id: uuid.UUID
    collection_id: uuid.UUID | None
    path: str
    rel_path: str
    rel_path_key: str
    sha256: str
    commit_id: uuid.UUID | None
    created_at: datetime
    claimed_at: datetime | None = None
    inode: int | None = None

    @classmethod
    def of(
        cls,
        collection_id: uuid.UUID,
        directory: str,
        rel_path: str,
        rel_path_key: str,
        sha256: str,
        *,
        commit_id: uuid.UUID | None,
        inode: int | None,
        now: datetime,
    ) -> Removal:
        """A new removal of ``rel_path`` from the collection directory ``directory``.

        The request that makes the removal claims it at ``now``, so that request unlinks the file
        and the background claims take the removal only after the claim goes stale.
        """
        return cls(
            id=new_id(),
            collection_id=collection_id,
            path=file_path(directory, rel_path),
            rel_path=rel_path,
            rel_path_key=rel_path_key,
            sha256=sha256,
            commit_id=commit_id,
            created_at=now,
            claimed_at=now,
            inode=inode,
        )

    @property
    def organization(self) -> str:
        """The name of the organization the file belongs to, the first segment of its path."""
        return self.path.split("/", 1)[0]

    @property
    def directory(self) -> str:
        """The path of the file's collection directory, in the form of :attr:`path`."""
        return self.path.removesuffix(f"/{self.rel_path}")


@dataclass(frozen=True, slots=True)
class Destination:
    """Where the API places an upload: the names, not a joined path.

    ``directory`` is the collection's ``disk_path``, in the form the API gives every collection
    path (``<organization>/<catalog>/<namespace path>/<collection>``). ``rel_path`` is the
    upload's path inside that directory. A :class:`Removal` names its file with the same two
    fields.
    """

    directory: str
    rel_path: str


_ENDED = frozenset({AttemptState.FAILED, AttemptState.CANCELLED, AttemptState.EXPIRED})
_UNSEALED = frozenset({AttemptState.RECEIVING, AttemptState.SEALING})
