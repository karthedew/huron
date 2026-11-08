"""An in-memory lake for tests: directories, files, symbolic links, modes, groups and owners."""

from __future__ import annotations

import errno
import hashlib
import itertools
import os
import stat
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from huron.core.storage.errors import SourceGone, StorageError, SymlinkInLake
from huron.core.storage.lakepath import LakePath
from huron.core.storage.ports import Entry, GroupOutcome, GroupResult, Outcome, Stat
from huron.pkg.fs.posix import INHERITING_DIR_MODE

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from huron.core.storage.ports import StatKind

__all__ = ["MemoryStorage", "Node", "NodeKind"]

type NodeKind = Literal["dir", "file", "symlink"]


@dataclass
class Node:
    """A directory, a file or a symbolic link (to ``target``).

    ``uid`` and ``gid`` are the owner and the group. Hard links of a file share one node, so
    they share its ``inode`` and its mode.
    """

    kind: NodeKind = "dir"
    mode: int = 0o2770
    uid: int = 0
    gid: int = 0
    data: bytes = b""
    mtime_ns: int = 0
    inode: int = 0
    target: str = ""


class MemoryStorage:
    """A :class:`Storage` over a dictionary of nodes keyed by :class:`LakePath`.

    ``root`` is the directory the root node stands for. The caller has the numbers ``uid`` and
    ``gid``. ``groups`` is the machine's group database (name to gid), and ``member_of`` the
    gids the caller may give an entry it owns. A directory in ``denied`` refuses every change
    to its entries, and a directory in ``unreadable`` cannot be searched or listed.
    ``inherits`` is whether a new directory inherits the setgid bit and the group of a setgid
    parent, as the server should. Each traversal refuses a symbolic link as the POSIX one does.
    """

    def __init__(self, root: Path, uid: int = 1000, gid: int = 1000) -> None:
        self.root = root
        self.uid = uid
        self.gid = gid
        self.groups: dict[str, int] = {}
        self.member_of: set[int] = {gid}
        self.nodes: dict[LakePath, Node] = {LakePath(): Node(mode=0o2771, inode=1)}
        self.denied: set[LakePath] = set()
        self.unreadable: set[LakePath] = set()
        self.inherits = True
        self.calls: list[tuple[str, LakePath]] = []
        self._clock = 0
        self._inodes = itertools.count(2)

    def add_directory(self, location: LakePath, uid: int = 0) -> None:
        """Add a directory owned by ``uid``, and any missing parents, like a declared root."""
        for size in range(1, len(location.names) + 1):
            self.nodes.setdefault(
                LakePath(location.names[:size]), Node(mode=0o755, uid=uid, inode=next(self._inodes))
            )

    def symlink(self, location: LakePath, target: str) -> None:
        """Plant a symbolic link to ``target``; for tests only, Huron makes no link."""
        self._require_parent(location)
        self.nodes[location] = Node("symlink", 0o777, self.uid, self.gid, target=target)

    def stat(self, location: LakePath) -> Stat | None:
        """The node at ``location``; ``None`` when it does not exist."""
        node = self._lookup(location)
        if node is None:
            return None
        kind: StatKind = "dir" if node.kind == "dir" else "file"
        return Stat(kind, node.mode, node.gid, node.inode, len(node.data))

    def read_bytes(self, location: LakePath) -> bytes | None:
        """The bytes of the file at ``location``, or ``None``."""
        node = self._lookup(location)
        if node is None:
            return None
        if node.kind == "dir":
            raise _error(location, errno.EISDIR)
        return node.data

    def is_empty(self, location: LakePath) -> bool:
        """Whether the directory has no entry; a link counts as an entry."""
        self._directory(location)
        return not any(self._children(location))

    def walk(self, location: LakePath) -> Iterator[Entry]:
        """Every entry below the directory, top-down and sorted by name; links are not entered."""
        self._directory(location)
        yield from self._walk(location, ())

    def open_file(self, location: LakePath) -> _MemoryFile | None:
        """The file at ``location`` opened read-only, or ``None``."""
        node = self._lookup(location)
        if node is None:
            return None
        if node.kind == "dir":
            raise _error(location, errno.EISDIR)
        return _MemoryFile(self, location, node)

    def make_directory(self, location: LakePath, mode: int) -> bool:
        """Create a directory with ``mode``; its group comes from a setgid parent."""
        if not self._new_directory(location):
            return False
        gid = self._new_gid(location.parent)
        node = Node(uid=self.uid, gid=gid, inode=next(self._inodes))
        node.mode = self._settable(mode, gid)
        self.nodes[location] = node
        self.calls.append(("mkdir", location))
        return True

    def make_inheriting_dir(self, location: LakePath) -> bool:
        """Create a directory with mode ``0750``; setgid and the group come only from the parent.

        With :attr:`inherits` off, a setgid parent passes neither on, and the new directory is
        refused.
        """
        if not self._new_directory(location):
            return False
        parent = self.nodes[location.parent]
        if not (self.inherits and parent.mode & stat.S_ISGID):
            raise StorageError(
                f"{location}: the directory did not inherit the setgid bit and the group"
                f" {parent.gid}",
                {"path": str(location)},
            )
        self.nodes[location] = Node(
            mode=INHERITING_DIR_MODE | stat.S_ISGID,
            uid=self.uid,
            gid=parent.gid,
            inode=next(self._inodes),
        )
        self.calls.append(("mkdir", location))
        return True

    def set_mode(self, location: LakePath, mode: int) -> bool:
        """Give the entry ``mode``; like ``chmod``, it drops setgid outside the caller's groups."""
        node = self._lookup(location)
        if node is None:
            raise _error(location, errno.ENOENT)
        if node.mode == mode:
            return False
        if node.uid != self.uid:
            raise _error(location, errno.EPERM)
        node.mode = self._settable(mode, node.gid)
        self.calls.append(("chmod", location))
        return True

    def set_group(self, location: LakePath, group: str | int) -> GroupResult:
        """Give the entry the group ``group``; only an owner who is a member of the group may."""
        gid = group if isinstance(group, int) else self.groups.get(group)
        if gid is None:
            return GroupResult.unknown(f"{group}")
        node = self._lookup(location)
        if node is None:
            return GroupResult(GroupOutcome.PENDING, f"{location} does not exist")
        if node.gid == gid:
            return GroupResult(GroupOutcome.UNCHANGED)
        if node.uid != self.uid or gid not in self.member_of:
            return GroupResult(GroupOutcome.PENDING, f"{location}: {os.strerror(errno.EPERM)}")
        node.gid = gid
        self.calls.append(("chgrp", location))
        return GroupResult(GroupOutcome.CHANGED)

    def write_bytes(self, location: LakePath, data: bytes, mode: int) -> None:
        """Store ``data`` with ``mode``; the new file takes its group from a setgid parent."""
        self._require_parent(location)
        existing = self._final(location)
        if existing is not None and existing.kind == "dir":
            raise _error(location, errno.EISDIR)
        self._check(location.parent)
        self._clock += 1
        self.nodes[location] = Node(
            "file",
            mode,
            self.uid,
            self._new_gid(location.parent),
            data,
            self._clock,
            next(self._inodes),
        )
        self.calls.append(("write", location))

    def link(
        self,
        source: LakePath,
        destination: LakePath,
        *,
        inode: int,
        part_name: str,
        backup_name: str,
    ) -> LakePath | None:
        """Give the file at ``source`` the name ``destination`` too, and return the backup.

        ``source`` must be a file with the inode ``inode``, else ``SourceGone``. An existing
        ``destination`` keeps its node under ``backup_name`` and is replaced through
        ``part_name``, as on the server. A ``destination`` that already is the source's node
        stays, with the backup an earlier attempt left.
        """
        found = self.nodes.get(source) if self._parent(source) is not None else None
        if found is None or found.kind != "file" or found.inode != inode:
            raise SourceGone(source)
        self._require_parent(destination)
        existing = self._final(destination)
        part, backup = (
            destination.parent.joinpath(part_name),
            destination.parent.joinpath(backup_name),
        )
        if existing is found:
            return backup if self._final(backup) is not None else None
        self._check(destination.parent)
        if existing is None:
            self.nodes[destination] = found
            self.calls.append(("link", destination))
            return None
        self._final(part)
        self._final(backup)
        self.nodes.pop(part, None)
        self.nodes[backup] = existing
        self.nodes[destination] = found
        self.calls += [("link", part), ("link", backup), ("rename", destination)]
        return backup

    def rename(self, source: LakePath, destination: LakePath) -> None:
        """Give the node at ``source`` the name ``destination``."""
        if self._lookup(source) is None:
            raise _error(source, errno.ENOENT)
        self._require_parent(destination)
        self._final(destination)
        self._check(destination.parent)
        self.nodes[destination] = self.nodes.pop(source)
        self.calls.append(("rename", destination))

    def remove_file(self, location: LakePath, *, inode: int | None = None) -> Outcome:
        """Remove a file; with ``inode``, only while the file has that inode."""
        node = self._lookup(location)
        if node is None:
            return Outcome.MISSING
        if inode is not None and node.inode != inode:
            return Outcome.KEPT
        if node.kind == "dir":
            raise _error(location, errno.EISDIR)
        self._check(location.parent)
        del self.nodes[location]
        self.calls.append(("unlink", location))
        return Outcome.REMOVED

    def remove_directory(self, location: LakePath) -> Outcome:
        """Remove an empty directory; ``KEPT`` when it has entries."""
        node = self._lookup(location)
        if node is None:
            return Outcome.MISSING
        if node.kind != "dir":
            raise _error(location, errno.ENOTDIR)
        if any(self._children(location)):
            return Outcome.KEPT
        self._check(location.parent)
        del self.nodes[location]
        self.calls.append(("rmdir", location))
        return Outcome.REMOVED

    def _parent(self, location: LakePath) -> Node | None:
        """The directory that holds ``location``, opened as the POSIX traversal opens it.

        ``None`` when a name on the way does not exist. A link on the way is
        ``SymlinkInLake``, a file on the way ``ENOTDIR`` and an unreadable directory ``EACCES``.
        """
        current = LakePath()
        node = self.nodes[current]
        for name in location.parent.names:
            self._search(current)
            current = current.joinpath(name)
            found = self.nodes.get(current)
            if found is None:
                return None
            if found.kind == "symlink":
                raise SymlinkInLake(current)
            if found.kind != "dir":
                raise _error(location, errno.ENOTDIR)
            node = found
        self._search(current)
        return node

    def _require_parent(self, location: LakePath) -> Node:
        parent = self._parent(location)
        if parent is None:
            raise _error(location.parent, errno.ENOENT)
        return parent

    def _final(self, location: LakePath) -> Node | None:
        node = self.nodes.get(location)
        if node is not None and node.kind == "symlink":
            raise SymlinkInLake(location)
        return node

    def _lookup(self, location: LakePath) -> Node | None:
        return None if self._parent(location) is None else self._final(location)

    def _directory(self, location: LakePath) -> None:
        node = self._lookup(location)
        if node is None:
            raise _error(location, errno.ENOENT)
        if node.kind != "dir":
            raise _error(location, errno.ENOTDIR)
        self._search(location)

    def _new_directory(self, location: LakePath) -> bool:
        """Whether ``location`` is free for a new directory; ``False`` for an existing one."""
        self._require_parent(location)
        existing = self._final(location)
        if existing is not None:
            if existing.kind == "dir":
                return False
            raise _error(location, errno.EEXIST)
        self._check(location.parent)
        return True

    def _children(self, location: LakePath) -> Iterator[LakePath]:
        return (p for p in self.nodes if p.parent == location and p != location)

    def _walk(self, location: LakePath, prefix: tuple[str, ...]) -> Iterator[Entry]:
        for child in sorted(self._children(location), key=lambda p: p.name):
            node, names = self.nodes[child], (*prefix, child.name)
            yield Entry(names, node.kind, len(node.data), node.mtime_ns)
            if node.kind == "dir":
                self._search(child)
                yield from self._walk(child, names)

    def _search(self, directory: LakePath) -> None:
        if directory in self.unreadable:
            raise _error(directory, errno.EACCES)

    def _check(self, directory: LakePath) -> None:
        if directory in self.denied:
            raise _error(directory, errno.EACCES)

    def _new_gid(self, directory: LakePath) -> int:
        parent = self.nodes.get(directory)
        if parent is not None and parent.kind == "dir" and parent.mode & stat.S_ISGID:
            return parent.gid
        return self.gid

    def _settable(self, mode: int, gid: int) -> int:
        return mode if gid in self.member_of else mode & ~stat.S_ISGID


class _MemoryFile:
    """A file of a :class:`MemoryStorage` opened read-only."""

    def __init__(self, storage: MemoryStorage, location: LakePath, node: Node) -> None:
        self._storage = storage
        self._location = location
        self._node = node
        self.size = len(node.data)
        self.inode = node.inode

    def sha256(self) -> str:
        """The sha256 of the file's bytes."""
        return hashlib.sha256(self._node.data).hexdigest()

    def set_mode(self, mode: int) -> None:
        """Give the file ``mode``; only its owner may."""
        if self._node.uid != self._storage.uid:
            raise _error(self._location, errno.EPERM)
        self._node.mode = mode
        self._storage.calls.append(("chmod", self._location))

    def close(self) -> None:
        """Nothing to release."""


def _error(location: LakePath, number: int) -> StorageError:
    """The error the POSIX adapter maps ``number`` at ``location`` to."""
    if number in {errno.EACCES, errno.EPERM}:
        context = {"path": str(location), "error": os.strerror(number)}
        return StorageError(f"permission denied on {location}", context)
    if number == errno.ENOENT:
        return StorageError(f"{location} does not exist", {"path": str(location)})
    return StorageError(f"{location}: {os.strerror(number)}", {"path": str(location)})
