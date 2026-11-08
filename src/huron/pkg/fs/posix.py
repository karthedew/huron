"""POSIX descriptor primitives: every place below a root is opened one name at a time.

Each function takes the descriptor of a parent directory and one name, never a path below the
root. :func:`open_beneath` opens the parent directories with ``O_NOFOLLOW``. A symbolic link at
any step raises :class:`SymlinkError`, and the primitives check the last name with ``lstat``
before they act, because ``unlink``, ``rename`` and ``mkdir`` act on a link itself. Only
:func:`walk` reports a link, as an entry of the kind ``symlink``, and it never enters one.
"""

from __future__ import annotations

import errno
import os
import stat as statmodule
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Generator, Iterable, Iterator
    from pathlib import Path

__all__ = [
    "INHERITING_DIR_MODE",
    "Entry",
    "EntryKind",
    "InheritanceError",
    "RootUnavailable",
    "SourceMismatch",
    "SymlinkError",
    "atomic_write",
    "change_group",
    "change_mode",
    "entry",
    "link_into_place",
    "make_dir",
    "make_inheriting_dir",
    "open_beneath",
    "open_directory",
    "open_entry",
    "open_file",
    "remove_empty_dir",
    "remove_file",
    "walk",
]

#: The permission bits :func:`make_inheriting_dir` asks for; the setgid bit must come from the
#: parent.
INHERITING_DIR_MODE = 0o750

type EntryKind = Literal["file", "dir", "symlink", "other"]

_STEP = os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW
#: How a final name is opened to read it or to change it through its descriptor. A FIFO does not
#: block the open, and a terminal does not become the controlling one.
_FINAL = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_NOCTTY | os.O_CLOEXEC


@dataclass(frozen=True, slots=True)
class Entry:
    """One entry that :func:`walk` found; ``names`` lead to it from the walked directory."""

    names: tuple[str, ...]
    kind: EntryKind
    size: int
    mtime_ns: int


class SymlinkError(OSError):
    """A name is a symbolic link; ``names`` lead to it from the descriptor the caller gave."""

    def __init__(self, names: tuple[str, ...]) -> None:
        super().__init__(errno.ELOOP, "a symbolic link", "/".join(names))
        self.names = names


class RootUnavailable(OSError):
    """The root of :func:`open_beneath` does not open as a directory."""


class SourceMismatch(OSError):
    """The source of :func:`link_into_place` is not a regular file with the expected inode."""


class InheritanceError(OSError):
    """A new directory did not inherit the setgid bit and the group of its parent."""


@contextmanager
def open_beneath(root: Path, names: Iterable[str]) -> Generator[int]:
    """Open ``root``, then each of ``names`` below it, and yield the ``O_PATH`` descriptor.

    Each step is ``openat(O_PATH | O_DIRECTORY | O_NOFOLLOW)`` on the descriptor before it, and
    each descriptor is closed when the next one opens or the ``with`` body ends. A link at a
    step raises :class:`SymlinkError` with the names up to it; any other failure of a step keeps
    its ``OSError``. Raises :class:`RootUnavailable` when ``root`` does not open.
    """
    try:
        descriptor = os.open(root, os.O_PATH | os.O_DIRECTORY)
    except OSError as error:
        raise RootUnavailable(error.errno, error.strerror, str(root)) from error
    walked: list[str] = []
    try:
        for name in names:
            walked.append(name)
            step = _opened(descriptor, name, _STEP, tuple(walked))
            os.close(descriptor)
            descriptor = step
        yield descriptor
    finally:
        os.close(descriptor)


def entry(parent_fd: int, name: str) -> os.stat_result | None:
    """The ``lstat`` of ``name`` in ``parent_fd``; ``None`` when it does not exist.

    Raises :class:`SymlinkError` when ``name`` is a symbolic link.
    """
    try:
        info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if statmodule.S_ISLNK(info.st_mode):
        raise SymlinkError((name,))
    return info


def open_file(parent_fd: int, name: str) -> int:
    """Open the file ``name`` read-only, without following a link; the caller closes it."""
    return _opened(parent_fd, name, _FINAL, (name,))


def open_entry(parent_fd: int, name: str) -> int:
    """Open the file or directory ``name`` read-only, without following a link.

    The caller closes it. Raises ``FileNotFoundError`` when ``name`` does not exist and
    :class:`SymlinkError` when it is a link, also when a link takes its place after the check.
    """
    found = entry(parent_fd, name)
    if found is None:
        raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), name)
    directory = os.O_DIRECTORY if statmodule.S_ISDIR(found.st_mode) else 0
    return _opened(parent_fd, name, _FINAL | directory, (name,))


def change_mode(parent_fd: int, name: str, mode: int) -> bool:
    """Give the entry ``name`` exactly ``mode`` through its own descriptor; ``False`` if it has it.

    The entry is opened with ``O_NOFOLLOW``, so the change never reaches the target of a link.
    """
    descriptor = open_entry(parent_fd, name)
    try:
        if statmodule.S_IMODE(os.fstat(descriptor).st_mode) == mode:
            return False
        os.fchmod(descriptor, mode)
    finally:
        os.close(descriptor)
    return True


def change_group(parent_fd: int, name: str, gid: int) -> bool:
    """Give the entry ``name`` the group ``gid`` through its own descriptor; ``False`` if it has it.

    The entry is opened with ``O_NOFOLLOW``, so the change never reaches the target of a link.
    """
    descriptor = open_entry(parent_fd, name)
    try:
        if os.fstat(descriptor).st_gid == gid:
            return False
        os.fchown(descriptor, -1, gid)
    finally:
        os.close(descriptor)
    return True


def open_directory(parent_fd: int, name: str) -> int:
    """Open the directory ``name`` read-only, so it can be listed; the caller closes it."""
    return _opened(parent_fd, name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, (name,))


def make_dir(parent_fd: int, name: str, mode: int) -> bool:
    """Create the directory ``name`` with exactly ``mode``; ``False`` when it exists.

    ``mkdir`` applies the umask and never sets the setgid bit, so the new directory gets
    ``mode`` with ``fchmod``. An existing directory is not changed.
    """
    if not _made(parent_fd, name, mode):
        return False
    descriptor = open_directory(parent_fd, name)
    try:
        os.fchmod(descriptor, mode)
    finally:
        os.close(descriptor)
    return True


def make_inheriting_dir(parent_fd: int, name: str) -> bool:
    """Create the directory ``name`` with mode ``0750``; it must inherit from its parent.

    ``mkdir`` applies only the permission bits, so the setgid bit and the group of the new
    directory come from the filesystem's inheritance alone. The mode is never fixed with
    ``chmod``: a caller outside the directory's group would clear the setgid bit without an
    error. A directory that did not inherit both is removed again and :class:`InheritanceError`
    is raised. Returns ``False`` for an existing directory, which is adopted as it is.
    """
    if not _made(parent_fd, name, INHERITING_DIR_MODE):
        return False
    made, parent = os.stat(name, dir_fd=parent_fd, follow_symlinks=False), os.fstat(parent_fd)
    if not made.st_mode & statmodule.S_ISGID or made.st_gid != parent.st_gid:
        os.rmdir(name, dir_fd=parent_fd)
        raise InheritanceError(
            errno.EPERM,
            f"the directory did not inherit the setgid bit and the group {parent.st_gid}",
            name,
        )
    return True


def atomic_write(parent_fd: int, name: str, data: bytes, mode: int, part_name: str) -> None:
    """Write ``data`` with exactly ``mode`` to ``name`` through ``part_name`` and a ``rename``.

    A part file that an earlier attempt left is replaced, and the part file is removed when the
    write fails. Raises :class:`SymlinkError` when ``name`` or ``part_name`` is a link.
    """
    entry(parent_fd, name)
    remove_file(parent_fd, part_name)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    try:
        descriptor = os.open(part_name, flags, mode, dir_fd=parent_fd)
        try:
            os.fchmod(descriptor, mode)
            unwritten = memoryview(data)
            while unwritten:
                unwritten = unwritten[os.write(descriptor, unwritten) :]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.rename(part_name, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
    except BaseException:
        remove_file(parent_fd, part_name)
        raise


def link_into_place(
    source_fd: int,
    source_name: str,
    inode: int,
    parent_fd: int,
    name: str,
    part_name: str,
    backup_name: str,
) -> str | None:
    """Hard-link the source to ``name``, replacing an existing ``name`` atomically.

    The source must be a regular file with the inode ``inode``, else :class:`SourceMismatch`;
    a missing source raises ``FileNotFoundError``. A new name is one ``link``. An existing name
    is first linked to ``backup_name`` beside it, so its bytes outlive the replacement, then
    replaced by a link to ``part_name`` and a ``rename`` over it. A part or backup file left by
    an earlier attempt is replaced. A ``name`` that already links the source is left as it is:
    an earlier attempt placed it, and a ``backup_name`` beside it holds the bytes that attempt
    replaced. The directory is flushed to disk afterwards. Returns the backup's name, if any.
    Raises :class:`SymlinkError` when ``name``, ``part_name`` or ``backup_name`` is a link.
    """
    source = os.stat(source_name, dir_fd=source_fd, follow_symlinks=False)
    if not statmodule.S_ISREG(source.st_mode) or source.st_ino != inode:
        raise SourceMismatch(errno.ESTALE, "the source is not the measured file", source_name)
    backup: str | None = None
    existing = entry(parent_fd, name)
    if existing is None:
        _link(source_fd, source_name, parent_fd, name)
    elif os.path.samestat(source, existing):
        return backup_name if entry(parent_fd, backup_name) is not None else None
    else:
        backup = _replace(source_fd, source_name, parent_fd, name, part_name, backup_name)
    _sync(parent_fd)
    return backup


def remove_file(parent_fd: int, name: str) -> bool:
    """Remove the file ``name``; ``False`` when it did not exist. A link is not removed."""
    if entry(parent_fd, name) is None:
        return False
    os.unlink(name, dir_fd=parent_fd)
    return True


def remove_empty_dir(parent_fd: int, name: str) -> bool:
    """Remove the empty directory ``name``; ``False`` when it did not exist.

    Raises ``OSError`` when the directory is not empty. A link is not removed.
    """
    if entry(parent_fd, name) is None:
        return False
    os.rmdir(name, dir_fd=parent_fd)
    return True


def walk(directory_fd: int) -> Iterator[Entry]:
    """Every entry below ``directory_fd``, top-down and sorted by name; links are not entered.

    A directory comes before its entries. A directory that a link replaces during the walk
    raises :class:`SymlinkError` with the names from ``directory_fd`` to it. ``directory_fd``
    must be open for reading, as :func:`open_directory` opens it.
    """
    yield from _walk(directory_fd, ())


def _opened(parent_fd: int, name: str, flags: int, names: tuple[str, ...]) -> int:
    """``openat`` that turns the refusal of a link into :class:`SymlinkError`.

    Linux refuses a link at an ``O_DIRECTORY`` step with ``ENOTDIR`` and a final ``O_NOFOLLOW``
    open of a link with ``ELOOP``. Only an ``lstat`` tells a link from any other entry.
    """
    try:
        return os.open(name, flags, dir_fd=parent_fd)
    except OSError as error:
        if error.errno in {errno.ENOTDIR, errno.ELOOP}:
            found = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            if statmodule.S_ISLNK(found.st_mode):
                raise SymlinkError(names) from error
        raise


def _made(parent_fd: int, name: str, mode: int) -> bool:
    try:
        os.mkdir(name, mode, dir_fd=parent_fd)
    except FileExistsError:
        found = entry(parent_fd, name)
        if found is not None and statmodule.S_ISDIR(found.st_mode):
            return False
        raise
    return True


def _sync(directory_fd: int) -> None:
    descriptor = os.open(".", os.O_RDONLY | os.O_DIRECTORY, dir_fd=directory_fd)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _replace(
    source_fd: int, source_name: str, parent_fd: int, name: str, part_name: str, backup_name: str
) -> str:
    _link_afresh(source_fd, source_name, parent_fd, part_name)
    try:
        _link_afresh(parent_fd, name, parent_fd, backup_name)
        try:
            os.rename(part_name, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        except BaseException:
            remove_file(parent_fd, backup_name)
            raise
    except BaseException:
        remove_file(parent_fd, part_name)
        raise
    return backup_name


def _link_afresh(source_fd: int, source_name: str, parent_fd: int, name: str) -> None:
    remove_file(parent_fd, name)
    _link(source_fd, source_name, parent_fd, name)


def _link(source_fd: int, source_name: str, parent_fd: int, name: str) -> None:
    os.link(source_name, name, src_dir_fd=source_fd, dst_dir_fd=parent_fd, follow_symlinks=False)


def _walk(directory_fd: int, prefix: tuple[str, ...]) -> Iterator[Entry]:
    with os.scandir(directory_fd) as iterator:
        found = sorted(iterator, key=lambda item: item.name)
    for item in found:
        names = (*prefix, item.name)
        info = item.stat(follow_symlinks=False)
        kind = _kind(item)
        yield Entry(names, kind, info.st_size, info.st_mtime_ns)
        if kind == "dir":
            try:
                child = open_directory(directory_fd, item.name)
            except SymlinkError as error:
                raise SymlinkError(names) from error
            try:
                yield from _walk(child, names)
            finally:
                os.close(child)


def _kind(item: os.DirEntry[str]) -> EntryKind:
    if item.is_symlink():
        return "symlink"
    if item.is_dir(follow_symlinks=False):
        return "dir"
    if item.is_file(follow_symlinks=False):
        return "file"
    return "other"
