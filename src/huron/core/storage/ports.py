"""The storage ports: reading the share, and writing it through the one writer."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Literal, Protocol

from huron.pkg.fs.posix import Entry

if TYPE_CHECKING:
    from collections.abc import Iterator

    from huron.core.storage.lakepath import LakePath

__all__ = [
    "SHARE_GROUP_PENDING",
    "Entry",
    "GroupOutcome",
    "GroupResult",
    "OpenFile",
    "Outcome",
    "ShareReader",
    "ShareWarning",
    "Stat",
    "StatKind",
    "Storage",
]

#: The warning code of a share group that is recorded but not yet set on disk.
SHARE_GROUP_PENDING = "SHARE_GROUP_PENDING"


type StatKind = Literal["file", "dir", "other"]


@dataclass(frozen=True, slots=True)
class Stat:
    """One entry on the lake, never a symbolic link.

    ``mode`` holds the permission bits with the setgid bit; ``inode`` is the inode number.
    """

    kind: StatKind
    mode: int
    gid: int
    inode: int
    size: int


class Outcome(StrEnum):
    """What a removal did: removed the entry, found nothing, or kept what it found."""

    REMOVED = "removed"
    MISSING = "missing"
    KEPT = "kept"


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

    def warning(self, group: str | int) -> ShareWarning | None:
        """The ``SHARE_GROUP_PENDING`` warning about ``group`` of a ``PENDING`` result, else
        ``None``.
        """
        if self.outcome is not GroupOutcome.PENDING:
            return None
        return ShareWarning(SHARE_GROUP_PENDING, f"{group}", self.reason or "")


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
    """Read-only operations on the lake.

    Every place is a :class:`LakePath` below the storage root. A symbolic link at any step of
    it raises ``SymlinkInLake``; only :meth:`walk` reports a link, and never enters it.
    """

    def stat(self, location: LakePath) -> Stat | None:
        """The entry at ``location``; ``None`` when it does not exist."""
        ...

    def read_bytes(self, location: LakePath) -> bytes | None:
        """The bytes of a file, or ``None`` when it does not exist."""
        ...

    def is_empty(self, location: LakePath) -> bool:
        """Whether the directory has no entry; a link counts as an entry."""
        ...

    def walk(self, location: LakePath) -> Iterator[Entry]:
        """Every entry below the directory, top-down and sorted by name."""
        ...

    def open_file(self, location: LakePath) -> OpenFile | None:
        """Open a file read-only; ``None`` when it does not exist. The caller closes it."""
        ...


class Storage(ShareReader, Protocol):
    """Every operation on the lake, writes included."""

    def make_directory(self, location: LakePath, mode: int) -> bool:
        """Create a directory with exactly ``mode`` (its parent must exist); ``True`` if made.

        An existing directory is left as it is.
        """
        ...

    def make_inheriting_dir(self, location: LakePath) -> bool:
        """Create a directory with mode ``0750``; ``True`` when made, an existing one is kept.

        The setgid bit and the group come only from the parent's inheritance. A new directory
        without them is removed again and refused; the mode is never fixed with ``chmod``.
        """
        ...

    def set_mode(self, location: LakePath, mode: int) -> bool:
        """Give the entry exactly ``mode``; ``True`` when the mode changed."""
        ...

    def set_group(self, location: LakePath, group: str | int) -> GroupResult:
        """Try to give the entry the group ``group``, a name or a gid.

        A refusal, or a name this machine cannot resolve, is ``PENDING``, not an error.
        """
        ...

    def write_bytes(self, location: LakePath, data: bytes, mode: int) -> None:
        """Write ``data`` atomically to a file with exactly ``mode``."""
        ...

    def link(
        self,
        source: LakePath,
        destination: LakePath,
        *,
        inode: int,
        part_name: str,
        backup_name: str,
    ) -> LakePath | None:
        """Hard-link ``source`` to ``destination``, atomically replacing an existing file.

        ``source`` must be a regular file with the inode ``inode``, else ``SourceGone``. The
        replaced file keeps its bytes under ``backup_name`` beside ``destination``, and the
        replacement goes through ``part_name``. A ``destination`` that already links ``source``
        stays as it is, and a backup an earlier attempt made for it is still the backup.
        Returns the backup, or ``None`` when nothing was replaced.
        """
        ...

    def rename(self, source: LakePath, destination: LakePath) -> None:
        """Give the file at ``source`` the name ``destination``, replacing it atomically."""
        ...

    def remove_file(self, location: LakePath, *, inode: int | None = None) -> Outcome:
        """Remove a file; with ``inode``, only while the file has that inode.

        ``MISSING`` when there is no file, ``KEPT`` when its inode is another.
        """
        ...

    def remove_directory(self, location: LakePath) -> Outcome:
        """Remove an empty directory; ``KEPT`` when it has entries, ``MISSING`` when absent."""
        ...
