"""Where things live on the share."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path, PurePosixPath

from huron.core.storage.errors import StorageError
from huron.schema.naming import METADATA_FILE, PART_SUFFIX

__all__ = ["MARKER_FILE", "DirectoryKind", "is_reserved_entry", "resolve"]

MARKER_FILE = ".huron"


class DirectoryKind(StrEnum):
    """The kinds of directory Huron creates, each with its own ACL plan."""

    ORGANIZATION = "organization"
    CATALOG = "catalog"
    NAMESPACE = "namespace"
    NAMESPACE_WITH_COLLECTIONS = "namespace_with_collections"
    COLLECTION = "collection"


def resolve(prefix: Path, relative: str) -> Path:
    """``prefix / relative`` for a path the API returned; refuses anything escaping the prefix."""
    parts = relative.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise StorageError("refusing a path outside the share", {"path": relative})
    return prefix.joinpath(*parts)


def is_reserved_entry(rel_path: str) -> bool:
    """Whether an entry inside a collection belongs to Huron rather than to the user."""
    name = PurePosixPath(rel_path).name
    return rel_path == METADATA_FILE or name.startswith(MARKER_FILE) or name.endswith(PART_SUFFIX)
