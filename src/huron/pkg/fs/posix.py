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

from huron.pkg.hashing import CHUNK_SIZE, sha256_descriptor

if TYPE_CHECKING:
    from collections.abc import Generator, Iterable, Iterator
    from pathlib import Path

__all__ = [
    "INHERITED_MODE",
    "INHERITING_DIR_MODE",
    "ChangeRefused",
    "Entry",
    "EntryKind",
    "FileError",
    "InheritanceError",
    "PartBlocked",
    "RootUnavailable",
    "SealedFile",
    "SizeMismatch",
    "SourceMismatch",
    "SymlinkError",
    "atomic_write",
    "change_group",
    "change_mode",
    "copy_sealed",
    "entry",
    "link_into_place",
    "link_once",
    "make_dir",
    "make_inheriting_dir",
    "open_beneath",
    "open_directory",
    "open_file",
    "remove_empty_dir",
    "remove_file",
    "sync_directory",
    "walk",
]

#: The permission bits :func:`make_inheriting_dir` asks for; the setgid bit must come from the
#: parent.
INHERITING_DIR_MODE = 0o750
#: The mode of a directory that :func:`make_inheriting_dir` keeps: ``0750`` and the setgid bit.
INHERITED_MODE = INHERITING_DIR_MODE | statmodule.S_ISGID

type EntryKind = Literal["file", "dir", "symlink", "other"]

_STEP = os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW
#: How a final name is opened to read it or to change it through its descriptor. A FIFO does not
#: block the open, and a terminal does not become the controlling one.
_FINAL = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_NOCTTY | os.O_CLOEXEC
#: How :func:`copy_sealed` creates its file: only a new name, never through a link.
_NEW_FILE = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC


@dataclass(frozen=True, slots=True)
class Entry:
    """One entry that :func:`walk` found; ``names`` lead to it from the walked directory."""

    names: tuple[str, ...]
    kind: EntryKind
    size: int
    mtime_ns: int


@dataclass(frozen=True, slots=True)
class SealedFile:
    """A file that :func:`copy_sealed` wrote, measured on a new descriptor after its sync.

    ``size`` is in bytes, ``sha256`` is the digest of the bytes and ``inode`` is the inode
    number of the new file.
    """

    size: int
    sha256: str
    inode: int


class SymlinkError(OSError):
    """A name is a symbolic link; ``names`` lead to it from the descriptor the caller gave."""

    def __init__(self, names: tuple[str, ...]) -> None:
        super().__init__(errno.ELOOP, "a symbolic link", "/".join(names))
        self.names = names


class RootUnavailable(OSError):
    """The root of :func:`open_beneath` does not open as a directory."""


class SourceMismatch(OSError):
    """The source of :func:`link_into_place` is not a regular file with the expected inode."""


class SizeMismatch(OSError):
    """The copy of :func:`copy_sealed` does not have the expected size; ``size`` is its size."""

    def __init__(self, size: int) -> None:
        super().__init__(errno.EIO, f"the copy has {size} bytes")
        self.size = size


class InheritanceError(OSError):
    """A new directory did not inherit the setgid bit and the group of its parent."""


class PartBlocked(OSError):
    """A directory has the name of a part or backup file; ``filename`` is that name.

    :func:`atomic_write` and :func:`link_into_place` raise it before any change.
    """


class ChangeRefused(OSError):
    """The filesystem refused the ``chown`` of :func:`change_group`."""


class FileError(OSError):
    """An operation failed on a known file, with its original error and descriptor-relative name."""

    def __init__(self, name: str, error: OSError) -> None:
        super().__init__(error.errno, error.strerror, name)
        self.error = error


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
            # A failed close can release the old descriptor. Never close it twice.
            previous, descriptor = descriptor, step
            os.close(previous)
        yield descriptor
    except BaseException as error:
        with _cleanup_errors(error, "close parent directory"):
            os.close(descriptor)
        raise
    else:
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


def change_mode(parent_fd: int, name: str, mode: int) -> bool:
    """Give the entry ``name`` exactly ``mode``; ``False`` when it has it already.

    The change is ``fchmodat`` with ``AT_SYMLINK_NOFOLLOW`` on the parent's descriptor, so it
    needs no read access to the entry: a directory that this process cannot read or search
    changes too. ``fchmodat`` refuses to change a link, and Python reports that refusal with
    ``ValueError``. An ``lstat`` then tells a link that took the name's place after the check
    (:class:`SymlinkError`) from a filesystem that refuses the change for another reason.
    Raises ``FileNotFoundError`` when ``name`` does not exist.
    """
    if statmodule.S_IMODE(_existing(parent_fd, name).st_mode) == mode:
        return False
    try:
        os.chmod(name, mode, dir_fd=parent_fd, follow_symlinks=False)
    except ValueError as error:
        entry(parent_fd, name)
        raise OSError(
            errno.EOPNOTSUPP, "the filesystem cannot change a mode without following links", name
        ) from error
    return True


def change_group(parent_fd: int, name: str, gid: int) -> bool:
    """Give the entry ``name`` the group ``gid``; ``False`` when it has it already.

    The change is ``fchownat`` with ``AT_SYMLINK_NOFOLLOW`` on the parent's descriptor, so it
    needs no read access to the entry and never reaches the target of a link. A link that takes
    the name's place after the check gets the group itself, and the ``lstat`` after the change
    refuses it with :class:`SymlinkError`. Raises ``FileNotFoundError`` when ``name`` does not
    exist, and :class:`ChangeRefused` when the filesystem refuses the ``chown``.
    """
    current = _existing(parent_fd, name).st_gid
    if current != gid:
        try:
            os.chown(name, -1, gid, dir_fd=parent_fd, follow_symlinks=False)
        except OSError as error:
            raise ChangeRefused(error.errno, error.strerror, name) from error
    entry(parent_fd, name)
    return current != gid


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
    error. So the umask must keep the bits of ``0750`` (the API runs with umask ``022``). A
    directory that did not inherit both, or whose mode is not ``2750``, is removed again and
    :class:`InheritanceError` is raised. Returns ``False`` for an existing directory, which is
    adopted as it is.
    """
    if not _made(parent_fd, name, INHERITING_DIR_MODE):
        return False
    made, parent = os.stat(name, dir_fd=parent_fd, follow_symlinks=False), os.fstat(parent_fd)
    mode = statmodule.S_IMODE(made.st_mode)
    if not made.st_mode & statmodule.S_ISGID or made.st_gid != parent.st_gid:
        reason = f"the directory did not inherit the setgid bit and the group {parent.st_gid}"
    elif mode != INHERITED_MODE:
        reason = f"the directory has the mode {mode:o}, not {INHERITED_MODE:o}"
    else:
        return True
    os.rmdir(name, dir_fd=parent_fd)
    raise InheritanceError(errno.EPERM, reason, name)


def atomic_write(parent_fd: int, name: str, data: bytes, mode: int, part_name: str) -> None:
    """Write ``data`` with exactly ``mode`` to ``name`` through ``part_name`` and a ``rename``.

    A part file that an earlier attempt left is replaced. A failed write attempts to remove it.
    Raises :class:`SymlinkError` when ``name`` or ``part_name`` is a link, and
    :class:`PartBlocked` when ``part_name`` is a directory. :class:`FileError` identifies errors
    on the part file. Parent-access failures during creation or removal keep their original error.
    Cleanup errors become notes on the primary exception, without changing its message or cause.
    """
    entry(parent_fd, name)
    with _file_errors(part_name):
        _require_no_directory(parent_fd, part_name)
    _remove_write_part(parent_fd, part_name)
    try:
        _write_part(parent_fd, part_name, data, mode)
        os.rename(part_name, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
    except BaseException as error:
        with _cleanup_errors(error, f"remove {part_name!r}"):
            _remove_write_part(parent_fd, part_name)
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
    Raises, before any change, :class:`SymlinkError` when ``name``, ``part_name`` or
    ``backup_name`` is a link, ``IsADirectoryError`` when ``name`` is a directory, and
    :class:`PartBlocked` when ``part_name`` or ``backup_name`` is a directory and ``name``
    exists.
    """
    source = os.stat(source_name, dir_fd=source_fd, follow_symlinks=False)
    if not statmodule.S_ISREG(source.st_mode) or source.st_ino != inode:
        raise SourceMismatch(errno.ESTALE, "the source is not the measured file", source_name)
    backup: str | None = None
    existing = entry(parent_fd, name)
    if existing is not None and statmodule.S_ISDIR(existing.st_mode):
        raise IsADirectoryError(errno.EISDIR, os.strerror(errno.EISDIR), name)
    if existing is None:
        _link(source_fd, source_name, parent_fd, name)
    elif os.path.samestat(source, existing):
        return backup_name if entry(parent_fd, backup_name) is not None else None
    else:
        _require_no_directory(parent_fd, part_name)
        _require_no_directory(parent_fd, backup_name)
        backup = _replace(source_fd, source_name, parent_fd, name, part_name, backup_name)
    _sync(parent_fd)
    return backup


def copy_sealed(source_fd: int, parent_fd: int, name: str, size: int, mode: int) -> SealedFile:
    """Copy the bytes of the open file ``source_fd`` to the new file ``name`` with exactly ``mode``.

    The source can be on another filesystem: the bytes go through this process. ``name`` is
    created only when it does not exist (``O_EXCL``), and the copy is synced to disk before it
    is closed. The copy stops one byte after ``size``, so a source that grows without end
    cannot fill the disk. A new read-only descriptor then measures the size, the sha256 and the
    inode, so the result describes the bytes on the server and not a cache. Last, the directory
    is synced, so the new name is durable too. The copy is never opened for a write again.
    Raises :class:`SymlinkError` when ``name`` is a link, ``FileExistsError`` when it exists,
    and :class:`SizeMismatch` when the copy does not have ``size`` bytes. A failure after the
    create, a failed sync of the directory included, removes the copy again.
    """
    entry(parent_fd, name)
    descriptor = os.open(name, _NEW_FILE, mode, dir_fd=parent_fd)
    try:
        _fill(descriptor, source_fd, size, mode)
        sealed = _measure(parent_fd, name)
        if sealed.size != size:
            raise SizeMismatch(sealed.size)
        _sync(parent_fd)
    except BaseException as error:
        with _cleanup_errors(error, f"remove {name!r}"):
            os.unlink(name, dir_fd=parent_fd)
        raise
    return sealed


def link_once(source_fd: int, source_name: str, parent_fd: int, name: str) -> None:
    """Hard-link the file ``source_name`` to the new name ``name``; an existing name stays.

    The source must be checked by the caller. Raises :class:`SymlinkError` when ``name`` is a
    link, ``FileExistsError`` when it exists, and the error of ``link`` for every other
    failure: ``EXDEV`` when the two names are on two filesystems or two mounts.
    """
    entry(parent_fd, name)
    _link(source_fd, source_name, parent_fd, name)


def sync_directory(parent_fd: int, name: str) -> None:
    """Flush the directory ``name`` to disk, so that its new and removed names are durable.

    Raises :class:`SymlinkError` when ``name`` is a link and ``NotADirectoryError`` when it is
    not a directory.
    """
    descriptor = open_directory(parent_fd, name)
    try:
        os.fsync(descriptor)
    except BaseException as error:
        with _cleanup_errors(error, f"close {name!r}"):
            os.close(descriptor)
        raise
    os.close(descriptor)


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


@contextmanager
def _cleanup_errors(primary: BaseException, operation: str) -> Generator[None]:
    """Keep ordinary cleanup errors as diagnostics, but let process-control exceptions propagate."""
    try:
        yield
    except OSError as secondary:
        primary.add_note(f"{operation} failed: [Errno {secondary.errno}] {secondary.strerror}")


@contextmanager
def _file_errors(name: str, *, parent_access: bool = False) -> Generator[None]:
    """Keep a known file's origin without trusting a system exception's filename."""
    try:
        yield
    except (SymlinkError, PartBlocked):
        raise
    except OSError as error:
        if parent_access and isinstance(error, PermissionError):
            raise
        raise FileError(name, error) from error


def _remove_write_part(parent_fd: int, name: str) -> None:
    with _file_errors(name):
        found = entry(parent_fd, name)
    if found is not None:
        with _file_errors(name, parent_access=True):
            os.unlink(name, dir_fd=parent_fd)


def _write_part(parent_fd: int, name: str, data: bytes, mode: int) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    with _file_errors(name, parent_access=True):
        descriptor = os.open(name, flags, mode, dir_fd=parent_fd)
    with _file_errors(name):
        try:
            os.fchmod(descriptor, mode)
            unwritten = memoryview(data)
            while unwritten:
                unwritten = unwritten[os.write(descriptor, unwritten) :]
            os.fsync(descriptor)
        except BaseException as error:
            with _cleanup_errors(error, f"close {name!r}"):
                os.close(descriptor)
            raise
        else:
            os.close(descriptor)


def _fill(descriptor: int, source_fd: int, size: int, mode: int) -> None:
    """Give the new file ``mode``, copy the bytes of ``source_fd`` into it, sync and close it.

    The copy stops at the end of the source or one byte after ``size``: that byte is enough to
    show that the source has another size.
    """
    try:
        os.fchmod(descriptor, mode)
        offset = 0
        while offset <= size and (
            block := os.pread(source_fd, min(CHUNK_SIZE, size + 1 - offset), offset)
        ):
            unwritten = memoryview(block)
            while unwritten:
                unwritten = unwritten[os.write(descriptor, unwritten) :]
            offset += len(block)
        os.fsync(descriptor)
    except BaseException as error:
        with _cleanup_errors(error, "close the copy"):
            os.close(descriptor)
        raise
    os.close(descriptor)


def _measure(parent_fd: int, name: str) -> SealedFile:
    """The size, the sha256 and the inode of the file ``name``, read on a new descriptor."""
    descriptor = open_file(parent_fd, name)
    try:
        info = os.fstat(descriptor)
        sealed = SealedFile(info.st_size, sha256_descriptor(descriptor), info.st_ino)
    except BaseException as error:
        with _cleanup_errors(error, f"close {name!r}"):
            os.close(descriptor)
        raise
    os.close(descriptor)
    return sealed


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


def _require_no_directory(parent_fd: int, name: str) -> None:
    """Refuse a link (:class:`SymlinkError`) or a directory (:class:`PartBlocked`) at ``name``."""
    found = entry(parent_fd, name)
    if found is not None and statmodule.S_ISDIR(found.st_mode):
        raise PartBlocked(errno.EISDIR, os.strerror(errno.EISDIR), name)


def _existing(parent_fd: int, name: str) -> os.stat_result:
    """The ``lstat`` of ``name``; ``FileNotFoundError`` when it does not exist, and
    :class:`SymlinkError` when it is a link.
    """
    found = entry(parent_fd, name)
    if found is None:
        raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), name)
    return found


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
        kind = _kind(info.st_mode)
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


def _kind(mode: int) -> EntryKind:
    if statmodule.S_ISLNK(mode):
        return "symlink"
    if statmodule.S_ISDIR(mode):
        return "dir"
    if statmodule.S_ISREG(mode):
        return "file"
    return "other"
