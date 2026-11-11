"""An in-memory lake for tests: directories, files, symbolic links, modes, groups and owners."""

from __future__ import annotations

import errno
import hashlib
import itertools
import os
import stat
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from huron.core.storage.errors import (
    InheritanceFailed,
    SourceGone,
    SourceSizeMismatch,
    StorageError,
    SymlinkInLake,
)
from huron.core.storage.lakepath import LakePath
from huron.core.storage.layout import FILE_MODE
from huron.core.storage.ports import (
    Entry,
    FreeSpace,
    GroupOutcome,
    GroupResult,
    Outcome,
    SealedFile,
    Stat,
)
from huron.pkg.fs.posix import INHERITED_MODE, INHERITING_DIR_MODE
from huron.schema.naming import PART_SUFFIX

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from huron.core.storage.ports import StatKind

__all__ = ["FREE_BYTES", "MemoryStorage", "Node", "NodeKind"]

#: The free bytes of a filesystem of a :class:`MemoryStorage` that its ``free`` does not name.
FREE_BYTES = 2**40

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
    parent, as the server should, and ``umask`` takes bits from the mode of a new directory
    that gets no ``chmod``, as the process umask does. Each traversal refuses a symbolic link as
    the POSIX one does.

    Each directory in ``mounts`` is the root of its own filesystem, and the root directory is
    the first one. ``link_once`` and ``rename`` refuse two names on two filesystems with
    ``EXDEV``, as the server does. ``faults`` maps an operation and a place to an error number
    that the next such call raises one time: ``("write", p)`` and ``("fsync", p)`` fail a copy
    to ``p``, ``("link", p)`` a link to ``p``, and ``("fsync", d)`` the flush of the directory
    ``d``, also the flush at the end of a copy into ``d``. ``free`` maps a mount to the bytes
    that are free on its filesystem. A mount that ``free`` does not name has :data:`FREE_BYTES`
    free.
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
        self.mounts: set[LakePath] = set()
        self.faults: dict[tuple[str, LakePath], int] = {}
        self.free: dict[LakePath, int] = {}
        self.inherits = True
        self.umask = 0o022
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
        """Plant a symbolic link to ``target``; for tests only, Huron makes no link.

        An existing entry at ``location`` is refused, as the system call refuses it.
        """
        self._require_parent(location)
        if self.nodes.get(location) is not None:
            raise _error(location, errno.EEXIST)
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
        refused. A :attr:`umask` that takes bits of ``0750`` refuses it too.
        """
        if not self._new_directory(location):
            return False
        parent = self.nodes[location.parent]
        if not (self.inherits and parent.mode & stat.S_ISGID):
            raise InheritanceFailed(
                location, f"the directory did not inherit the setgid bit and the group {parent.gid}"
            )
        mode = INHERITING_DIR_MODE & ~self.umask | stat.S_ISGID
        if mode != INHERITED_MODE:
            raise InheritanceFailed(
                location, f"the directory has the mode {mode:o}, not {INHERITED_MODE:o}"
            )
        self.nodes[location] = Node(
            mode=INHERITED_MODE,
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
        """Store ``data`` with ``mode``; the new file takes its group from a setgid parent.

        The steps are those of the POSIX adapter's atomic write through ``<name>.huron-part``:
        refuse a link at the name, refuse a link or a directory at the part file, remove a part
        file that an earlier attempt left, then write. A directory at the name fails after the
        part file is removed.
        """
        self._require_parent(location)
        existing = self._final(location)
        part = location.parent.joinpath(f"{location.name}{PART_SUFFIX}")
        self._no_directory(part)
        self._check(location.parent, location)
        if self.nodes.pop(part, None) is not None:
            self.calls.append(("unlink", part))
        if existing is not None and existing.kind == "dir":
            raise _error(location, errno.EISDIR)
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

    def rename(self, source: LakePath, destination: LakePath) -> None:
        """Give the file at ``source`` the name ``destination``.

        A directory at ``source`` is refused before the destination is looked up. Two names of
        one file change nothing, as ``rename(2)`` does. A refusal of either parent directory
        names ``destination``, as the POSIX adapter names it, and comes before the refusal of a
        directory at ``destination``.
        """
        found = self._lookup(source)
        if found is None:
            raise _error(source, errno.ENOENT)
        if found.kind == "dir":
            raise _error(source, errno.EISDIR)
        self._require_parent(destination)
        existing = self._final(destination)
        if existing is found:
            return
        self._same_filesystem(source, destination)
        self._check(source.parent, destination)
        self._check(destination.parent, destination)
        if existing is not None and existing.kind == "dir":
            raise _error(destination, errno.EISDIR)
        self.nodes[destination] = self.nodes.pop(source)
        self.calls.append(("rename", destination))

    def copy_sealed(
        self, source: LakePath, destination: LakePath, expected_size: int
    ) -> SealedFile:
        """Copy the file ``source`` to a new node at ``destination`` with mode ``0644``.

        The copy is a new node with a new inode, so a later change to the source's node does
        not change it. The checks come in the order of the POSIX adapter: the source, then
        the destination. An injected ``write`` or ``fsync`` fault at ``destination``, or an
        ``fsync`` fault at its directory, fails the copy and leaves no node, as the POSIX
        adapter removes its copy.
        """
        self._require_parent(source)
        found = self._final(source)
        if found is None or found.kind != "file":
            raise SourceGone(source)
        if len(found.data) != expected_size:
            raise SourceSizeMismatch(source, expected_size, len(found.data))
        self._require_parent(destination)
        if self._final(destination) is not None:
            raise _error(destination, errno.EEXIST)
        self._check(destination.parent, destination)
        self._fault("write", destination)
        self._fault("fsync", destination)
        self._fault("fsync", destination.parent, destination)
        self._clock += 1
        copy = Node(
            "file",
            FILE_MODE,
            self.uid,
            self._new_gid(destination.parent),
            found.data,
            self._clock,
            next(self._inodes),
        )
        self.nodes[destination] = copy
        self.calls += [("copy", destination), ("sync", destination.parent)]
        return SealedFile(len(copy.data), hashlib.sha256(copy.data).hexdigest(), copy.inode)

    def link_once(self, source: LakePath, destination: LakePath) -> None:
        """Give the file at ``source`` the new name ``destination`` too; nothing is replaced.

        The checks come in the order of the POSIX adapter and of ``link(2)``: the source, an
        existing destination (``EEXIST``), another filesystem (``EXDEV``), then a refusal of
        the destination's directory. An injected ``link`` fault at ``destination`` fails it.
        """
        self._require_parent(source)
        found = self._final(source)
        if found is None:
            raise _error(source, errno.ENOENT)
        if found.kind == "dir":
            raise _error(source, errno.EISDIR)
        self._require_parent(destination)
        if self._final(destination) is not None:
            raise _error(destination, errno.EEXIST)
        self._same_filesystem(source, destination)
        self._check(destination.parent, destination)
        self._fault("link", destination)
        self.nodes[destination] = found
        self.calls.append(("link", destination))

    def sync_directory(self, location: LakePath) -> None:
        """Record the flush of the directory ``location``; an injected ``fsync`` fault fails it."""
        self._directory(location)
        self._fault("fsync", location)
        self.calls.append(("sync", location))

    def free_space(self, location: LakePath) -> FreeSpace:
        """The free space of the filesystem of the directory ``location``: its bytes of
        :attr:`free`, and the inode of its mount as the filesystem.
        """
        self._directory(location)
        mount = self._filesystem(location)
        return FreeSpace(self.nodes[mount].inode, self.free.get(mount, FREE_BYTES))

    def remove_file(self, location: LakePath, *, inode: int | None = None) -> Outcome:
        """Remove a file; with ``inode``, only while the file has that inode.

        A refusal of the parent directory comes before the refusal of a directory.
        """
        node = self._lookup(location)
        if node is None:
            return Outcome.MISSING
        if inode is not None and node.inode != inode:
            return Outcome.KEPT
        self._check(location.parent, location)
        if node.kind == "dir":
            raise _error(location, errno.EISDIR)
        del self.nodes[location]
        self.calls.append(("unlink", location))
        return Outcome.REMOVED

    def remove_directory(self, location: LakePath) -> Outcome:
        """Remove an empty directory; ``KEPT`` when it has entries.

        A refusal of the parent directory comes before the refusal of a file and before
        ``KEPT``.
        """
        node = self._lookup(location)
        if node is None:
            return Outcome.MISSING
        self._check(location.parent, location)
        if node.kind != "dir":
            raise _error(location, errno.ENOTDIR)
        if any(self._children(location)):
            return Outcome.KEPT
        del self.nodes[location]
        self.calls.append(("rmdir", location))
        return Outcome.REMOVED

    def in_group(self, gid: int) -> bool:
        """Whether ``gid`` is one of :attr:`member_of`."""
        return gid in self.member_of

    def _parent(self, location: LakePath) -> Node | None:
        """The directory that holds ``location``, opened as the POSIX traversal opens it.

        ``None`` when a name on the way does not exist. A link on the way is
        ``SymlinkInLake``, a file on the way ``ENOTDIR`` and an unreadable directory ``EACCES``.
        As on the server, opening a directory needs search permission on the directories above
        it only. The look-up of a name in it (:meth:`_final`) needs search permission on it.
        """
        current = LakePath()
        node = self.nodes[current]
        for name in location.parent.names:
            self._search(current, location)
            current = current.joinpath(name)
            found = self.nodes.get(current)
            if found is None:
                return None
            if found.kind == "symlink":
                raise SymlinkInLake(current)
            if found.kind != "dir":
                raise _error(location, errno.ENOTDIR)
            node = found
        return node

    def _require_parent(self, location: LakePath) -> Node:
        parent = self._parent(location)
        if parent is None:
            raise _error(location, errno.ENOENT)
        return parent

    def _final(self, location: LakePath) -> Node | None:
        """The node at the last name of ``location``, looked up in its parent directory."""
        self._search(location.parent, location)
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
        self._search(location, location)

    def _new_directory(self, location: LakePath) -> bool:
        """Whether ``location`` is free for a new directory; ``False`` for an existing one."""
        self._require_parent(location)
        existing = self._final(location)
        if existing is not None:
            if existing.kind == "dir":
                return False
            raise _error(location, errno.EEXIST)
        self._check(location.parent, location)
        return True

    def _no_directory(self, location: LakePath) -> None:
        """Refuse a link or a directory at a part file; the error names the file."""
        found = self._final(location)
        if found is not None and found.kind == "dir":
            raise _error(location, errno.EISDIR)

    def _children(self, location: LakePath) -> Iterator[LakePath]:
        return (p for p in self.nodes if p.parent == location and p != location)

    def _walk(self, top: LakePath, prefix: tuple[str, ...]) -> Iterator[Entry]:
        for child in sorted(self._children(top.joinpath(*prefix)), key=lambda p: p.name):
            node, names = self.nodes[child], (*prefix, child.name)
            yield Entry(names, node.kind, len(node.data), node.mtime_ns)
            if node.kind == "dir":
                self._search(child, top)
                yield from self._walk(top, names)

    def _search(self, directory: LakePath, location: LakePath) -> None:
        """Refuse a ``directory`` that cannot be searched; the error names ``location``, the
        place the caller asked for, as the POSIX adapter names it.
        """
        if directory in self.unreadable:
            raise _error(location, errno.EACCES)

    def _check(self, directory: LakePath, location: LakePath) -> None:
        """Refuse a change in a denied ``directory``; the error names ``location``."""
        if directory in self.denied:
            raise _error(location, errno.EACCES)

    def _same_filesystem(self, source: LakePath, destination: LakePath) -> None:
        """Refuse a link or a rename across two filesystems (``EXDEV``); the error names
        ``destination``.
        """
        if self._filesystem(source) != self._filesystem(destination):
            raise _error(destination, errno.EXDEV)

    def _filesystem(self, location: LakePath) -> LakePath:
        """The mount that holds ``location``: the deepest of :attr:`mounts` above it, or the
        root.
        """
        above = [m for m in self.mounts if location.names[: len(m.names)] == m.names]
        return max(above, key=lambda mount: len(mount.names), default=LakePath())

    def _fault(self, operation: str, location: LakePath, named: LakePath | None = None) -> None:
        """Raise the error of an injected fault of ``operation`` at ``location``, one time.

        The error names ``named`` when it is given, else ``location``.
        """
        number = self.faults.pop((operation, location), None)
        if number is not None:
            raise _error(location if named is None else named, number)

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
