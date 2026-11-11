"""The lake as a POSIX filesystem, opened one name at a time from the root."""

from __future__ import annotations

import errno
import grp
import os
import stat
from contextlib import contextmanager
from typing import TYPE_CHECKING

from huron.core.storage.errors import (
    InheritanceFailed,
    LakeUnavailable,
    SourceGone,
    SourceSizeMismatch,
    StorageError,
    SymlinkInLake,
)
from huron.core.storage.lakepath import LakePath
from huron.core.storage.layout import FILE_MODE
from huron.core.storage.ports import GroupOutcome, GroupResult, Outcome, Stat
from huron.pkg.fs import posix
from huron.pkg.hashing import CHUNK_SIZE, sha256_descriptor
from huron.schema.naming import PART_SUFFIX, check_lake_name

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Iterator
    from pathlib import Path

    from huron.core.storage.ports import Entry, SealedFile, StatKind

__all__ = ["AUTH_SYS_GROUPS", "PosixStorage"]

#: The supplementary groups that an AUTH_SYS request carries to an NFS server; the server does
#: not see the groups after them.
AUTH_SYS_GROUPS = 16


class PosixStorage:
    """Storage over the directory ``root``, which every :class:`LakePath` lies below.

    Each operation opens ``root``, then each parent name with ``O_NOFOLLOW``, and acts on the
    last name through its parent's descriptor. A symbolic link at any step is
    ``SymlinkInLake``; a ``root`` that does not open is ``LakeUnavailable``.
    """

    def __init__(self, root: Path) -> None:
        self._root = root

    @property
    def root(self) -> Path:
        """The directory that every lake path lies below."""
        return self._root

    def stat(self, location: LakePath) -> Stat | None:
        """The entry at ``location``; ``None`` when it does not exist."""
        try:
            with self._parent(location) as parent:
                info = posix.entry(parent, _name(location))
        except _Missing:
            return None
        if info is None:
            return None
        kind = _kind(info.st_mode)
        return Stat(kind, stat.S_IMODE(info.st_mode), info.st_gid, info.st_ino, info.st_size)

    def read_bytes(self, location: LakePath) -> bytes | None:
        """The bytes of a file, or ``None`` when it does not exist."""
        try:
            with self._parent(location) as parent:
                descriptor = posix.open_file(parent, _name(location))
                try:
                    _require_file(descriptor, location)
                    return _read_all(descriptor)
                finally:
                    os.close(descriptor)
        except _Missing:
            return None

    def is_empty(self, location: LakePath) -> bool:
        """Whether the directory has no entry; reads at most one entry."""
        with self._parent(location) as parent:
            descriptor = posix.open_directory(parent, _name(location))
            try:
                with os.scandir(descriptor) as entries:
                    return next(entries, None) is None
            finally:
                os.close(descriptor)

    def walk(self, location: LakePath) -> Iterator[Entry]:
        """Every entry below the directory, top-down and sorted; a link is yielded, not entered."""
        with self._parent(location) as parent:
            descriptor = posix.open_directory(parent, _name(location))
        try:
            yield from posix.walk(descriptor)
        except posix.SymlinkError as error:
            raise SymlinkInLake(location.joinpath(*error.names)) from error
        except OSError as error:
            raise _storage_error(location, error) from error
        finally:
            os.close(descriptor)

    def open_file(self, location: LakePath) -> _PosixFile | None:
        """Open a file read-only; ``None`` when it does not exist.

        Opening makes an NFS client read the file's attributes again, so the descriptor's size
        and inode are the server's.
        """
        try:
            with self._parent(location) as parent:
                descriptor = posix.open_file(parent, _name(location))
        except _Missing:
            return None
        try:
            _require_file(descriptor, location)
            return _PosixFile(location, descriptor)
        except BaseException:
            os.close(descriptor)
            raise

    def make_directory(self, location: LakePath, mode: int) -> bool:
        """Create a directory with exactly ``mode``; an existing directory is left as it is."""
        with self._parent(location) as parent:
            return posix.make_dir(parent, _name(location), mode)

    def make_inheriting_dir(self, location: LakePath) -> bool:
        """Create a directory with mode ``0750``; it must inherit setgid and group.

        A new directory without them is removed again and refused with ``InheritanceFailed``.
        """
        with self._parent(location) as parent:
            try:
                return posix.make_inheriting_dir(parent, _name(location))
            except posix.InheritanceError as error:
                raise InheritanceFailed(location, f"{error.strerror}") from error

    def set_mode(self, location: LakePath, mode: int) -> bool:
        """Give the entry exactly ``mode``; ``False`` when it already has it."""
        with self._parent(location) as parent:
            return posix.change_mode(parent, _name(location), mode)

    def set_group(self, location: LakePath, group: str | int) -> GroupResult:
        """Give the entry the group ``group``, a name or a gid.

        An unknown name, a missing entry or a refused ``chown`` is ``PENDING``; any other
        failure is an error, as in every other operation.
        """
        try:
            gid = group if isinstance(group, int) else grp.getgrnam(group).gr_gid
        except KeyError:
            return GroupResult.unknown(f"{group}")
        try:
            with self._parent(location) as parent:
                try:
                    changed = posix.change_group(parent, _name(location), gid)
                except posix.ChangeRefused as error:
                    return GroupResult(GroupOutcome.PENDING, f"{location}: {error.strerror}")
        except _Missing as missing:
            return GroupResult(GroupOutcome.PENDING, missing.message)
        return GroupResult(GroupOutcome.CHANGED if changed else GroupOutcome.UNCHANGED)

    def write_bytes(self, location: LakePath, data: bytes, mode: int) -> None:
        """Write ``data`` atomically to a file with exactly ``mode``.

        A link or a directory at the part file ``<name>.huron-part`` refuses the write, and the
        error names the part file.
        """
        name = _name(location)
        part = f"{name}{PART_SUFFIX}"
        with self._parent(location) as parent:
            try:
                posix.atomic_write(parent, name, data, mode, part)
            except posix.FileError as error:
                raise _storage_error(location.parent.joinpath(part), error.error) from error
            except posix.PartBlocked as error:
                raise _blocked(location, error) from error

    def link(
        self,
        source: LakePath,
        destination: LakePath,
        *,
        inode: int,
        part_name: str,
        backup_name: str,
    ) -> LakePath | None:
        """Hard-link ``source`` to ``destination``; the replaced file stays as ``backup_name``.

        Raises ``SourceGone`` when ``source`` is missing or is not a regular file with the inode
        ``inode``, ``SymlinkInLake`` for a link at ``source``, a ``StorageError`` (``ENOENT``)
        for a missing parent of ``source``, and ``NAME_INVALID`` before any change when
        ``part_name`` or ``backup_name`` is not one name. A failure to look up ``source`` names
        ``source``. A directory at ``part_name`` or ``backup_name`` names that file. Any other
        failure names ``destination``.
        """
        check_lake_name(part_name)
        check_lake_name(backup_name)
        with self._parent(source) as source_parent:
            posix.entry(source_parent, source.name)
            with self._parent(destination) as parent:
                try:
                    backup = posix.link_into_place(
                        source_parent,
                        source.name,
                        inode,
                        parent,
                        destination.name,
                        part_name,
                        backup_name,
                    )
                except (FileNotFoundError, posix.SourceMismatch) as error:
                    raise SourceGone(source) from error
                except posix.PartBlocked as error:
                    raise _blocked(destination, error) from error
        return None if backup is None else destination.parent.joinpath(backup)

    def rename(self, source: LakePath, destination: LakePath) -> None:
        """Give the file at ``source`` the name ``destination``, replacing it atomically.

        A directory at ``source`` is refused, and two names of one file change nothing. A
        failure of the ``rename`` itself names ``destination``, as the system does not tell which
        of the two directories refused it.
        """
        with self._parent(source) as source_parent:
            found = posix.entry(source_parent, source.name)
            if found is None:
                raise _Missing(source)
            if stat.S_ISDIR(found.st_mode):
                raise _not_a_file(source, errno.EISDIR)
            with self._parent(destination) as parent:
                posix.entry(parent, destination.name)
                os.rename(
                    source.name, destination.name, src_dir_fd=source_parent, dst_dir_fd=parent
                )

    def copy_sealed(
        self, source: LakePath, destination: LakePath, expected_size: int
    ) -> SealedFile:
        """Copy the file ``source`` to the new file ``destination`` with mode ``0644``.

        The source is opened and checked first: a missing source or one that is not a regular
        file is ``SourceGone``, and a size other than ``expected_size`` is
        ``SourceSizeMismatch``. Then :func:`~huron.pkg.fs.posix.copy_sealed` makes the copy, and
        a failure names ``destination``.
        """
        with self._parent(source) as source_parent:
            try:
                descriptor = posix.open_file(source_parent, source.name)
            except FileNotFoundError as error:
                raise SourceGone(source) from error
        try:
            found = _guard(lambda: os.fstat(descriptor), source)
            if not stat.S_ISREG(found.st_mode):
                raise SourceGone(source)
            if found.st_size != expected_size:
                raise SourceSizeMismatch(source, expected_size, found.st_size)
            with self._parent(destination) as parent:
                try:
                    return posix.copy_sealed(
                        descriptor, parent, destination.name, expected_size, FILE_MODE
                    )
                except posix.SizeMismatch as error:
                    raise SourceSizeMismatch(source, expected_size, error.size) from error
        finally:
            os.close(descriptor)

    def link_once(self, source: LakePath, destination: LakePath) -> None:
        """Hard-link the file ``source`` to the new name ``destination``; nothing is replaced.

        A failure to look up ``source`` names ``source``; a failure of the link names
        ``destination``, an ``EXDEV`` across two mounts included.
        """
        with self._parent(source) as source_parent:
            found = posix.entry(source_parent, source.name)
            if found is None:
                raise _Missing(source)
            if stat.S_ISDIR(found.st_mode):
                raise _not_a_file(source, errno.EISDIR)
            with self._parent(destination) as parent:
                posix.link_once(source_parent, source.name, parent, destination.name)

    def sync_directory(self, location: LakePath) -> None:
        """Flush the directory ``location`` to disk with ``fsync``."""
        with self._parent(location) as parent:
            posix.sync_directory(parent, _name(location))

    def remove_file(self, location: LakePath, *, inode: int | None = None) -> Outcome:
        """Remove a file; with ``inode``, only while the file has that inode."""
        name = _name(location)
        try:
            with self._parent(location) as parent:
                found = posix.entry(parent, name)
                if found is not None and inode is not None and found.st_ino != inode:
                    return Outcome.KEPT
                removed = found is not None and posix.remove_file(parent, name)
        except _Missing:
            return Outcome.MISSING
        return Outcome.REMOVED if removed else Outcome.MISSING

    def remove_directory(self, location: LakePath) -> Outcome:
        """Remove an empty directory; ``KEPT`` when it has entries, ``MISSING`` when absent."""
        try:
            with self._parent(location) as parent:
                try:
                    removed = posix.remove_empty_dir(parent, _name(location))
                except OSError as error:
                    if error.errno not in {errno.ENOTEMPTY, errno.EEXIST}:
                        raise
                    return Outcome.KEPT
        except _Missing:
            return Outcome.MISSING
        return Outcome.REMOVED if removed else Outcome.MISSING

    def in_group(self, gid: int) -> bool:
        """Whether ``gid`` is the effective group or one of the first :data:`AUTH_SYS_GROUPS`
        supplementary groups, the only ones that the server sees.
        """
        return gid == os.getegid() or gid in os.getgroups()[:AUTH_SYS_GROUPS]

    @contextmanager
    def _parent(self, location: LakePath) -> Generator[int]:
        """The descriptor of the directory that holds ``location``, with its errors mapped.

        A link names its lake path: a step of the traversal, or a name in that directory.
        """
        directory = location.parent
        try:
            with posix.open_beneath(self._root, directory.names) as descriptor:
                try:
                    yield descriptor
                except posix.SymlinkError as error:
                    raise SymlinkInLake(directory.joinpath(*error.names)) from error
        except posix.SymlinkError as error:
            raise SymlinkInLake(LakePath(error.names)) from error
        except posix.RootUnavailable as error:
            raise LakeUnavailable(
                f"the lake does not open as a directory: {error.strerror}", {"path": str(location)}
            ) from error
        except OSError as error:
            raise _storage_error(location, error) from error


class _PosixFile:
    """A read-only descriptor of a file on the lake."""

    def __init__(self, location: LakePath, descriptor: int) -> None:
        self._location = location
        self._descriptor = descriptor
        info = _guard(lambda: os.fstat(descriptor), location)
        self.size = info.st_size
        self.inode = info.st_ino

    def sha256(self) -> str:
        """The sha256 of the bytes, read from the start of the descriptor."""
        return _guard(lambda: sha256_descriptor(self._descriptor), self._location)

    def set_mode(self, mode: int) -> None:
        """Give the file exactly ``mode`` through the descriptor."""
        _guard(lambda: os.fchmod(self._descriptor, mode), self._location)

    def close(self) -> None:
        """Release the descriptor."""
        os.close(self._descriptor)


class _Missing(StorageError):
    """A name of a lake path does not exist; a read answers ``None`` for it."""

    def __init__(self, location: LakePath) -> None:
        super().__init__(f"{location} does not exist", {"path": str(location)})


def _require_file(descriptor: int, location: LakePath) -> None:
    """Refuse a descriptor that is not of a regular file, as the in-memory lake refuses it."""
    mode = _guard(lambda: os.fstat(descriptor), location).st_mode
    if not stat.S_ISREG(mode):
        raise _not_a_file(location, errno.EISDIR if stat.S_ISDIR(mode) else errno.EINVAL)


def _blocked(location: LakePath, error: posix.PartBlocked) -> StorageError:
    """The error of a directory at a part or backup file beside ``location``; it names the file."""
    return _storage_error(location.parent.joinpath(f"{error.filename}"), error)


def _not_a_file(location: LakePath, number: int) -> StorageError:
    return StorageError(f"{location}: {os.strerror(number)}", {"path": str(location)})


def _read_all(descriptor: int) -> bytes:
    blocks: list[bytes] = []
    while block := os.read(descriptor, CHUNK_SIZE):
        blocks.append(block)
    return b"".join(blocks)


def _name(location: LakePath) -> str:
    """The last name of ``location``; the root is ``.`` in its own descriptor."""
    return location.name or "."


def _kind(mode: int) -> StatKind:
    if stat.S_ISDIR(mode):
        return "dir"
    return "file" if stat.S_ISREG(mode) else "other"


def _guard[T](action: Callable[[], T], location: LakePath) -> T:
    try:
        return action()
    except OSError as error:
        raise _storage_error(location, error) from error


def _storage_error(location: LakePath, error: OSError) -> StorageError:
    if isinstance(error, FileNotFoundError):
        return _Missing(location)
    if isinstance(error, PermissionError):
        return StorageError(
            f"permission denied on {location}", {"path": str(location), "error": error.strerror}
        )
    return StorageError(f"{location}: {error.strerror}", {"path": str(location)})
