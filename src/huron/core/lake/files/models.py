"""Recorded files and commits."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import uuid
    from datetime import datetime

    from huron.core.lake.uploads.models import Removal

__all__ = ["Commit", "CommitRequest", "CommitResult", "FileAdd", "FileRecord"]


@dataclass(frozen=True, slots=True)
class FileRecord:
    """One file recorded in a collection.

    ``inode`` is the inode of the receipt that proved the record, ``None`` without one.
    ``object_id`` names the sealed object that a commit request published at the path, ``None``
    for a file that no sealed object holds.
    """

    collection_id: uuid.UUID
    rel_path: str
    rel_path_key: str
    size: int
    sha256: str
    recorded_at: datetime
    recorded_by: str
    commit_id: uuid.UUID
    inode: int | None = None
    object_id: uuid.UUID | None = None

    def as_dict(self) -> dict[str, Any]:
        """Render for the API."""
        return {
            "rel_path": self.rel_path,
            "size": self.size,
            "sha256": self.sha256,
            "recorded_at": self.recorded_at.isoformat(),
            "recorded_by": self.recorded_by,
            "commit_id": str(self.commit_id),
        }


@dataclass(frozen=True, slots=True)
class FileAdd:
    """A file a commit adds or replaces.

    ``sha256`` is ``None`` only in a dry run, which may be sent before the file is uploaded and
    hashed; a real commit refuses an add without one.
    """

    rel_path: str
    size: int
    sha256: str | None


@dataclass(frozen=True, slots=True)
class CommitRequest:
    """The body of a commit."""

    base_version: int
    adds: tuple[FileAdd, ...]
    removes: tuple[str, ...]
    host: str
    message: str | None = None


@dataclass(frozen=True, slots=True)
class Commit:
    """One applied commit."""

    id: uuid.UUID
    collection_id: uuid.UUID
    base_version: int
    new_version: int
    adds: int
    removes: int
    host: str
    message: str | None
    actor: str
    created_at: datetime

    def as_dict(self) -> dict[str, Any]:
        """Render for the API."""
        return {
            "id": str(self.id),
            "base_version": self.base_version,
            "new_version": self.new_version,
            "adds": self.adds,
            "removes": self.removes,
            "host": self.host,
            "message": self.message,
            "actor": self.actor,
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class CommitResult:
    """What a successful commit answers, or what a dry run says the commit would make.

    A dry run writes no commit, so its ``commit_id`` is ``None``. ``removals`` are the removals
    of the removed files, which the commit claimed for the request that made it; the API drains
    them and never renders them.
    """

    version: int
    file_count: int
    commit_id: uuid.UUID | None
    removals: tuple[Removal, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        """Render for the API."""
        return {
            "version": self.version,
            "file_count": self.file_count,
            "commit_id": None if self.commit_id is None else str(self.commit_id),
        }
