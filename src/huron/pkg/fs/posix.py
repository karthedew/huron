"""POSIX filesystem operations used by the storage adapter.

Nothing here follows symbolic links when it creates, removes or walks.
"""

from __future__ import annotations

import os
import stat as statmodule
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from huron.pkg.hashing import sha256_copy

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = [
    "INHERITING_DIR_MODE",
    "PART_SUFFIX",
    "Entry",
    "InheritanceError",
    "Stamp",
    "atomic_copy",
    "atomic_write",
    "inode",
    "is_dir",
    "link_into_place",
    "make_dir",
    "make_inheriting_dir",
    "remove_empty_dir",
    "remove_file",
    "stat",
    "walk",
]

PART_SUFFIX = ".huron-part"
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


def make_dir(path: Path, mode: int) -> bool:
    """Create ``path`` with ``mode`` exactly, or fix the mode of an existing directory.

    Returns ``True`` when the directory was created. Raises ``NotADirectoryError`` when ``path``
    exists as anything other than a real directory (a symlink to a directory included).
    """
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        os.mkdir(path, mode)
        os.chmod(path, mode)
        return True
    if not statmodule.S_ISDIR(info.st_mode):
        raise NotADirectoryError(str(path))
    if statmodule.S_IMODE(info.st_mode) != mode:
        os.chmod(path, mode)
    return False


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


def link_into_place(source: Path, destination: Path, part_name: str) -> None:
    """Hard-link ``source`` to ``destination``, replacing an existing ``destination`` atomically.

    A new name is one ``link``. An existing name is replaced by a link to ``part_name`` beside
    it and a ``rename`` over it; a part file left by an earlier attempt is replaced first. The
    directory is flushed to disk afterwards. Raises ``FileNotFoundError`` when ``source`` does
    not exist.
    """
    try:
        os.link(source, destination, follow_symlinks=False)
    except FileExistsError:
        part = destination.with_name(part_name)
        try:
            os.link(source, part, follow_symlinks=False)
        except FileExistsError:
            os.unlink(part)
            os.link(source, part, follow_symlinks=False)
        try:
            os.rename(part, destination)
        finally:
            # rename does nothing when both names already link one inode; the part stays then.
            remove_file(part)
    _sync_directory(destination.parent)


def inode(path: Path) -> int:
    """The inode number of ``path``, without following a final symlink."""
    return os.lstat(path).st_ino


def atomic_copy(source: Path, destination: Path, part_suffix: str = PART_SUFFIX) -> tuple[int, str]:
    """Copy ``source`` to ``destination`` through a part file, returning ``(size, sha256)``.

    The bytes are written to ``destination`` plus ``part_suffix``, flushed to disk and renamed
    over ``destination``. On failure the part file is removed and the error re-raised; an existing
    ``destination`` is left untouched.
    """
    part = destination.with_name(destination.name + part_suffix)
    remove_file(part)
    descriptor = os.open(part, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o660)
    try:
        with os.fdopen(descriptor, "wb") as target, source.open("rb") as origin:
            size, digest = sha256_copy(origin, target)
            target.flush()
            os.fsync(target.fileno())
        os.rename(part, destination)
    except BaseException:
        remove_file(part)
        raise
    return size, digest


def atomic_write(destination: Path, data: bytes, part_suffix: str = PART_SUFFIX) -> None:
    """Write ``data`` to ``destination`` through a part file and a rename."""
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
