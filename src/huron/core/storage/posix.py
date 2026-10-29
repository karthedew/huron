"""The share as a POSIX filesystem, with POSIX ACLs applied through ``setfacl``."""

from __future__ import annotations

import grp
import os
import stat
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Literal

from huron.core.storage.aclplan import AclPlan, diff
from huron.core.storage.errors import StorageError
from huron.core.storage.ports import FileStamp
from huron.pkg.fs import posix
from huron.pkg.fs.acl import Acl, AclEntry, Runner, read_acl, write_acl
from huron.pkg.hashing import sha256_file

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from huron.pkg.fs.posix import Entry, Stamp

__all__ = ["DIRECTORY_MODE", "PosixStorage"]

DIRECTORY_MODE = 0o2770


class PosixStorage:
    """Storage over the mounted share. With ``acl_backend="none"`` only modes are applied."""

    def __init__(self, acl_backend: Literal["posix", "none"], runner: Runner) -> None:
        self._acls = acl_backend == "posix"
        self._runner = runner

    def ensure_directory(self, path: Path, plan: AclPlan) -> bool:
        """Create ``path`` with the plan's mode and ACL; an existing one is brought in line."""
        if not posix.is_dir(path.parent):
            raise StorageError(f"{path.parent} does not exist", {"path": str(path.parent)})
        created = _guard(lambda: posix.make_dir(path, plan.mode), path)
        self.apply_plan(path, plan)
        return created

    def apply_plan(self, path: Path, plan: AclPlan) -> bool:
        """Apply group, mode and ACL; returns whether anything changed."""
        changed = self._chgrp(path, plan.owning_group)
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

    def copy_in(
        self, source: Path, directory: Path, rel_path: str, expected: FileStamp | None = None
    ) -> FileStamp:
        """Copy ``source`` into the collection through a part file; skip a matching copy."""
        destination = directory.joinpath(*PurePosixPath(rel_path).parts)
        for parent in reversed(destination.relative_to(directory).parents[:-1]):
            _make_dir(directory / parent)
        if expected is not None and destination.exists() and self.hash(destination) == expected:
            return expected
        size, digest = _guard(lambda: posix.atomic_copy(source, destination), destination)
        return FileStamp(size, digest)

    def write_bytes(self, path: Path, data: bytes) -> None:
        """Write ``data`` atomically."""
        _guard(lambda: posix.atomic_write(path, data), path)

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

    def _chgrp(self, path: Path, group: str | None) -> bool:
        if group is None:
            return False
        try:
            gid = grp.getgrnam(group).gr_gid
        except KeyError:
            return False
        if os.lstat(path).st_gid == gid:
            return False
        try:
            os.chown(path, -1, gid)
        except PermissionError:
            return False
        return True


def _guard[T](action: Callable[[], T], path: Path) -> T:
    try:
        return action()
    except PermissionError as error:
        raise StorageError(
            f"permission denied on {path}", {"path": str(path), "error": str(error)}
        ) from error
    except OSError as error:
        raise StorageError(f"{path}: {error.strerror or error}", {"path": str(path)}) from error


def _make_dir(path: Path) -> None:
    if not posix.is_dir(path):
        _guard(lambda: posix.make_dir(path, DIRECTORY_MODE), path)


def _perms(bits: int) -> str:
    return "".join(flag if bits & mask else "-" for flag, mask in (("r", 4), ("w", 2), ("x", 1)))
