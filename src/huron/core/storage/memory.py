"""An in-memory share for tests: directories, files, modes, ACLs and owners."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from huron.core.storage.errors import StorageError
from huron.core.storage.ports import FileStamp
from huron.pkg.fs.acl import Acl
from huron.pkg.fs.posix import Entry, Stamp

if TYPE_CHECKING:
    from collections.abc import Iterator

    from huron.core.storage.aclplan import AclPlan

__all__ = ["MemoryStorage", "Node"]


@dataclass
class Node:
    """A directory (``data is None``) or a file."""

    owner: str
    mode: int = 0o2770
    acl: Acl = field(default_factory=Acl)
    group: str | None = None
    data: bytes | None = None
    mtime_ns: int = 0

    @property
    def is_dir(self) -> bool:
        """Whether the node is a directory."""
        return self.data is None


class MemoryStorage:
    """A :class:`Storage` over a dictionary; ``user`` is who the caller is."""

    def __init__(self, root: Path, user: str = "me") -> None:
        self.user = user
        self.nodes: dict[Path, Node] = {root: Node(owner="root", mode=0o2771)}
        self.denied: set[Path] = set()
        self.calls: list[tuple[str, Path]] = []
        self._clock = 0

    def ensure_directory(self, path: Path, plan: AclPlan) -> bool:
        """Create ``path`` (its parent must exist) and apply ``plan``."""
        if not self.is_directory(path.parent):
            raise StorageError(f"{path.parent} does not exist", {"path": str(path.parent)})
        created = path not in self.nodes
        if created:
            self._check(path.parent)
            self.nodes[path] = Node(owner=self.user)
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
            self.nodes[parent] = Node(owner=self.user)
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

    def write_bytes(self, path: Path, data: bytes) -> None:
        """Store ``data`` at ``path``."""
        self._check(path.parent)
        self._clock += 1
        self.nodes[path] = Node(owner=self.user, mode=0o660, data=data, mtime_ns=self._clock)

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
