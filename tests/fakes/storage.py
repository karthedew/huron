"""Views of an in-memory share: one rooted at a directory below its root, and a read-only one."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from huron.core.storage import (
    Entry,
    FreeSpace,
    GroupResult,
    LakePath,
    LakeUnavailable,
    OpenFile,
    Outcome,
    SealedFile,
    Stat,
    Storage,
    SymlinkInLake,
)
from huron.core.storage.memory import MemoryStorage

#: The methods of the ``Storage`` port that change the share. ``sync_directory`` changes no
#: entry, so a read-only share allows it.
WRITES = frozenset(
    {
        "copy_sealed",
        "link_once",
        "make_directory",
        "make_inheriting_dir",
        "remove_directory",
        "remove_file",
        "rename",
        "set_group",
        "set_mode",
        "set_owner",
        "write_bytes",
    }
)


class Subtree:
    """The storage of ``share`` rooted at its directory ``base``, as a POSIX storage there.

    When ``stat`` or ``read_bytes`` meets a link below ``base``, the error names the link by
    its path below ``base``, as a POSIX storage there names it. A link at ``base`` gets the
    empty path. Every other error keeps its path in the share.
    """

    def __init__(self, share: MemoryStorage, base: LakePath) -> None:
        self.share = share
        self.base = base

    def stat(self, location: LakePath) -> Stat | None:
        with self._rooted():
            return self.share.stat(self._in(location))

    def read_bytes(self, location: LakePath) -> bytes | None:
        with self._rooted():
            return self.share.read_bytes(self._in(location))

    def is_empty(self, location: LakePath) -> bool:
        return self.share.is_empty(self._in(location))

    def walk(self, location: LakePath, *, recursive: bool = True) -> Iterator[Entry]:
        return self.share.walk(self._in(location), recursive=recursive)

    def open_file(self, location: LakePath) -> OpenFile | None:
        return self.share.open_file(self._in(location))

    def make_directory(self, location: LakePath, mode: int) -> bool:
        return self.share.make_directory(self._in(location), mode)

    def make_inheriting_dir(self, location: LakePath) -> bool:
        return self.share.make_inheriting_dir(self._in(location))

    def set_mode(self, location: LakePath, mode: int) -> bool:
        return self.share.set_mode(self._in(location), mode)

    def set_owner(self, location: LakePath, uid: int, gid: int) -> bool:
        return self.share.set_owner(self._in(location), uid, gid)

    def set_group(self, location: LakePath, group: str | int) -> GroupResult:
        return self.share.set_group(self._in(location), group)

    def write_bytes(self, location: LakePath, data: bytes, mode: int) -> None:
        self.share.write_bytes(self._in(location), data, mode)

    def rename(self, source: LakePath, destination: LakePath) -> None:
        self.share.rename(self._in(source), self._in(destination))

    def copy_sealed(
        self, source: LakePath, destination: LakePath, expected_size: int
    ) -> SealedFile:
        return self.share.copy_sealed(self._in(source), self._in(destination), expected_size)

    def link_once(self, source: LakePath, destination: LakePath) -> None:
        self.share.link_once(self._in(source), self._in(destination))

    def sync_directory(self, location: LakePath) -> None:
        self.share.sync_directory(self._in(location))

    def in_group(self, gid: int) -> bool:
        return self.share.in_group(gid)

    def free_space(self, location: LakePath) -> FreeSpace:
        return self.share.free_space(self._in(location))

    def remove_file(self, location: LakePath, *, inode: int | None = None) -> Outcome:
        return self.share.remove_file(self._in(location), inode=inode)

    def remove_directory(self, location: LakePath) -> Outcome:
        return self.share.remove_directory(self._in(location))

    def _in(self, location: LakePath) -> LakePath:
        return self.base.joinpath(*location.names)

    @contextmanager
    def _rooted(self) -> Iterator[None]:
        try:
            yield
        except SymlinkInLake as error:
            names = LakePath.parse(str(error.context["path"])).names
            if names[: len(self.base.names)] != self.base.names:
                raise
            raise SymlinkInLake(LakePath.of(*names[len(self.base.names) :])) from error


def rooted(share: MemoryStorage) -> Callable[[Path], Any]:
    """A storage factory: ``share`` rooted at a directory below its root, as on a machine.

    A directory outside the share's root is not mounted: its storage does not open.
    """

    def storage(base: Path) -> Any:
        if not base.is_relative_to(share.root):
            return Unmounted()
        return Subtree(share, LakePath.of(*base.relative_to(share.root).parts))

    return storage


class Unmounted:
    """A storage whose root does not open, as for a directory that nothing is mounted at."""

    def __getattr__(self, name: str) -> Any:
        def refuse(*args: object, **kwargs: object) -> None:
            raise LakeUnavailable("the lake does not open as a directory", {"path": ""})

        return refuse


class ReadOnlyShare:
    """Reads go to ``share``; a call of a write method raises :class:`AssertionError`."""

    def __init__(self, share: Storage) -> None:
        self.share = share

    def __getattr__(self, name: str) -> Any:
        if name in WRITES:
            return _refuse(name)
        return getattr(self.share, name)


def _refuse(name: str) -> Callable[..., None]:
    def write(*args: object, **kwargs: object) -> None:
        raise AssertionError(f"a write to the read-only share: {name}{args}")

    return write
