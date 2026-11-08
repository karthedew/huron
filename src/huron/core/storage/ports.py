"""The storage ports: reading the share, and writing it through the one writer."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from huron.core.storage.aclplan import AclPlan
    from huron.pkg.fs.acl import Acl
    from huron.pkg.fs.posix import Entry, Stamp

__all__ = [
    "SHARE_GROUP_PENDING",
    "FileStamp",
    "GroupOutcome",
    "GroupResult",
    "OpenFile",
    "Ownership",
    "ShareReader",
    "ShareWarning",
    "Storage",
]

#: The warning code of a share group that is recorded but not yet set on disk.
SHARE_GROUP_PENDING = "SHARE_GROUP_PENDING"


@dataclass(frozen=True, slots=True)
class FileStamp:
    """Size and content hash of a file."""

    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class Ownership:
    """The owner, the group and the mode bits (setgid included) of an entry."""

    uid: int
    gid: int
    mode: int


class GroupOutcome(StrEnum):
    """What an attempt to set a directory's group did."""

    CHANGED = "changed"
    UNCHANGED = "unchanged"
    PENDING = "pending"


@dataclass(frozen=True, slots=True)
class GroupResult:
    """The outcome of a group change; ``reason`` says why a ``PENDING`` change did not happen."""

    outcome: GroupOutcome
    reason: str | None = None

    @classmethod
    def unknown(cls, group: str) -> GroupResult:
        """The ``PENDING`` result for a group name the machine cannot resolve."""
        return cls(GroupOutcome.PENDING, f"this machine does not know the group {group}")


@dataclass(frozen=True, slots=True)
class ShareWarning:
    """A change on disk that the storage administrator must still make.

    ``code`` is :data:`SHARE_GROUP_PENDING` when a catalog directory does not carry the group
    ``group``. ``group`` is the catalog's share group, or the gid of the service group as text
    when the share group is cleared. ``detail`` says why the attempt failed.
    """

    code: str
    group: str
    detail: str


class OpenFile(Protocol):
    """A file opened read-only.

    ``size`` and ``inode`` come from the open descriptor, so they describe the bytes that
    :meth:`sha256` reads, whatever happens to the file's name meanwhile.
    """

    @property
    def size(self) -> int:
        """The size in bytes."""
        ...

    @property
    def inode(self) -> int:
        """The unsigned inode number."""
        ...

    def sha256(self) -> str:
        """The sha256 of the bytes, read from the descriptor."""
        ...

    def set_mode(self, mode: int) -> None:
        """Give the file exactly ``mode`` through the descriptor."""
        ...

    def close(self) -> None:
        """Release the descriptor."""
        ...


class ShareReader(Protocol):
    """Read-only operations on the share."""

    def read_bytes(self, path: Path) -> bytes | None:
        """The bytes of a file, or ``None`` when it does not exist."""
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

    def owner(self, path: Path) -> Ownership:
        """The owner, the group and the mode of ``path``, without following a final link."""
        ...

    def device(self, path: Path) -> int:
        """The identifier of the filesystem that holds ``path``."""
        ...


class Storage(ShareReader, Protocol):
    """Every operation on the share, writes included."""

    def make_directory(self, path: Path, mode: int) -> bool:
        """Create ``path`` with exactly ``mode`` (its parent must exist); ``True`` when created.

        An existing directory is left as it is.
        """
        ...

    def set_mode(self, path: Path, mode: int) -> bool:
        """Give ``path`` exactly ``mode``; ``True`` when the mode changed."""
        ...

    def set_group(self, path: Path, group: str | int) -> GroupResult:
        """Try to give ``path`` the group ``group``, a name or a gid.

        A refusal, or a name this machine cannot resolve, is ``PENDING``, not an error.
        """
        ...

    def make_inheriting_dir(self, path: Path) -> bool:
        """Create ``path`` with mode ``0750``; ``True`` when created, an existing one is kept.

        The setgid bit and the group come only from the parent's inheritance. A new directory
        without them is removed again and refused; the mode is never fixed with ``chmod``.
        """
        ...

    def write_bytes(self, path: Path, data: bytes, mode: int | None = None) -> None:
        """Write ``data`` atomically; with ``mode``, the file gets exactly that mode."""
        ...

    def open_file(self, path: Path) -> OpenFile | None:
        """Open a file read-only; ``None`` when it does not exist. The caller closes it."""
        ...

    def link(
        self, source: Path, destination: Path, part_name: str, backup_name: str
    ) -> Path | None:
        """Hard-link ``source`` to ``destination``, atomically replacing an existing file.

        The replaced file keeps its bytes under ``backup_name`` beside ``destination``, and the
        replacement goes through ``part_name``. A ``destination`` that already links ``source``
        stays as it is, and a backup an earlier attempt made for it is still the backup. Returns
        the backup, or ``None`` when nothing was replaced. Raises ``SourceGone`` when ``source``
        does not exist.
        """
        ...

    def rename(self, source: Path, destination: Path) -> None:
        """Give the file at ``source`` the name ``destination``, replacing it atomically."""
        ...

    def inode(self, path: Path) -> int | None:
        """The inode number of ``path``, without following a final link; ``None`` when absent."""
        ...

    def remove_file(self, path: Path) -> bool:
        """Remove a file; ``False`` when it was already gone."""
        ...

    def remove_directory(self, path: Path) -> bool:
        """Remove an empty directory; ``False`` when it was already gone."""
        ...

    def ensure_directory(self, path: Path, plan: AclPlan) -> bool:
        """Create ``path`` (its parent must exist) and apply ``plan``; ``True`` when created."""
        ...

    def apply_plan(self, path: Path, plan: AclPlan) -> bool:
        """Apply ``plan`` to an existing directory; ``True`` when anything changed."""
        ...

    def read_acl(self, path: Path) -> Acl:
        """The ACL of ``path``."""
        ...

    def owned_by_me(self, path: Path) -> bool:
        """Whether the current user owns ``path`` (only owners may change its ACL)."""
        ...
