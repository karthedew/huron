"""Uploads: the rows behind resumable uploads, their receipts and the removal outbox."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from huron.pkg.identifiers import new_id

if TYPE_CHECKING:
    import uuid
    from datetime import datetime

    from huron.core.security.rbac import EffectiveGroups

__all__ = [
    "ClaimedRemoval",
    "Destination",
    "Failure",
    "ReceiptMode",
    "Removal",
    "Upload",
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


class ReceiptMode(StrEnum):
    """Whether a commit may record an add that no placed upload proves."""

    REQUIRED = "required"
    OPTIONAL = "optional"


@dataclass(frozen=True, slots=True)
class Failure:
    """Why the ingest sidecar could not place an upload."""

    code: str
    message: str

    def as_dict(self) -> dict[str, str]:
        """Render for the API and the ``failure`` column."""
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True, slots=True)
class Upload:
    """One upload of one file to one path of a collection, by one user.

    ``sha256`` and ``placed_at`` are the receipt, set once the bytes are at their destination;
    ``commit_id`` names the commit that consumed the receipt. ``failure`` says why a ``failed``
    upload was never placed.
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
class Removal:
    """A file the ingest sidecar still has to unlink.

    A commit queues one for each file it removes, and deleting a collection queues one for each
    of its placed uploads. ``path`` is the file's path in the form of :attr:`Destination.path`, so
    a removal outlives its collection: ``collection_id`` becomes ``None`` when the collection is
    deleted. ``commit_id`` is the commit that removed the file, ``None`` once that commit is gone
    with its collection or when no commit removed it.
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
        now: datetime,
    ) -> Removal:
        """A new, unclaimed removal of ``rel_path`` from the collection directory ``directory``."""
        return cls(
            id=new_id(),
            collection_id=collection_id,
            path=file_path(directory, rel_path),
            rel_path=rel_path,
            rel_path_key=rel_path_key,
            sha256=sha256,
            commit_id=commit_id,
            created_at=now,
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
    """Where the ingest sidecar places an upload, and the groups its file ACL comes from.

    ``path`` is the file's path below its organization's base, in the form the API gives every
    collection path (``<organization>/<catalog>/<namespace path>/<collection>/<rel_path>``).
    ``share_root`` is the organization's configured root, or ``None`` when the sidecar's mount
    prefix is the base. ``groups`` are the catalog's effective groups.
    """

    path: str
    share_root: str | None
    groups: EffectiveGroups

    def as_dict(self) -> dict[str, Any]:
        """Render for the API."""
        return {"path": self.path, "share_root": self.share_root, "groups": self.groups.as_dict()}


@dataclass(frozen=True, slots=True)
class ClaimedRemoval:
    """A removal the ingest sidecar claimed, with its organization's share root."""

    removal: Removal
    share_root: str | None

    def as_dict(self) -> dict[str, Any]:
        """Render for the API."""
        r = self.removal
        return {
            "id": str(r.id),
            "collection_id": None if r.collection_id is None else str(r.collection_id),
            "rel_path": r.rel_path,
            "sha256": r.sha256,
            "path": r.path,
            "share_root": self.share_root,
        }
