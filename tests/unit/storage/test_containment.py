"""The contract of the storage port, on both adapters: no operation follows a symbolic link or
leaves the lake, and each method answers each case as its row in :data:`ROWS` says.

:data:`ROWS`, which :func:`table_rows` makes, is the table of errors per port method. It has one
row for each method and case. Each row gives the result: the return value, or the error class
and the exact path that the error names. Each row is checked over ``PosixStorage`` and
``MemoryStorage``. An error changes nothing, in the lake or outside it, unless the row says
otherwise.
"""

import copy
import errno
import hashlib
import itertools
import os
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from huron.core.storage import (
    DIRECTORY_MODE,
    GroupOutcome,
    GroupResult,
    InheritanceFailed,
    LakePath,
    LakeUnavailable,
    Outcome,
    SealedFile,
    SourceGone,
    SourceSizeMismatch,
    Storage,
    StorageError,
    SymlinkInLake,
)
from huron.core.storage.memory import MemoryStorage
from huron.core.storage.posix import PosixStorage
from huron.pkg.errors import HuronError
from tests.support.disk import LAKE, plant_symlink, snapshot

SOURCE = LakePath.of("up", "src")
NAME = LakePath.of("a", "t")
PART = LakePath.of("a", "t.huron-part")
#: The part and backup names that ``link`` gets.
LINK_PART, LINK_BACKUP = ".part", ".prev"
#: The backup that ``link`` keeps when it replaces the file at :data:`NAME`.
BACKUP = LakePath.of("a", LINK_BACKUP)
#: Where ``link source``, ``link_once source`` and ``copy_sealed source`` put their file.
DESTINATION = LakePath.of("up", "dst")
#: The bytes of :data:`SOURCE` in the case ``resized_source``: not the 3 bytes that
#: ``copy_sealed`` expects.
RESIZED = b"longer"
#: Where each case puts the place it asks for; any other case asks for :data:`NAME`.
PLACES = {
    "parent_missing": LakePath.of("a", "gone", "t"),
    "link_above": LakePath.of("a", "l", "t"),
    "file_above": LakePath.of("a", "f", "t"),
    "unsearchable": LakePath.of("a", "p", "t"),
    "read_only": LakePath.of("a", "p", "t"),
}

type Kind = str | None


@dataclass
class Lake:
    """The directories ``a`` (setgid) and ``up`` with the file ``up/src``, on one adapter.

    ``close`` makes a directory that this process cannot search, ``protect`` one that it can
    search but not write. ``state`` is everything in the lake and, on the disk, everything in
    the directory ``outside`` that planted links point to, to compare before and after.
    """

    storage: Storage
    close: Callable[[LakePath], None]
    protect: Callable[[LakePath], None]
    state: Callable[[], object]

    def put(self, location: LakePath, kind: Kind) -> None:
        if kind == "file":
            self.storage.write_bytes(location, b"x", 0o644)
        elif kind == "dir":
            self.storage.make_directory(location, DIRECTORY_MODE)

    def kind(self, location: LakePath) -> Kind:
        found = self.storage.stat(location)
        return None if found is None else found.kind


@pytest.fixture(params=["posix", "memory"])
def lake(
    request: pytest.FixtureRequest,
    tmp_path: Path,
    temporary_mode: Callable[[Path, int], None],
) -> Iterator[Lake]:
    storage: Storage
    if request.param == "posix":
        (tmp_path / "lake").mkdir()
        (tmp_path / "outside" / "inner").mkdir(parents=True)
        (tmp_path / "outside" / "file").write_bytes(b"keep")
        posix = PosixStorage(tmp_path / "lake")
        storage = posix

        def mode(mode: int) -> Callable[[LakePath], None]:
            return lambda at: temporary_mode(posix.root.joinpath(*at.names), mode)

        def files() -> object:
            return snapshot(posix.root), snapshot(tmp_path / "outside")

        made = Lake(posix, mode(0o000), mode(0o550), files)
    else:
        memory = MemoryStorage(LAKE, uid=1000, gid=1000)
        memory.nodes[LakePath()].gid = 1000
        storage = memory

        def state() -> object:
            return copy.deepcopy(memory.nodes), list(memory.calls)

        made = Lake(memory, memory.unreadable.add, memory.denied.add, state)
    storage.make_directory(LakePath.of("a"), DIRECTORY_MODE)
    storage.make_directory(LakePath.of("up"), DIRECTORY_MODE)
    storage.write_bytes(SOURCE, b"new", 0o644)
    yield made


def arrange(lake: Lake, case: str, kind: Kind) -> LakePath:
    """Make ``case`` in ``lake`` and return the place to ask for.

    A case of several parts joined by ``+`` makes each part. ``unsearchable`` and
    ``read_only`` put the place in a directory that is locked last. Without a part that says
    what is at the place, that directory holds ``kind``: the entry the method expects.
    """
    parts = case.split("+")
    at = next((PLACES[part] for part in parts if part in PLACES), NAME)
    locked = [part for part in parts if part in {"unsearchable", "read_only"}]
    if locked:
        lake.put(at.parent, "dir")
        if not ENTRIES.intersection(parts):
            lake.put(at, kind)
    for part in parts:
        SETUPS[part](lake, at)
    for part in locked:
        (lake.close if part == "unsearchable" else lake.protect)(at.parent)
    return at


def beside(at: LakePath, name: str) -> LakePath:
    return at.parent.joinpath(name)


def part_of(at: LakePath) -> LakePath:
    return beside(at, f"{at.name}.huron-part")


def full_directory(lake: Lake, at: LakePath) -> None:
    lake.put(at, "dir")
    lake.put(at.joinpath("keep"), "file")


def replaced_with(planted: Callable[[Lake, LakePath], None]) -> Callable[[Lake, LakePath], None]:
    """A file at the place, so that ``link`` replaces it, and ``planted`` beside it."""

    def setup(lake: Lake, at: LakePath) -> None:
        lake.put(at, "file")
        planted(lake, at)

    return setup


def nothing(lake: Lake, at: LakePath) -> None:
    """The case needs nothing beyond the place."""


def same_file(lake: Lake, at: LakePath) -> None:
    """A second name of :data:`SOURCE` at the place."""
    storage = lake.storage
    storage.link(
        SOURCE, at, inode=source_inode(storage), part_name=LINK_PART, backup_name=LINK_BACKUP
    )


SETUPS: dict[str, Callable[[Lake, LakePath], None]] = {
    "missing": nothing,
    "parent_missing": nothing,
    "unsearchable": nothing,
    "read_only": nothing,
    "link_at_name": lambda lake, at: plant_symlink(lake.storage, at),
    "link_above": lambda lake, at: plant_symlink(lake.storage, at.parent),
    "file_above": lambda lake, at: lake.put(at.parent, "file"),
    "dir_at_name": lambda lake, at: lake.put(at, "dir"),
    "file_at_name": lambda lake, at: lake.put(at, "file"),
    "nonempty_dir": full_directory,
    "dir_at_part": lambda lake, at: full_directory(lake, part_of(at)),
    "part_and_dir": lambda lake, at: (lake.put(part_of(at), "file"), lake.put(at, "dir")),
    "link_at_part": lambda lake, at: plant_symlink(lake.storage, part_of(at)),
    "old_part": lambda lake, at: lake.put(part_of(at), "file"),
    "dir_at_part_name": replaced_with(lambda lake, at: full_directory(lake, beside(at, LINK_PART))),
    "dir_at_backup_name": replaced_with(
        lambda lake, at: full_directory(lake, beside(at, LINK_BACKUP))
    ),
    "link_at_part_name": replaced_with(
        lambda lake, at: plant_symlink(lake.storage, beside(at, LINK_PART))
    ),
    "link_at_backup_name": replaced_with(
        lambda lake, at: plant_symlink(lake.storage, beside(at, LINK_BACKUP))
    ),
    "same_file_at_name": same_file,
    "source_missing": lambda lake, at: lake.storage.remove_file(SOURCE),
    "resized_source": lambda lake, at: lake.storage.write_bytes(SOURCE, RESIZED, 0o644),
}
#: The parts of a case by group. A way part says that the parent is not a directory, a lock
#: part that the parent is a directory without a permission, and a source part what is at the
#: source of ``link``, ``link_once``, ``copy_sealed`` or ``rename``. Every other part is an
#: entry part: it states everything at the name and beside it.
WAY = frozenset({"parent_missing", "link_above", "file_above"})
LOCK = frozenset({"unsearchable", "read_only"})
SOURCES = frozenset({"source_missing", "resized_source"})
ENTRIES = frozenset(SETUPS) - WAY - LOCK - SOURCES
#: The pairs of groups whose parts cannot hold at once, with the reason.
UNARRANGEABLE: dict[frozenset[str], str] = {
    frozenset({"way"}): "the parent is one entry: missing, a link or a file",
    frozenset({"way", "lock"}): "a parent without a permission is a directory",
    frozenset({"way", "entry"}): "nothing is in a parent that is missing, a link or a file",
    frozenset({"lock"}): "a parent without search permission has no write permission either",
    frozenset({"entry"}): "each entry part states everything at the name and beside it",
    frozenset({"source"}): "the source is one entry: missing or resized",
}


def group_of(part: str) -> str:
    if part in WAY:
        return "way"
    if part in LOCK:
        return "lock"
    return "source" if part in SOURCES else "entry"


def arrangeable_pairs(method: str) -> set[frozenset[str]]:
    """Every pair of the method's case parts that can hold at once.

    The method's parts are those of its rows. A pair is arrangeable unless its two groups are
    in :data:`UNARRANGEABLE`.
    """
    parts = sorted({part for row in ROWS if row.method == method for part in row.case.split("+")})
    return {
        frozenset(pair)
        for pair in itertools.combinations(parts, 2)
        if frozenset(map(group_of, pair)) not in UNARRANGEABLE
    }


def file_inode(storage: Storage, at: LakePath) -> int:
    """The inode of the file at ``at``; 0, which no file has, for anything else."""
    try:
        found = storage.stat(at)
    except StorageError:
        return 0
    return found.inode if found is not None and found.kind == "file" else 0


def source_inode(storage: Storage) -> int:
    """The inode of :data:`SOURCE`; 0, which no file has, when a case removed it."""
    found = storage.stat(SOURCE)
    return 0 if found is None else found.inode


def copied(storage: Storage, at: LakePath, sealed: SealedFile) -> tuple[int, str, bool]:
    """The size and the sha256 of a copy, and whether the file at ``at`` has its inode."""
    return sealed.size, sealed.sha256, sealed.inode == file_inode(storage, at)


#: Each method: the entry it expects at its place, and the call.
METHODS: dict[str, tuple[Kind, Callable[[Storage, LakePath], object]]] = {
    "stat": (None, lambda storage, at: storage.stat(at)),
    "read_bytes": ("file", lambda storage, at: storage.read_bytes(at)),
    "is_empty": ("dir", lambda storage, at: storage.is_empty(at)),
    "walk": ("dir", lambda storage, at: list(storage.walk(at))),
    "open_file": ("file", lambda storage, at: storage.open_file(at)),
    "make_directory": (None, lambda storage, at: storage.make_directory(at, DIRECTORY_MODE)),
    "make_inheriting_dir": (None, lambda storage, at: storage.make_inheriting_dir(at)),
    "set_mode": ("dir", lambda storage, at: storage.set_mode(at, 0o700)),
    "set_group": ("dir", lambda storage, at: storage.set_group(at, 0)),
    "write_bytes": (None, lambda storage, at: storage.write_bytes(at, b"y", 0o644)),
    "link": (
        None,
        lambda storage, at: storage.link(
            SOURCE,
            at,
            inode=source_inode(storage),
            part_name=LINK_PART,
            backup_name=LINK_BACKUP,
        ),
    ),
    "link source": (
        "file",
        lambda storage, at: storage.link(
            at,
            DESTINATION,
            inode=file_inode(storage, at),
            part_name=LINK_PART,
            backup_name=LINK_BACKUP,
        ),
    ),
    "copy_sealed": (
        None,
        lambda storage, at: copied(storage, at, storage.copy_sealed(SOURCE, at, len(b"new"))),
    ),
    "copy_sealed source": (
        "file",
        lambda storage, at: copied(
            storage, DESTINATION, storage.copy_sealed(at, DESTINATION, len(b"x"))
        ),
    ),
    "link_once": (None, lambda storage, at: storage.link_once(SOURCE, at)),
    "link_once source": ("file", lambda storage, at: storage.link_once(at, DESTINATION)),
    "sync_directory": ("dir", lambda storage, at: storage.sync_directory(at)),
    "free_space": ("dir", lambda storage, at: storage.free_space(at).free > 0),
    "rename": (None, lambda storage, at: storage.rename(SOURCE, at)),
    "rename source": ("file", lambda storage, at: storage.rename(at, LakePath.of("up", "moved"))),
    "remove_file": ("file", lambda storage, at: storage.remove_file(at)),
    "remove_directory": ("dir", lambda storage, at: storage.remove_directory(at)),
}


@dataclass(frozen=True)
class Returns:
    """The method returns ``value``."""

    value: object


@dataclass(frozen=True)
class Raises:
    """The method raises ``error`` that names ``path``; ``reason`` gives its message."""

    error: type[StorageError]
    path: str
    reason: str = ""

    def message(self) -> str:
        if self.error is SymlinkInLake:
            return (
                f"{self.path} is a symbolic link. The lake must not contain symbolic links."
                " Remove it."
            )
        if self.error is SourceGone:
            return f"the upload file {self.path} does not exist"
        if self.error is SourceSizeMismatch:
            return f"the upload file {self.path} has {len(RESIZED)} bytes, not 3 bytes"
        if self.reason == "ENOENT":
            return f"{self.path} does not exist"
        if self.reason == "EACCES":
            return f"permission denied on {self.path}"
        return f"{self.path}: {os.strerror(getattr(errno, self.reason))}"


@dataclass(frozen=True)
class Row:
    """One row of the table; ``after`` names the kinds of entries after the call.

    Without ``after``, an error leaves the lake as it was.
    """

    method: str
    case: str
    result: Returns | Raises
    after: Mapping[LakePath, Kind] = field(default_factory=dict)


LINK_AT_NAME = Raises(SymlinkInLake, "a/t")
LINK_ABOVE = Raises(SymlinkInLake, "a/l")
FILE_ABOVE = Raises(StorageError, "a/f/t", "ENOTDIR")
NAME_MISSING = Raises(StorageError, "a/t", "ENOENT")
PARENT_MISSING = Raises(StorageError, "a/gone/t", "ENOENT")
DENIED = Raises(StorageError, "a/p/t", "EACCES")


def traversal_rows(method: str) -> list[Row]:
    """The rows that every method shares: a link at or above the name, a file above it, and
    a parent that this process cannot search.
    """
    return [
        Row(method, "link_at_name", LINK_AT_NAME),
        Row(method, "link_above", LINK_ABOVE),
        Row(method, "file_above", FILE_ABOVE),
        Row(method, "unsearchable", DENIED),
    ]


def table_rows() -> list[Row]:
    rows: list[Row] = []
    for method in ("stat", "read_bytes", "open_file"):
        rows += [
            Row(method, "missing", Returns(None)),
            Row(method, "parent_missing", Returns(None)),
            *traversal_rows(method),
        ]
    for method in ("read_bytes", "open_file"):
        rows.append(Row(method, "dir_at_name", Raises(StorageError, "a/t", "EISDIR")))
    for method in ("is_empty", "walk", "set_mode"):
        rows += [
            Row(method, "missing", NAME_MISSING),
            Row(method, "parent_missing", PARENT_MISSING),
            *traversal_rows(method),
        ]
    for method in ("is_empty", "walk"):
        rows.append(Row(method, "file_at_name", Raises(StorageError, "a/t", "ENOTDIR")))
    for method in ("make_directory", "make_inheriting_dir"):
        rows += [
            Row(method, "missing", Returns(True)),
            Row(method, "parent_missing", PARENT_MISSING),
            *traversal_rows(method),
            Row(method, "dir_at_name", Returns(False)),
            Row(method, "file_at_name", Raises(StorageError, "a/t", "EEXIST")),
            Row(method, "read_only", DENIED),
        ]
    rows += [
        Row("set_mode", "file_at_name", Returns(True)),
        Row(
            "set_group", "missing", Returns(GroupResult(GroupOutcome.PENDING, "a/t does not exist"))
        ),
        Row(
            "set_group",
            "parent_missing",
            Returns(GroupResult(GroupOutcome.PENDING, "a/gone/t does not exist")),
        ),
        *traversal_rows("set_group"),
        Row(
            "set_group",
            "file_at_name",
            Returns(GroupResult(GroupOutcome.PENDING, f"a/t: {os.strerror(errno.EPERM)}")),
        ),
    ]
    for method, created in (("write_bytes", "file"), ("link", "file"), ("rename", "file")):
        rows += [
            Row(method, "missing", Returns(None), {NAME: created}),
            Row(method, "parent_missing", PARENT_MISSING),
            *traversal_rows(method),
            Row(method, "dir_at_name", Raises(StorageError, "a/t", "EISDIR")),
            Row(method, "read_only", DENIED),
        ]
    rows += [
        Row("write_bytes", "dir_at_part", Raises(StorageError, "a/t.huron-part", "EISDIR")),
        Row(
            "write_bytes",
            "part_and_dir",
            Raises(StorageError, "a/t", "EISDIR"),
            {PART: None, NAME: "dir"},
        ),
        Row("write_bytes", "link_at_part", Raises(SymlinkInLake, "a/t.huron-part")),
        Row("write_bytes", "old_part", Returns(None), {PART: None, NAME: "file"}),
        Row("write_bytes", "file_at_name", Returns(None), {PART: None, NAME: "file"}),
    ]
    rows += [
        Row(
            "link",
            "file_at_name",
            Returns(BACKUP),
            {NAME: "file", BACKUP: "file", beside(NAME, LINK_PART): None},
        ),
        Row("link", "source_missing", Raises(SourceGone, "up/src")),
        Row("rename", "file_at_name", Returns(None), {NAME: "file", SOURCE: None}),
        Row("rename", "source_missing", Raises(StorageError, "up/src", "ENOENT")),
    ]
    rows += [
        Row("link source", "missing", Raises(SourceGone, "a/t")),
        Row("link source", "parent_missing", PARENT_MISSING),
        *traversal_rows("link source"),
        Row("link source", "dir_at_name", Raises(SourceGone, "a/t")),
        Row("link source", "read_only", Returns(None), {DESTINATION: "file"}),
        Row("rename", "same_file_at_name", Returns(None), {NAME: "file", SOURCE: "file"}),
    ]
    rows += [
        Row("rename source", "missing", NAME_MISSING),
        Row("rename source", "parent_missing", PARENT_MISSING),
        *traversal_rows("rename source"),
        Row("rename source", "dir_at_name", Raises(StorageError, "a/t", "EISDIR")),
        Row("rename source", "read_only", Raises(StorageError, "up/moved", "EACCES")),
    ]
    rows += [
        Row("link", "dir_at_part_name", Raises(StorageError, "a/.part", "EISDIR")),
        Row("link", "dir_at_backup_name", Raises(StorageError, "a/.prev", "EISDIR")),
        Row("link", "link_at_part_name", Raises(SymlinkInLake, "a/.part")),
        Row("link", "link_at_backup_name", Raises(SymlinkInLake, "a/.prev")),
        Row("remove_directory", "nonempty_dir", Returns(Outcome.KEPT)),
    ]
    rows += [
        Row("remove_file", "missing", Returns(Outcome.MISSING)),
        Row("remove_file", "parent_missing", Returns(Outcome.MISSING)),
        *traversal_rows("remove_file"),
        Row("remove_file", "dir_at_name", Raises(StorageError, "a/t", "EISDIR")),
        Row("remove_file", "read_only", DENIED),
        Row("remove_directory", "missing", Returns(Outcome.MISSING)),
        Row("remove_directory", "parent_missing", Returns(Outcome.MISSING)),
        *traversal_rows("remove_directory"),
        Row("remove_directory", "file_at_name", Raises(StorageError, "a/t", "ENOTDIR")),
        Row("remove_directory", "read_only", DENIED),
    ]
    return rows + publication_rows() + combined_rows() + combined_publication_rows()


#: The result of a copy of :data:`SOURCE` (``new``) and of a file that a case put (``x``).
COPY_OF_SOURCE = Returns((3, hashlib.sha256(b"new").hexdigest(), True))
COPY_OF_PUT = Returns((1, hashlib.sha256(b"x").hexdigest(), True))
SOURCE_GONE = Raises(SourceGone, "up/src")
RESIZED_SOURCE = Raises(SourceSizeMismatch, "up/src")
SOURCE_MISSING = Raises(StorageError, "up/src", "ENOENT")
EXISTS = Raises(StorageError, "a/t", "EEXIST")
LOCKED_EXISTS = Raises(StorageError, "a/p/t", "EEXIST")
LOCKED_DENIED = Raises(StorageError, "a/p/t", "EACCES")
LOCKED_LINK = Raises(SymlinkInLake, "a/p/t")
#: The methods that act on a directory and change no entry.
DIRECTORY_METHODS = ("sync_directory", "free_space")


def publication_rows() -> list[Row]:
    """The rows of the methods that seal and publish: ``copy_sealed``, ``link_once``,
    ``sync_directory`` and ``free_space``.
    """
    rows: list[Row] = []
    for method, created in (("copy_sealed", COPY_OF_SOURCE), ("link_once", Returns(None))):
        rows += [
            Row(method, "missing", created, {NAME: "file"}),
            Row(method, "parent_missing", PARENT_MISSING),
            *traversal_rows(method),
            Row(method, "dir_at_name", EXISTS),
            Row(method, "file_at_name", EXISTS),
            Row(method, "read_only", DENIED),
        ]
    rows += [
        Row("copy_sealed", "source_missing", SOURCE_GONE),
        Row("copy_sealed", "resized_source", RESIZED_SOURCE),
        Row("link_once", "source_missing", SOURCE_MISSING),
        Row("link_once", "same_file_at_name", EXISTS),
    ]
    rows += [
        Row("copy_sealed source", "missing", Raises(SourceGone, "a/t")),
        Row("copy_sealed source", "parent_missing", PARENT_MISSING),
        *traversal_rows("copy_sealed source"),
        Row("copy_sealed source", "dir_at_name", Raises(SourceGone, "a/t")),
        Row("copy_sealed source", "read_only", COPY_OF_PUT, {DESTINATION: "file"}),
        Row("link_once source", "missing", NAME_MISSING),
        Row("link_once source", "parent_missing", PARENT_MISSING),
        *traversal_rows("link_once source"),
        Row("link_once source", "dir_at_name", Raises(StorageError, "a/t", "EISDIR")),
        Row("link_once source", "read_only", Returns(None), {DESTINATION: "file"}),
    ]
    for method, read_only in (("sync_directory", None), ("free_space", True)):
        rows += [
            Row(method, "missing", NAME_MISSING),
            Row(method, "parent_missing", PARENT_MISSING),
            *traversal_rows(method),
            Row(method, "file_at_name", Raises(StorageError, "a/t", "ENOTDIR")),
            Row(method, "read_only", Returns(read_only)),
        ]
    return rows


def combined_publication_rows() -> list[Row]:
    """The rows of ``copy_sealed``, ``link_once`` and ``sync_directory`` where two cases hold
    at once. Both methods with a source check the source first.
    """
    rows: list[Row] = []
    for method, sources in (
        ("copy_sealed", {"source_missing": SOURCE_GONE, "resized_source": RESIZED_SOURCE}),
        ("link_once", {"source_missing": SOURCE_MISSING}),
    ):
        entries = ["missing", "link_at_name", "dir_at_name", "file_at_name"]
        if method == "link_once":
            entries.append("same_file_at_name")
        for source, refused in sources.items():
            rows += [
                Row(method, f"{other}+{source}", refused)
                for other in ["parent_missing", "link_above", "file_above", *sorted(LOCK), *entries]
            ]
        rows += [Row(method, f"unsearchable+{entry}", LOCKED_DENIED) for entry in entries]
        rows += [
            Row(method, "read_only+missing", LOCKED_DENIED),
            Row(method, "read_only+link_at_name", LOCKED_LINK),
            *(
                Row(method, f"read_only+{entry}", LOCKED_EXISTS)
                for entry in entries
                if entry not in {"missing", "link_at_name"}
            ),
        ]
    for method, missing, directory in (
        ("copy_sealed source", Raises(SourceGone, "a/p/t"), Raises(SourceGone, "a/p/t")),
        (
            "link_once source",
            Raises(StorageError, "a/p/t", "ENOENT"),
            Raises(StorageError, "a/p/t", "EISDIR"),
        ),
        *(
            (
                directory_method,
                Raises(StorageError, "a/p/t", "ENOENT"),
                Raises(StorageError, "a/p/t", "ENOTDIR"),
            )
            for directory_method in DIRECTORY_METHODS
        ),
    ):
        other = "file_at_name" if method in DIRECTORY_METHODS else "dir_at_name"
        rows += [
            Row(method, f"unsearchable+{entry}", LOCKED_DENIED)
            for entry in ("missing", "link_at_name", other)
        ]
        rows += [
            Row(method, "read_only+missing", missing),
            Row(method, "read_only+link_at_name", LOCKED_LINK),
            Row(method, f"read_only+{other}", directory),
        ]
    return rows


def combined_rows() -> list[Row]:
    """The rows where two cases hold at once; the precedence rule of the table decides."""
    rows = [
        Row(method, f"unsearchable+{entry}", DENIED)
        for method, entry in (
            ("stat", "missing"),
            ("set_mode", "missing"),
            ("set_mode", "file_at_name"),
            ("set_group", "missing"),
            ("set_group", "file_at_name"),
            ("read_bytes", "dir_at_name"),
            ("open_file", "dir_at_name"),
            ("is_empty", "file_at_name"),
            ("walk", "file_at_name"),
            ("make_directory", "file_at_name"),
            ("make_inheriting_dir", "file_at_name"),
            ("write_bytes", "dir_at_name"),
            ("link", "dir_at_name"),
            ("link source", "dir_at_name"),
            ("rename", "dir_at_name"),
            ("rename source", "dir_at_name"),
            ("remove_file", "dir_at_name"),
            ("remove_directory", "file_at_name"),
        )
    ]
    for method in ("make_directory", "make_inheriting_dir"):
        rows += [
            Row(method, "read_only+dir_at_name", Returns(False)),
            Row(method, "read_only+file_at_name", Raises(StorageError, "a/p/t", "EEXIST")),
        ]
    rows += [
        Row("write_bytes", "read_only+dir_at_name", DENIED),
        Row("write_bytes", "read_only+file_at_name", DENIED),
        Row(
            "write_bytes",
            "read_only+dir_at_part",
            Raises(StorageError, "a/p/t.huron-part", "EISDIR"),
        ),
        Row("write_bytes", "read_only+old_part", DENIED),
        Row("link", "read_only+dir_at_name", Raises(StorageError, "a/p/t", "EISDIR")),
        Row("link", "read_only+file_at_name", DENIED),
        Row("link", "read_only+dir_at_part_name", Raises(StorageError, "a/p/.part", "EISDIR")),
        Row("link", "read_only+source_missing", Raises(SourceGone, "up/src")),
        Row("link", "unsearchable+source_missing", Raises(SourceGone, "up/src")),
        Row("link", "parent_missing+source_missing", PARENT_MISSING),
        Row("rename", "read_only+dir_at_name", DENIED),
        Row("rename", "read_only+file_at_name", DENIED),
        Row("rename", "read_only+source_missing", Raises(StorageError, "up/src", "ENOENT")),
        Row("rename", "parent_missing+source_missing", Raises(StorageError, "up/src", "ENOENT")),
        Row("rename source", "read_only+dir_at_name", Raises(StorageError, "a/p/t", "EISDIR")),
        Row("remove_file", "read_only+dir_at_name", DENIED),
        Row("remove_directory", "read_only+file_at_name", DENIED),
        Row("remove_directory", "read_only+nonempty_dir", DENIED),
    ]
    rows += [
        Row("stat", "unsearchable+link_at_name", Raises(StorageError, "a/p/t", "EACCES")),
        Row("read_bytes", "unsearchable+link_at_name", Raises(StorageError, "a/p/t", "EACCES")),
        Row("read_bytes", "unsearchable+missing", Raises(StorageError, "a/p/t", "EACCES")),
        Row("is_empty", "unsearchable+link_at_name", Raises(StorageError, "a/p/t", "EACCES")),
        Row("is_empty", "unsearchable+missing", Raises(StorageError, "a/p/t", "EACCES")),
        Row("walk", "unsearchable+link_at_name", Raises(StorageError, "a/p/t", "EACCES")),
        Row("walk", "unsearchable+missing", Raises(StorageError, "a/p/t", "EACCES")),
        Row("open_file", "unsearchable+link_at_name", Raises(StorageError, "a/p/t", "EACCES")),
        Row("open_file", "unsearchable+missing", Raises(StorageError, "a/p/t", "EACCES")),
        Row("make_directory", "unsearchable+dir_at_name", Raises(StorageError, "a/p/t", "EACCES")),
        Row("make_directory", "read_only+link_at_name", Raises(SymlinkInLake, "a/p/t")),
        Row("make_directory", "unsearchable+link_at_name", Raises(StorageError, "a/p/t", "EACCES")),
        Row("make_directory", "read_only+missing", Raises(StorageError, "a/p/t", "EACCES")),
        Row("make_directory", "unsearchable+missing", Raises(StorageError, "a/p/t", "EACCES")),
        Row(
            "make_inheriting_dir",
            "unsearchable+dir_at_name",
            Raises(StorageError, "a/p/t", "EACCES"),
        ),
        Row("make_inheriting_dir", "read_only+link_at_name", Raises(SymlinkInLake, "a/p/t")),
        Row(
            "make_inheriting_dir",
            "unsearchable+link_at_name",
            Raises(StorageError, "a/p/t", "EACCES"),
        ),
        Row("make_inheriting_dir", "read_only+missing", Raises(StorageError, "a/p/t", "EACCES")),
        Row("make_inheriting_dir", "unsearchable+missing", Raises(StorageError, "a/p/t", "EACCES")),
        Row("set_mode", "unsearchable+link_at_name", Raises(StorageError, "a/p/t", "EACCES")),
        Row("set_group", "unsearchable+link_at_name", Raises(StorageError, "a/p/t", "EACCES")),
        Row("write_bytes", "unsearchable+dir_at_part", Raises(StorageError, "a/p/t", "EACCES")),
        Row("write_bytes", "unsearchable+file_at_name", Raises(StorageError, "a/p/t", "EACCES")),
        Row("write_bytes", "read_only+link_at_name", Raises(SymlinkInLake, "a/p/t")),
        Row("write_bytes", "unsearchable+link_at_name", Raises(StorageError, "a/p/t", "EACCES")),
        Row("write_bytes", "read_only+link_at_part", Raises(SymlinkInLake, "a/p/t.huron-part")),
        Row("write_bytes", "unsearchable+link_at_part", Raises(StorageError, "a/p/t", "EACCES")),
        Row("write_bytes", "read_only+missing", Raises(StorageError, "a/p/t", "EACCES")),
        Row("write_bytes", "unsearchable+missing", Raises(StorageError, "a/p/t", "EACCES")),
        Row("write_bytes", "unsearchable+old_part", Raises(StorageError, "a/p/t", "EACCES")),
        Row("write_bytes", "read_only+part_and_dir", Raises(StorageError, "a/p/t", "EACCES")),
        Row("write_bytes", "unsearchable+part_and_dir", Raises(StorageError, "a/p/t", "EACCES")),
        Row("link", "read_only+dir_at_backup_name", Raises(StorageError, "a/p/.prev", "EISDIR")),
        Row("link", "dir_at_backup_name+source_missing", Raises(SourceGone, "up/src")),
        Row("link", "unsearchable+dir_at_backup_name", Raises(StorageError, "a/p/t", "EACCES")),
        Row("link", "dir_at_name+source_missing", Raises(SourceGone, "up/src")),
        Row("link", "dir_at_part_name+source_missing", Raises(SourceGone, "up/src")),
        Row("link", "unsearchable+dir_at_part_name", Raises(StorageError, "a/p/t", "EACCES")),
        Row("link", "file_above+source_missing", Raises(StorageError, "a/f/t", "ENOTDIR")),
        Row("link", "file_at_name+source_missing", Raises(SourceGone, "up/src")),
        Row("link", "unsearchable+file_at_name", Raises(StorageError, "a/p/t", "EACCES")),
        Row("link", "link_above+source_missing", Raises(SymlinkInLake, "a/l")),
        Row("link", "read_only+link_at_backup_name", Raises(SymlinkInLake, "a/p/.prev")),
        Row("link", "link_at_backup_name+source_missing", Raises(SourceGone, "up/src")),
        Row("link", "unsearchable+link_at_backup_name", Raises(StorageError, "a/p/t", "EACCES")),
        Row("link", "read_only+link_at_name", Raises(SymlinkInLake, "a/p/t")),
        Row("link", "link_at_name+source_missing", Raises(SourceGone, "up/src")),
        Row("link", "unsearchable+link_at_name", Raises(StorageError, "a/p/t", "EACCES")),
        Row("link", "read_only+link_at_part_name", Raises(SymlinkInLake, "a/p/.part")),
        Row("link", "link_at_part_name+source_missing", Raises(SourceGone, "up/src")),
        Row("link", "unsearchable+link_at_part_name", Raises(StorageError, "a/p/t", "EACCES")),
        Row("link", "read_only+missing", Raises(StorageError, "a/p/t", "EACCES")),
        Row("link", "missing+source_missing", Raises(SourceGone, "up/src")),
        Row("link", "unsearchable+missing", Raises(StorageError, "a/p/t", "EACCES")),
        Row("link source", "read_only+dir_at_name", Raises(SourceGone, "a/p/t")),
        Row("link source", "read_only+link_at_name", Raises(SymlinkInLake, "a/p/t")),
        Row("link source", "unsearchable+link_at_name", Raises(StorageError, "a/p/t", "EACCES")),
        Row("link source", "read_only+missing", Raises(SourceGone, "a/p/t")),
        Row("link source", "unsearchable+missing", Raises(StorageError, "a/p/t", "EACCES")),
        Row("rename", "dir_at_name+source_missing", Raises(StorageError, "up/src", "ENOENT")),
        Row("rename", "file_above+source_missing", Raises(StorageError, "up/src", "ENOENT")),
        Row("rename", "file_at_name+source_missing", Raises(StorageError, "up/src", "ENOENT")),
        Row("rename", "unsearchable+file_at_name", Raises(StorageError, "a/p/t", "EACCES")),
        Row("rename", "link_above+source_missing", Raises(StorageError, "up/src", "ENOENT")),
        Row("rename", "read_only+link_at_name", Raises(SymlinkInLake, "a/p/t")),
        Row("rename", "link_at_name+source_missing", Raises(StorageError, "up/src", "ENOENT")),
        Row("rename", "unsearchable+link_at_name", Raises(StorageError, "a/p/t", "EACCES")),
        Row("rename", "read_only+missing", Raises(StorageError, "a/p/t", "EACCES")),
        Row("rename", "missing+source_missing", Raises(StorageError, "up/src", "ENOENT")),
        Row("rename", "unsearchable+missing", Raises(StorageError, "a/p/t", "EACCES")),
        Row("rename", "read_only+same_file_at_name", Returns(None)),
        Row("rename", "same_file_at_name+source_missing", Raises(StorageError, "up/src", "ENOENT")),
        Row("rename", "unsearchable+same_file_at_name", Raises(StorageError, "a/p/t", "EACCES")),
        Row("rename", "unsearchable+source_missing", Raises(StorageError, "up/src", "ENOENT")),
        Row("rename source", "read_only+link_at_name", Raises(SymlinkInLake, "a/p/t")),
        Row("rename source", "unsearchable+link_at_name", Raises(StorageError, "a/p/t", "EACCES")),
        Row("rename source", "read_only+missing", Raises(StorageError, "a/p/t", "ENOENT")),
        Row("rename source", "unsearchable+missing", Raises(StorageError, "a/p/t", "EACCES")),
        Row("remove_file", "read_only+link_at_name", Raises(SymlinkInLake, "a/p/t")),
        Row("remove_file", "unsearchable+link_at_name", Raises(StorageError, "a/p/t", "EACCES")),
        Row("remove_file", "read_only+missing", Returns(Outcome.MISSING)),
        Row("remove_file", "unsearchable+missing", Raises(StorageError, "a/p/t", "EACCES")),
        Row("remove_directory", "read_only+link_at_name", Raises(SymlinkInLake, "a/p/t")),
        Row(
            "remove_directory", "unsearchable+link_at_name", Raises(StorageError, "a/p/t", "EACCES")
        ),
        Row("remove_directory", "read_only+missing", Returns(Outcome.MISSING)),
        Row("remove_directory", "unsearchable+missing", Raises(StorageError, "a/p/t", "EACCES")),
        Row(
            "remove_directory", "unsearchable+nonempty_dir", Raises(StorageError, "a/p/t", "EACCES")
        ),
    ]
    return rows


ROWS = table_rows()
ROW_COUNT = 388


def test_the_table_has_one_row_per_method_and_case() -> None:
    keys = [(row.method, row.case) for row in ROWS]
    assert len(keys) == len(set(keys)) == ROW_COUNT
    assert {row.method for row in ROWS} == set(METHODS)
    assert {part for row in ROWS for part in row.case.split("+")} == set(SETUPS)


@pytest.mark.parametrize("method", sorted(METHODS))
def test_each_part_of_a_combined_row_has_its_own_row(method: str) -> None:
    rows = [row.case for row in ROWS if row.method == method]
    parts = {part for case in rows for part in case.split("+")}
    assert parts == {case for case in rows if "+" not in case}


@pytest.mark.parametrize("method", sorted(METHODS))
def test_each_pair_of_cases_that_can_hold_at_once_has_one_row(method: str) -> None:
    combined = [row.case.split("+") for row in ROWS if row.method == method and "+" in row.case]
    assert all(len(parts) == 2 for parts in combined)
    assert {frozenset(parts) for parts in combined} == arrangeable_pairs(method)


@pytest.mark.parametrize("row", ROWS, ids=[f"{row.method}-{row.case}" for row in ROWS])
def test_each_port_method_answers_each_case_as_the_table_says(lake: Lake, row: Row) -> None:
    kind, call = METHODS[row.method]
    at = arrange(lake, row.case, kind)
    before = lake.state()
    expected = row.result
    if isinstance(expected, Returns):
        assert call(lake.storage, at) == expected.value
    else:
        with pytest.raises(StorageError) as raised:
            call(lake.storage, at)
        assert _public_class(raised.value) is expected.error
        assert raised.value.context["path"] == expected.path
        assert raised.value.message == expected.message()
        if not row.after:
            assert lake.state() == before
    for location, after in row.after.items():
        assert lake.kind(location) == after


def test_walk_yields_a_link_and_never_enters_it(lake: Lake) -> None:
    plant_symlink(lake.storage, NAME)
    before = lake.state()
    entries = list(lake.storage.walk(LakePath.of("a")))
    assert [(e.names, e.kind) for e in entries] == [(("t",), "symlink")]
    assert lake.storage.is_empty(LakePath.of("a")) is False
    assert lake.state() == before


@pytest.mark.parametrize("field", ["part_name", "backup_name"])
@pytest.mark.parametrize("name", ["../../outside/escaped", "x/y", "..", ""])
def test_link_refuses_a_part_or_backup_name_that_is_not_one_name(
    lake: Lake, field: str, name: str
) -> None:
    names = {"part_name": ".part", "backup_name": ".prev", field: name}
    inode = source_inode(lake.storage)
    before = lake.state()
    with pytest.raises(HuronError) as refused:
        lake.storage.link(SOURCE, LakePath.of("a", "c.bin"), inode=inode, **names)
    assert (refused.value.code, refused.value.status) == ("NAME_INVALID", 422)
    assert lake.state() == before


def _public_class(error: StorageError) -> type[StorageError]:
    """The most specific public storage error class of ``error``."""
    for public in (
        SymlinkInLake,
        SourceGone,
        SourceSizeMismatch,
        InheritanceFailed,
        LakeUnavailable,
    ):
        if isinstance(error, public):
            return public
    return StorageError
