"""The share as a POSIX filesystem, with POSIX ACLs applied through ``setfacl``."""

from __future__ import annotations

import grp
import hashlib
import os
import stat
from typing import TYPE_CHECKING, Literal

from huron.core.storage.aclplan import AclPlan, diff
from huron.core.storage.errors import SourceGone, StorageError
from huron.core.storage.ports import FileStamp, GroupOutcome, GroupResult, Ownership
from huron.pkg.fs import posix
from huron.pkg.fs.acl import Acl, AclEntry, Runner, read_acl, write_acl
from huron.pkg.hashing import CHUNK_SIZE, sha256_file
from huron.schema.naming import PART_SUFFIX

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from huron.pkg.fs.posix import Entry, Stamp

__all__ = ["PosixStorage"]


class PosixStorage:
    """Storage over the mounted share. With ``acl_backend="none"`` only modes are applied."""

    def __init__(self, acl_backend: Literal["posix", "none"], runner: Runner) -> None:
        self._acls = acl_backend == "posix"
        self._runner = runner

    def make_directory(self, path: Path, mode: int) -> bool:
        """Create ``path`` with exactly ``mode``; an existing directory is left as it is."""
        if not posix.is_dir(path.parent):
            raise StorageError(f"{path.parent} does not exist", {"path": str(path.parent)})
        try:
            os.mkdir(path, mode)
        except FileExistsError:
            if posix.is_dir(path):
                return False
            raise StorageError(f"{path} is not a directory", {"path": str(path)}) from None
        except OSError as error:
            raise _storage_error(path, error) from error
        # mkdir applies the umask and never sets the setgid bit.
        _guard(lambda: os.chmod(path, mode), path)
        return True

    def set_mode(self, path: Path, mode: int) -> bool:
        """Give ``path`` exactly ``mode``."""
        if self.owner(path).mode == mode:
            return False
        _guard(lambda: os.chmod(path, mode), path)
        return True

    def set_group(self, path: Path, group: str | int) -> GroupResult:
        """Give ``path`` the group ``group``, a name or a gid.

        An unknown name or a refusal is ``PENDING``.
        """
        try:
            gid = group if isinstance(group, int) else grp.getgrnam(group).gr_gid
        except KeyError:
            return GroupResult.unknown(f"{group}")
        try:
            if os.lstat(path).st_gid == gid:
                return GroupResult(GroupOutcome.UNCHANGED)
            os.chown(path, -1, gid, follow_symlinks=False)
        except OSError as error:
            return GroupResult(GroupOutcome.PENDING, f"{path}: {error.strerror or error}")
        return GroupResult(GroupOutcome.CHANGED)

    def owner(self, path: Path) -> Ownership:
        """The owner, the group and the mode bits of ``path``."""
        info = _guard(lambda: os.lstat(path), path)
        return Ownership(info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode))

    def device(self, path: Path) -> int:
        """The filesystem of ``path``, following links."""
        return _guard(lambda: os.stat(path).st_dev, path)

    def ensure_directory(self, path: Path, plan: AclPlan) -> bool:
        """Create ``path`` with the plan's mode and ACL; an existing one is brought in line."""
        if not posix.is_dir(path.parent):
            raise StorageError(f"{path.parent} does not exist", {"path": str(path.parent)})
        created = _guard(lambda: posix.make_dir(path, plan.mode), path)
        self.apply_plan(path, plan)
        return created

    def apply_plan(self, path: Path, plan: AclPlan) -> bool:
        """Apply group, mode and ACL; returns whether anything changed."""
        group = plan.owning_group
        changed = group is not None and self.set_group(path, group).outcome is GroupOutcome.CHANGED
        if stat.S_IMODE(os.lstat(path).st_mode) != plan.mode:
            _guard(lambda: os.chmod(path, plan.mode), path)
            changed = True
        if self._acls and diff(plan, self.read_acl(path)):
            write_acl(path, plan.acl, self._runner)
            changed = True
        return changed

    def read_acl(self, path: Path) -> Acl:
        """The ACL of ``path``; without ACL support, the mode bits as base entries."""
        if self._acls:
            return read_acl(path, self._runner)
        mode = stat.S_IMODE(os.lstat(path).st_mode)
        return Acl(
            frozenset(
                {
                    AclEntry("user", None, _perms(mode >> 6)),
                    AclEntry("group", None, _perms(mode >> 3)),
                    AclEntry("other", None, _perms(mode)),
                }
            )
        )

    def write_bytes(self, path: Path, data: bytes, mode: int | None = None) -> None:
        """Write ``data`` atomically; with ``mode``, the file gets exactly that mode."""
        _guard(lambda: posix.atomic_write(path, data, PART_SUFFIX), path)
        if mode is not None:
            _guard(lambda: os.chmod(path, mode), path)

    def make_inheriting_dir(self, path: Path) -> bool:
        """Create ``path`` with mode ``0750``; it must inherit setgid and group from its parent."""
        return _guard(lambda: posix.make_inheriting_dir(path), path)

    def open_file(self, path: Path) -> _PosixFile | None:
        """Open a file read-only without following a final link; ``None`` when it is absent.

        Opening makes an NFS client read the file's attributes again, so the descriptor's size
        and inode are the server's.
        """
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return None
        except OSError as error:
            raise _storage_error(path, error) from error
        try:
            return _PosixFile(path, descriptor)
        except BaseException:
            os.close(descriptor)
            raise

    def link(
        self, source: Path, destination: Path, part_name: str, backup_name: str
    ) -> Path | None:
        """Hard-link ``source`` to ``destination``; the replaced file stays as ``backup_name``."""
        try:
            return posix.link_into_place(source, destination, part_name, backup_name)
        except FileNotFoundError as error:
            if not os.path.lexists(source):
                raise SourceGone(source) from error
            raise _storage_error(destination, error) from error
        except OSError as error:
            raise _storage_error(destination, error) from error

    def rename(self, source: Path, destination: Path) -> None:
        """Give the file at ``source`` the name ``destination``, replacing it atomically."""
        _guard(lambda: os.rename(source, destination), destination)

    def inode(self, path: Path) -> int | None:
        """The inode number of ``path``; ``None`` when it does not exist."""
        try:
            return posix.inode(path)
        except FileNotFoundError:
            return None
        except OSError as error:
            raise _storage_error(path, error) from error

    def read_bytes(self, path: Path) -> bytes | None:
        """The bytes of a file, or ``None``."""
        try:
            return path.read_bytes()
        except FileNotFoundError:
            return None

    def remove_file(self, path: Path) -> bool:
        """Remove a file."""
        return _guard(lambda: posix.remove_file(path), path)

    def remove_directory(self, path: Path) -> bool:
        """Remove an empty directory."""
        return _guard(lambda: posix.remove_empty_dir(path), path)

    def exists(self, path: Path) -> bool:
        """Whether ``path`` exists (without following a final link)."""
        return os.path.lexists(path)

    def is_directory(self, path: Path) -> bool:
        """Whether ``path`` is a real directory."""
        return posix.is_dir(path)

    def walk(self, path: Path) -> Iterator[Entry]:
        """Every entry under ``path``."""
        return posix.walk(path)

    def stamp(self, path: Path) -> Stamp:
        """Size and modification time."""
        return posix.stat(path)

    def hash(self, path: Path) -> FileStamp:
        """Size and sha256."""
        size, digest = _guard(lambda: sha256_file(path), path)
        return FileStamp(size, digest)

    def owned_by_me(self, path: Path) -> bool:
        """Whether the current user owns ``path``."""
        return os.lstat(path).st_uid == os.getuid()


class _PosixFile:
    """A read-only descriptor of a file on the share."""

    def __init__(self, path: Path, descriptor: int) -> None:
        self._path = path
        self._descriptor = descriptor
        info = _guard(lambda: os.fstat(descriptor), path)
        self.size = info.st_size
        self.inode = info.st_ino

    def sha256(self) -> str:
        """The sha256 of the bytes, read from the start of the descriptor."""
        return _guard(self._digest, self._path)

    def set_mode(self, mode: int) -> None:
        """Give the file exactly ``mode`` through the descriptor."""
        _guard(lambda: os.fchmod(self._descriptor, mode), self._path)

    def close(self) -> None:
        """Release the descriptor."""
        os.close(self._descriptor)

    def _digest(self) -> str:
        digest = hashlib.sha256()
        offset = 0
        while block := os.pread(self._descriptor, CHUNK_SIZE, offset):
            digest.update(block)
            offset += len(block)
        return digest.hexdigest()


def _guard[T](action: Callable[[], T], path: Path) -> T:
    try:
        return action()
    except OSError as error:
        raise _storage_error(path, error) from error


def _storage_error(path: Path, error: OSError) -> StorageError:
    if isinstance(error, PermissionError):
        context = {"path": str(path), "error": str(error)}
        return StorageError(f"permission denied on {path}", context)
    return StorageError(f"{path}: {error.strerror or error}", {"path": str(path)})


def _perms(bits: int) -> str:
    return "".join(flag if bits & mask else "-" for flag, mask in (("r", 4), ("w", 2), ("x", 1)))
