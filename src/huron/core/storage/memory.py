"""An in-memory share for tests: directories, files, modes, groups, ACLs, owners and mounts."""

from __future__ import annotations

import errno
import hashlib
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from huron.core.storage.errors import StorageError
from huron.core.storage.ports import FileStamp, GroupOutcome, GroupResult, Ownership
from huron.pkg.fs.acl import Acl
from huron.pkg.fs.posix import Entry, Stamp

if TYPE_CHECKING:
    from collections.abc import Iterator

    from huron.core.storage.aclplan import AclPlan

__all__ = ["ROOT_DEVICE", "MemoryStorage", "Node"]


#: The filesystem every entry is on unless a mount point above it says otherwise.
ROOT_DEVICE = 1


@dataclass
class Node:
    """A directory (``data is None``) or a file.

    ``owner`` and ``group`` are names for the ACL plans; ``uid`` and ``gid`` are the numbers
    :meth:`MemoryStorage.owner` reports.
    """

    owner: str
    mode: int = 0o2770
    uid: int = 0
    gid: int = 0
    acl: Acl = field(default_factory=Acl)
    group: str | None = None
    data: bytes | None = None
    mtime_ns: int = 0

    @property
    def is_dir(self) -> bool:
        """Whether the node is a directory."""
        return self.data is None


class MemoryStorage:
    """A :class:`Storage` over a dictionary.

    The caller is ``user``, with the numbers ``uid`` and ``gid``. ``groups`` is the machine's
    group database (name to gid), and ``member_of`` the gids the caller may give an entry it
    owns. A directory in ``denied`` refuses every change to its entries. ``mounts`` maps mount
    points to the filesystem below them.
    """

    def __init__(self, root: Path, user: str = "me", uid: int = 1000, gid: int = 1000) -> None:
        self.user = user
        self.uid = uid
        self.gid = gid
        self.groups: dict[str, int] = {}
        self.member_of: set[int] = {gid}
        self.nodes: dict[Path, Node] = {root: Node(owner="root", mode=0o2771)}
        self.denied: set[Path] = set()
        self.mounts: dict[Path, int] = {}
        self.calls: list[tuple[str, Path]] = []
        self._clock = 0

    def add_root(self, path: Path, owner: str = "root") -> None:
        """Add a directory owned by ``owner`` (and any missing parents), like a mounted root."""
        for directory in (*reversed(path.parents), path):
            self.nodes.setdefault(directory, Node(owner=owner, mode=0o755))

    def mount(self, path: Path, device: int) -> None:
        """Make ``path`` (and any missing parents) the mount point of filesystem ``device``."""
        self.add_root(path)
        self.mounts[path] = device

    def make_directory(self, path: Path, mode: int) -> bool:
        """Create ``path`` with ``mode``; its group comes from a setgid parent, as on the server."""
        parent = self.nodes.get(path.parent)
        if parent is None or not parent.is_dir:
            raise StorageError(f"{path.parent} does not exist", {"path": str(path.parent)})
        existing = self.nodes.get(path)
        if existing is not None:
            if existing.is_dir:
                return False
            raise StorageError(f"{path} is not a directory", {"path": str(path)})
        self._check(path.parent)
        gid = self._new_gid(path.parent)
        self.nodes[path] = Node(owner=self.user, uid=self.uid, gid=gid)
        self.nodes[path].mode = self._settable(mode, gid)
        self.calls.append(("mkdir", path))
        return True

    def set_mode(self, path: Path, mode: int) -> bool:
        """Give ``path`` ``mode``; like ``chmod``, it drops setgid outside the caller's groups."""
        node = self._node(path)
        if node.mode == mode:
            return False
        if node.uid != self.uid:
            raise StorageError(f"permission denied on {path}", {"path": str(path)})
        node.mode = self._settable(mode, node.gid)
        self.calls.append(("chmod", path))
        return True

    def set_group(self, path: Path, group: str | int) -> GroupResult:
        """Give ``path`` the group ``group``, a name or a gid.

        Only an owner who is a member of the group may.
        """
        gid = group if isinstance(group, int) else self.groups.get(group)
        if gid is None:
            return GroupResult.unknown(f"{group}")
        node = self.nodes.get(path)
        if node is None:
            return GroupResult(GroupOutcome.PENDING, f"{path}: {os.strerror(errno.ENOENT)}")
        if node.gid == gid:
            return GroupResult(GroupOutcome.UNCHANGED)
        if node.uid != self.uid or gid not in self.member_of:
            return GroupResult(GroupOutcome.PENDING, f"{path}: {os.strerror(errno.EPERM)}")
        names = {number: name for name, number in self.groups.items()}
        node.gid, node.group = gid, names.get(gid)
        self.calls.append(("chgrp", path))
        return GroupResult(GroupOutcome.CHANGED)

    def owner(self, path: Path) -> Ownership:
        """The owner, the group and the mode of ``path``."""
        node = self._node(path)
        return Ownership(node.uid, node.gid, node.mode)

    def device(self, path: Path) -> int:
        """The filesystem of the nearest mount point at or above ``path``."""
        self._node(path)
        for candidate in (path, *path.parents):
            if candidate in self.mounts:
                return self.mounts[candidate]
        return ROOT_DEVICE

    def ensure_directory(self, path: Path, plan: AclPlan) -> bool:
        """Create ``path`` (its parent must exist) and apply ``plan``."""
        if not self.is_directory(path.parent):
            raise StorageError(f"{path.parent} does not exist", {"path": str(path.parent)})
        created = path not in self.nodes
        if created:
            self._check(path.parent)
            self.nodes[path] = Node(owner=self.user, uid=self.uid, gid=self.gid)
            self.calls.append(("mkdir", path))
        elif not self.nodes[path].is_dir:
            raise StorageError(f"{path} is not a directory", {"path": str(path)})
        self.apply_plan(path, plan)
        return created

    def apply_plan(self, path: Path, plan: AclPlan) -> bool:
        """Apply mode, group and ACL; only the owner may."""
        node = self._node(path)
        wanted = (plan.mode, plan.acl, plan.owning_group or node.group)
        if (node.mode, node.acl, node.group) == wanted:
            return False
        if node.owner != self.user:
            raise StorageError(f"only the owner can change {path}", {"path": str(path)})
        node.mode, node.acl, node.group = wanted
        self.calls.append(("acl", path))
        return True

    def read_acl(self, path: Path) -> Acl:
        """The recorded ACL."""
        return self._node(path).acl

    def copy_in(
        self, source: Path, directory: Path, rel_path: str, expected: FileStamp | None = None
    ) -> FileStamp:
        """Copy a real local file into the in-memory share."""
        destination = directory.joinpath(*PurePosixPath(rel_path).parts)
        current = destination.parent
        missing = []
        while current not in self.nodes:
            missing.append(current)
            current = current.parent
        for parent in reversed(missing):
            self._check(parent.parent)
            self.nodes[parent] = Node(owner=self.user, uid=self.uid, gid=self.gid)
        if (
            expected is not None
            and destination in self.nodes
            and self.hash(destination) == expected
        ):
            return expected
        try:
            data = source.read_bytes()
        except OSError as error:
            raise StorageError(f"cannot read {source}", {"path": str(source)}) from error
        self.write_bytes(destination, data)
        self.calls.append(("copy", destination))
        return FileStamp(len(data), hashlib.sha256(data).hexdigest())

    def write_bytes(self, path: Path, data: bytes, mode: int | None = None) -> None:
        """Store ``data`` at ``path`` (mode ``0660`` unless ``mode`` is given).

        The write replaces the file, so the file takes its group from a setgid parent, as a new
        file does on the server.
        """
        self._check(path.parent)
        self._clock += 1
        self.nodes[path] = Node(
            owner=self.user,
            mode=0o660 if mode is None else mode,
            uid=self.uid,
            gid=self._new_gid(path.parent),
            data=data,
            mtime_ns=self._clock,
        )

    def read_bytes(self, path: Path) -> bytes | None:
        """The bytes at ``path``."""
        node = self.nodes.get(path)
        return None if node is None else node.data

    def remove_file(self, path: Path) -> bool:
        """Remove a file."""
        if path not in self.nodes:
            return False
        self._check(path.parent)
        del self.nodes[path]
        self.calls.append(("unlink", path))
        return True

    def remove_directory(self, path: Path) -> bool:
        """Remove an empty directory."""
        if path not in self.nodes:
            return False
        if any(other.parent == path for other in self.nodes):
            raise StorageError(f"{path} is not empty", {"path": str(path)})
        self._check(path.parent)
        del self.nodes[path]
        self.calls.append(("rmdir", path))
        return True

    def exists(self, path: Path) -> bool:
        """Whether ``path`` exists."""
        return path in self.nodes

    def is_directory(self, path: Path) -> bool:
        """Whether ``path`` is a directory."""
        node = self.nodes.get(path)
        return node is not None and node.is_dir

    def walk(self, path: Path) -> Iterator[Entry]:
        """Every entry under ``path``, sorted by relative path."""
        below = sorted(p for p in self.nodes if path in p.parents)
        for found in below:
            node = self.nodes[found]
            size = 0 if node.data is None else len(node.data)
            rel_path = found.relative_to(path).as_posix()
            if node.is_dir:
                yield Entry(rel_path, "dir", size, node.mtime_ns, False)
            else:
                yield Entry(rel_path, "file", size, node.mtime_ns, False)

    def stamp(self, path: Path) -> Stamp:
        """Size and modification counter."""
        node = self._node(path)
        return Stamp(len(node.data or b""), node.mtime_ns)

    def hash(self, path: Path) -> FileStamp:
        """Size and sha256."""
        data = self._node(path).data or b""
        return FileStamp(len(data), hashlib.sha256(data).hexdigest())

    def owned_by_me(self, path: Path) -> bool:
        """Whether ``user`` owns ``path``."""
        return self._node(path).owner == self.user

    def _node(self, path: Path) -> Node:
        node = self.nodes.get(path)
        if node is None:
            raise StorageError(f"{path} does not exist", {"path": str(path)})
        return node

    def _check(self, directory: Path) -> None:
        if directory in self.denied:
            raise StorageError(f"permission denied on {directory}", {"path": str(directory)})

    def _new_gid(self, directory: Path) -> int:
        parent = self.nodes.get(directory)
        if parent is not None and parent.is_dir and parent.mode & stat.S_ISGID:
            return parent.gid
        return self.gid

    def _settable(self, mode: int, gid: int) -> int:
        return mode if gid in self.member_of else mode & ~stat.S_ISGID
