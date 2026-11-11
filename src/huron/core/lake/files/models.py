"""Recorded files and commits."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import uuid
    from datetime import datetime

__all__ = ["Commit", "FileRecord"]


@dataclass(frozen=True, slots=True)
class FileRecord:
    """One file recorded in a collection.

    ``inode`` is the inode of the sealed object that a commit request published at the path,
    and ``object_id`` names that object. Both are ``None`` for a file that no sealed object
    holds.
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
