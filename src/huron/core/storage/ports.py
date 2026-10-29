"""The storage port the CLI writes the share through."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from huron.core.storage.aclplan import AclPlan
    from huron.pkg.fs.acl import Acl
    from huron.pkg.fs.posix import Entry, Stamp

__all__ = ["FileStamp", "Storage"]


@dataclass(frozen=True, slots=True)
class FileStamp:
    """Size and content hash of a file copied into a collection."""

    size: int
    sha256: str


class Storage(Protocol):
    """Directory, ACL and file operations on the share."""

    def ensure_directory(self, path: Path, plan: AclPlan) -> bool:
        """Create ``path`` (its parent must exist) and apply ``plan``; ``True`` when created."""
        ...

    def apply_plan(self, path: Path, plan: AclPlan) -> bool:
        """Apply ``plan`` to an existing directory; ``True`` when anything changed."""
        ...

    def read_acl(self, path: Path) -> Acl:
        """The ACL of ``path``."""
        ...

    def copy_in(
        self, source: Path, directory: Path, rel_path: str, expected: FileStamp | None = None
    ) -> FileStamp:
        """Copy ``source`` to ``directory / rel_path`` through a part file."""
        ...

    def write_bytes(self, path: Path, data: bytes) -> None:
        """Write ``data`` atomically."""
        ...

    def read_bytes(self, path: Path) -> bytes | None:
        """The bytes of a file, or ``None`` when it does not exist."""
        ...

    def remove_file(self, path: Path) -> bool:
        """Remove a file; ``False`` when it was already gone."""
        ...

    def remove_directory(self, path: Path) -> bool:
        """Remove an empty directory; ``False`` when it was already gone."""
        ...

    def exists(self, path: Path) -> bool:
        """Whether ``path`` is a directory or file."""
        ...

    def is_directory(self, path: Path) -> bool:
        """Whether ``path`` is a real directory."""
        ...

    def walk(self, path: Path) -> Iterator[Entry]:
        """Every entry under ``path``, sorted, without following links."""
        ...

    def stamp(self, path: Path) -> Stamp:
        """Size and modification time of a file."""
        ...

    def hash(self, path: Path) -> FileStamp:
        """Size and sha256 of a file."""
        ...

    def owned_by_me(self, path: Path) -> bool:
        """Whether the current user owns ``path`` (only owners may change its ACL)."""
        ...
