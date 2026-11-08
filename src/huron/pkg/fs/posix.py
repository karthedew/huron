"""POSIX filesystem operations used by the storage adapter.

Nothing here follows symbolic links when it creates, removes or walks.
"""

from __future__ import annotations

import os
import stat as statmodule
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = [
    "INHERITING_DIR_MODE",
    "Entry",
    "InheritanceError",
    "Stamp",
    "atomic_write",
    "inode",
    "is_dir",
    "link_into_place",
    "make_inheriting_dir",
    "remove_empty_dir",
    "remove_file",
    "stat",
    "walk",
]

#: The permission bits :func:`make_inheriting_dir` asks for; the setgid bit must come from the
#: parent.
INHERITING_DIR_MODE = 0o750

type EntryKind = Literal["file", "dir", "other"]


@dataclass(frozen=True, slots=True)
class Stamp:
    """Size and modification time of a file."""

    size: int
    mtime_ns: int


@dataclass(frozen=True, slots=True)
class Entry:
    """One entry found by :func:`walk`, relative to the walked directory."""

    rel_path: str
    kind: EntryKind
    size: int
    mtime_ns: int
    is_symlink: bool


class InheritanceError(OSError):
    """A new directory did not inherit the setgid bit and the group of its parent."""


def make_inheriting_dir(path: Path) -> bool:
    """Create ``path`` with mode ``0750`` and require the setgid bit and group of its parent.

    ``mkdir`` applies only the permission bits, so the setgid bit and the group of the new
    directory come from the filesystem's inheritance alone. The mode is never fixed with
    ``chmod``: a caller outside the directory's group would clear the setgid bit without an
    error. A directory that did not inherit both is removed again and :class:`InheritanceError`
    is raised. Returns ``False`` for an existing directory, which is adopted as it is.
    """
    try:
        os.mkdir(path, INHERITING_DIR_MODE)
    except FileExistsError:
        if is_dir(path):
            return False
        raise
    made, parent = os.lstat(path), os.lstat(path.parent)
    if not made.st_mode & statmodule.S_ISGID or made.st_gid != parent.st_gid:
        os.rmdir(path)
        raise InheritanceError(
            f"{path} did not inherit the setgid bit and the group {parent.st_gid} of its parent"
        )
    return True


def link_into_place(
    source: Path, destination: Path, part_name: str, backup_name: str
) -> Path | None:
    """Hard-link ``source`` to ``destination``, replacing an existing ``destination`` atomically.

    A new name is one ``link``. An existing name is first linked to ``backup_name`` beside it, so
    its bytes outlive the replacement, then replaced by a link to ``part_name`` and a ``rename``
    over it. A part or backup file left by an earlier attempt is replaced. A ``destination`` that
    already links the inode of ``source`` is left as it is: an earlier attempt placed it, and a
    ``backup_name`` beside it holds the bytes that attempt replaced. The directory is flushed to
    disk afterwards. Returns the backup, if any. Raises ``FileNotFoundError`` when ``source`` does
    not exist.
    """
    backup: Path | None = None
    try:
        os.link(source, destination, follow_symlinks=False)
    except FileExistsError:
        if os.path.samestat(os.lstat(source), os.lstat(destination)):
            earlier = destination.with_name(backup_name)
            return earlier if os.path.lexists(earlier) else None
        backup = _replace(source, destination, part_name, backup_name)
    _sync_directory(destination.parent)
    return backup


def inode(path: Path) -> int:
    """The inode number of ``path``, without following a final symlink."""
    return os.lstat(path).st_ino


def atomic_write(destination: Path, data: bytes, part_suffix: str) -> None:
    """Write ``data`` to ``destination`` through a part file and a rename.

    The part file is ``destination`` plus ``part_suffix``; it is removed when the write fails.
    """
    part = destination.with_name(destination.name + part_suffix)
    remove_file(part)
    try:
        with part.open("xb") as target:
            target.write(data)
            target.flush()
            os.fsync(target.fileno())
        os.rename(part, destination)
    except BaseException:
        remove_file(part)
        raise


def remove_file(path: Path) -> bool:
    """Remove a file or symlink; returns ``False`` when it did not exist."""
    try:
        os.unlink(path)
    except FileNotFoundError:
        return False
    return True


def remove_empty_dir(path: Path) -> bool:
    """Remove an empty directory; returns ``False`` when it did not exist.

    Raises ``OSError`` when the directory is not empty.
    """
    try:
        os.rmdir(path)
    except FileNotFoundError:
        return False
    return True


def walk(root: Path) -> Iterator[Entry]:
    """Yield every entry under ``root`` depth first, sorted by name, without following links."""
    yield from _walk(root, "")


def stat(path: Path) -> Stamp:
    """Return the size and modification time of ``path`` without following a final symlink."""
    info = os.lstat(path)
    return Stamp(info.st_size, info.st_mtime_ns)


def is_dir(path: Path) -> bool:
    """Return whether ``path`` is a real directory (not a symlink to one)."""
    try:
        return statmodule.S_ISDIR(os.lstat(path).st_mode)
    except FileNotFoundError:
        return False


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _replace(source: Path, destination: Path, part_name: str, backup_name: str) -> Path:
    part = _link_afresh(source, destination.with_name(part_name))
    try:
        backup = _link_afresh(destination, destination.with_name(backup_name))
        try:
            os.rename(part, destination)
        except BaseException:
            remove_file(backup)
            raise
    except BaseException:
        remove_file(part)
        raise
    return backup


def _link_afresh(source: Path, name: Path) -> Path:
    try:
        os.link(source, name, follow_symlinks=False)
    except FileExistsError:
        os.unlink(name)
        os.link(source, name, follow_symlinks=False)
    return name


def _walk(root: Path, prefix: str) -> Iterator[Entry]:
    with os.scandir(root) as iterator:
        entries = sorted(iterator, key=lambda entry: entry.name)
    for entry in entries:
        rel_path = f"{prefix}{entry.name}"
        info = entry.stat(follow_symlinks=False)
        is_link = entry.is_symlink()
        kind: EntryKind
        if is_link:
            kind = "other"
        elif entry.is_dir(follow_symlinks=False):
            kind = "dir"
        elif entry.is_file(follow_symlinks=False):
            kind = "file"
        else:
            kind = "other"
        yield Entry(rel_path, kind, info.st_size, info.st_mtime_ns, is_link)
        if kind == "dir":
            yield from _walk(Path(entry.path), rel_path + "/")
