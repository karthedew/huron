"""Layout, modes, the marker and the storage port on both adapters."""

import errno
import grp
import hashlib
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from huron.core.storage import (
    DIRECTORY_MODE,
    FILE_MODE,
    MARKER_FILE,
    ORGANIZATION_MODE,
    UPLOAD_DIR_MODE,
    GroupOutcome,
    GroupResult,
    LakePath,
    Marker,
    Outcome,
    SourceGone,
    Stat,
    Storage,
    StorageError,
    is_reserved_entry,
    read_marker,
    render_marker,
    verify_marker,
)
from huron.core.storage.memory import MemoryStorage, Node
from huron.core.storage.posix import PosixStorage
from tests.support.disk import LAKE

BASE = LakePath.of("share")
PART = ".a.bin.1.huron-part"
BACKUP = ".a.bin.1.huron-prev"


def at(*names: str) -> LakePath:
    """A lake path below :data:`BASE`."""
    return BASE.joinpath(*names)


def test_reserved_entries() -> None:
    assert is_reserved_entry("metadata.json")
    assert is_reserved_entry("x/a.bin.huron-part")
    assert is_reserved_entry("x/.a.bin.0192.huron-prev")
    assert is_reserved_entry(".huron")
    assert not is_reserved_entry("sub/metadata.json")


def test_files_and_the_upload_directory_have_their_modes() -> None:
    assert (ORGANIZATION_MODE, DIRECTORY_MODE) == (0o2751, 0o2750)
    assert (FILE_MODE, UPLOAD_DIR_MODE) == (0o644, 0o700)


def test_marker_round_trip_and_refusals() -> None:
    storage = MemoryStorage(LAKE)
    with pytest.raises(StorageError, match="the root is not a Huron share"):
        read_marker(storage, LakePath())
    with pytest.raises(StorageError, match="missing is not mounted"):
        read_marker(storage, LakePath.of("missing"))
    storage.write_bytes(LakePath.of(MARKER_FILE), b"{not json", 0o644)
    with pytest.raises(StorageError, match="unreadable"):
        read_marker(storage, LakePath())
    marker = render_marker(Marker(1, "http://a", "id-1"))
    storage.write_bytes(LakePath.of(MARKER_FILE), marker, 0o644)
    assert verify_marker(storage, LakePath(), "id-1").api_url == "http://a"
    with pytest.raises(StorageError, match="another Huron service") as refused:
        verify_marker(storage, LakePath(), "id-2")
    assert refused.value.context["path"] == ""


@pytest.fixture(params=["posix", "memory"])
def share(request: pytest.FixtureRequest, tmp_path: Path) -> Storage:
    """Each adapter with the setgid directory ``share`` of the caller's group to work in."""
    if request.param == "posix":
        (tmp_path / "lake" / "share").mkdir(parents=True)
        os.chmod(tmp_path / "lake" / "share", 0o2750)
        return PosixStorage(tmp_path / "lake")
    memory = MemoryStorage(LAKE, uid=1000, gid=1000)
    memory.nodes[BASE] = Node(mode=0o2750, uid=1000, gid=1000, inode=99)
    return memory


def found(storage: Storage, location: LakePath) -> Stat:
    entry = storage.stat(location)
    assert entry is not None
    return entry


def test_stat_of_a_file_a_directory_and_a_missing_name(share: Storage) -> None:
    share.write_bytes(at("f"), b"abc", 0o640)
    file = found(share, at("f"))
    assert (file.kind, file.mode, file.size) == ("file", 0o640, 3)
    assert found(share, BASE).kind == "dir"
    assert found(share, BASE).mode == 0o2750
    assert found(share, LakePath()).kind == "dir"
    assert share.stat(at("missing")) is None
    assert share.stat(at("missing", "deeper")) is None


def test_read_bytes(share: Storage) -> None:
    share.write_bytes(at("f"), b"abc", 0o644)
    assert share.read_bytes(at("f")) == b"abc"
    assert share.read_bytes(at("missing")) is None
    assert share.read_bytes(at("missing", "f")) is None
    with pytest.raises(StorageError, match="share: Is a directory"):
        share.read_bytes(BASE)
    with pytest.raises(StorageError, match="share: Is a directory"):
        share.open_file(BASE)


def test_is_empty(share: Storage) -> None:
    share.make_directory(at("d"), DIRECTORY_MODE)
    assert share.is_empty(at("d")) is True
    share.write_bytes(at("d", "f"), b"", 0o644)
    assert share.is_empty(at("d")) is False
    with pytest.raises(StorageError):
        share.is_empty(at("d", "f"))
    with pytest.raises(StorageError, match="does not exist"):
        share.is_empty(at("missing"))


def test_walk_is_top_down_and_sorted(share: Storage) -> None:
    share.make_directory(at("b"), DIRECTORY_MODE)
    share.write_bytes(at("b", "c.txt"), b"12345", 0o644)
    share.write_bytes(at("a.txt"), b"1", 0o644)
    entries = list(share.walk(BASE))
    assert [(e.names, e.kind) for e in entries] == [
        (("a.txt",), "file"),
        (("b",), "dir"),
        (("b", "c.txt"), "file"),
    ]
    assert entries[2].size == 5
    with pytest.raises(StorageError):
        list(share.walk(at("missing")))


def test_make_directory_gives_exactly_the_mode_and_keeps_an_existing_one(share: Storage) -> None:
    assert share.make_directory(at("helio"), 0o2751) is True
    assert found(share, at("helio")).mode == 0o2751
    share.set_mode(at("helio"), 0o755)
    assert share.make_directory(at("helio"), ORGANIZATION_MODE) is False
    assert found(share, at("helio")).mode == 0o755


def test_make_directory_refusals(share: Storage) -> None:
    share.write_bytes(at("file"), b"", 0o644)
    with pytest.raises(StorageError, match="File exists"):
        share.make_directory(at("file"), DIRECTORY_MODE)
    with pytest.raises(StorageError, match="does not exist"):
        share.make_directory(at("missing", "d"), DIRECTORY_MODE)
    with pytest.raises(StorageError, match="Not a directory"):
        share.make_directory(at("file", "d"), DIRECTORY_MODE)


def test_make_inheriting_dir_inherits_setgid_and_the_group(share: Storage) -> None:
    assert share.make_inheriting_dir(at("run7")) is True
    made = found(share, at("run7"))
    assert (made.mode, made.gid) == (DIRECTORY_MODE, found(share, BASE).gid)
    assert share.make_inheriting_dir(at("run7")) is False


def test_make_inheriting_dir_refusals(share: Storage) -> None:
    share.write_bytes(at("file"), b"", 0o644)
    with pytest.raises(StorageError, match="File exists"):
        share.make_inheriting_dir(at("file"))
    share.make_directory(at("plain"), 0o750)
    with pytest.raises(StorageError, match="did not inherit the setgid bit"):
        share.make_inheriting_dir(at("plain", "d"))
    assert share.stat(at("plain", "d")) is None
    with pytest.raises(StorageError, match="does not exist"):
        share.make_inheriting_dir(at("missing", "d"))


def test_set_mode_changes_only_a_different_mode(share: Storage) -> None:
    share.write_bytes(at("f"), b"", 0o600)
    assert share.set_mode(at("f"), FILE_MODE) is True
    assert found(share, at("f")).mode == FILE_MODE
    assert share.set_mode(at("f"), FILE_MODE) is False
    with pytest.raises(StorageError, match="does not exist"):
        share.set_mode(at("missing"), FILE_MODE)


def test_write_bytes_replaces_a_file_with_exactly_the_mode(share: Storage) -> None:
    share.write_bytes(at("m.json"), b"{}", 0o600)
    share.write_bytes(at("m.json"), b'{"a":1}', 0o640)
    assert share.read_bytes(at("m.json")) == b'{"a":1}'
    assert found(share, at("m.json")).mode == 0o640
    assert [e.names for e in share.walk(BASE)] == [("m.json",)]
    with pytest.raises(StorageError, match="does not exist"):
        share.write_bytes(at("missing", "m"), b"", 0o644)
    with pytest.raises(StorageError, match="Is a directory"):
        share.write_bytes(BASE, b"", 0o644)


def test_an_open_file_reports_from_its_descriptor(share: Storage) -> None:
    share.write_bytes(at("upload"), b"payload", 0o600)
    opened = share.open_file(at("upload"))
    assert opened is not None
    try:
        assert (opened.size, opened.inode) == (7, found(share, at("upload")).inode)
        assert opened.sha256() == hashlib.sha256(b"payload").hexdigest()
        opened.set_mode(FILE_MODE)
    finally:
        opened.close()
    assert found(share, at("upload")).mode == FILE_MODE
    assert share.open_file(at("missing")) is None
    assert share.open_file(at("missing", "f")) is None


def place(share: Storage, inode: int | None = None) -> LakePath | None:
    measured = found(share, at("upload")).inode if inode is None else inode
    return share.link(at("upload"), at("a.bin"), inode=measured, part_name=PART, backup_name=BACKUP)


def test_link_gives_a_file_a_new_name(share: Storage) -> None:
    share.write_bytes(at("upload"), b"new", 0o644)
    assert place(share) is None
    assert found(share, at("a.bin")).inode == found(share, at("upload")).inode
    assert share.read_bytes(at("a.bin")) == b"new"
    assert place(share) is None
    assert share.stat(at(BACKUP)) is None


@pytest.mark.parametrize("stale", [False, True], ids=["fresh", "stale"])
def test_link_replaces_an_existing_file_and_keeps_a_backup(share: Storage, stale: bool) -> None:
    share.write_bytes(at("upload"), b"new", 0o644)
    share.write_bytes(at("a.bin"), b"old", 0o644)
    old_inode = found(share, at("a.bin")).inode
    if stale:
        share.write_bytes(at(PART), b"stale", 0o644)
        share.write_bytes(at(BACKUP), b"stale", 0o644)
    assert place(share) == at(BACKUP)
    assert share.read_bytes(at("a.bin")) == b"new"
    assert found(share, at("a.bin")).inode == found(share, at("upload")).inode
    assert (share.read_bytes(at(BACKUP)), found(share, at(BACKUP)).inode) == (b"old", old_inode)
    assert share.stat(at(PART)) is None
    assert place(share) == at(BACKUP)


def test_link_without_the_measured_source_raises_source_gone(share: Storage) -> None:
    share.write_bytes(at("upload"), b"new", 0o644)
    with pytest.raises(SourceGone):
        place(share, inode=found(share, at("upload")).inode + 1)
    share.remove_file(at("upload"))
    with pytest.raises(SourceGone):
        place(share, inode=1)
    share.make_directory(at("upload"), DIRECTORY_MODE)
    with pytest.raises(SourceGone):
        place(share, inode=found(share, at("upload")).inode)
    assert share.stat(at("a.bin")) is None


def test_link_into_a_missing_directory_fails(share: Storage) -> None:
    share.write_bytes(at("upload"), b"new", 0o644)
    inode = found(share, at("upload")).inode
    with pytest.raises(StorageError, match="does not exist"):
        share.link(
            at("upload"), at("missing", "a.bin"), inode=inode, part_name=PART, backup_name=BACKUP
        )


def test_rename_replaces_the_destination(share: Storage) -> None:
    share.write_bytes(at(BACKUP), b"old", 0o644)
    share.write_bytes(at("a.bin"), b"new", 0o644)
    inode = found(share, at(BACKUP)).inode
    share.rename(at(BACKUP), at("a.bin"))
    assert (share.read_bytes(at("a.bin")), found(share, at("a.bin")).inode) == (b"old", inode)
    assert share.stat(at(BACKUP)) is None
    with pytest.raises(StorageError):
        share.rename(at(BACKUP), at("a.bin"))


def test_remove_file_answers_its_outcome(share: Storage) -> None:
    share.write_bytes(at("f"), b"", 0o644)
    inode = found(share, at("f")).inode
    assert share.remove_file(at("f"), inode=inode + 1) is Outcome.KEPT
    assert share.remove_file(at("f"), inode=inode) is Outcome.REMOVED
    assert share.remove_file(at("f")) is Outcome.MISSING
    assert share.remove_file(at("missing", "f")) is Outcome.MISSING
    share.write_bytes(at("g"), b"", 0o644)
    assert share.remove_file(at("g")) is Outcome.REMOVED
    with pytest.raises(StorageError, match="Is a directory"):
        share.remove_file(BASE)


def test_remove_directory_answers_its_outcome(share: Storage) -> None:
    share.make_directory(at("d"), DIRECTORY_MODE)
    share.write_bytes(at("d", "f"), b"", 0o644)
    assert share.remove_directory(at("d")) is Outcome.KEPT
    share.remove_file(at("d", "f"))
    assert share.remove_directory(at("d")) is Outcome.REMOVED
    assert share.remove_directory(at("d")) is Outcome.MISSING
    assert share.remove_directory(at("missing", "d")) is Outcome.MISSING
    share.write_bytes(at("f"), b"", 0o644)
    with pytest.raises(StorageError, match="Not a directory"):
        share.remove_directory(at("f"))


def test_rename_of_a_missing_file_names_it(share: Storage) -> None:
    with pytest.raises(StorageError, match="share/gone does not exist"):
        share.rename(at("gone"), at("a.bin"))


@pytest.fixture
def lake(tmp_path: Path) -> PosixStorage:
    """POSIX storage over ``tmp_path/lake``, which holds the setgid directory ``share``."""
    (tmp_path / "lake" / "share").mkdir(parents=True)
    os.chmod(tmp_path / "lake" / "share", 0o2750)
    return PosixStorage(tmp_path / "lake")


def test_posix_root_that_does_not_open_is_lake_unavailable(tmp_path: Path) -> None:
    missing = PosixStorage(tmp_path / "missing")
    assert missing.root == tmp_path / "missing"
    with pytest.raises(StorageError) as refused:
        missing.stat(at("x"))
    assert (refused.value.code, refused.value.status) == ("LAKE_UNAVAILABLE", 503)
    assert str(tmp_path) not in refused.value.message


def test_posix_permission_errors_are_storage_errors(lake: PosixStorage) -> None:
    lake.make_directory(at("closed"), DIRECTORY_MODE)
    lake.write_bytes(at("closed", "f"), b"x", 0o644)
    os.chmod(lake.root / "share" / "closed", 0)
    try:
        with pytest.raises(StorageError, match="permission denied on share/closed/f") as refused:
            lake.read_bytes(at("closed", "f"))
        assert refused.value.context == {"path": "share/closed/f", "error": "Permission denied"}
        with pytest.raises(StorageError, match="permission denied"):
            list(lake.walk(at("closed")))
    finally:
        os.chmod(lake.root / "share" / "closed", 0o750)


def test_posix_walk_refuses_a_directory_below_that_it_cannot_list(lake: PosixStorage) -> None:
    lake.make_directory(at("open"), DIRECTORY_MODE)
    lake.make_directory(at("open", "closed"), DIRECTORY_MODE)
    os.chmod(lake.root / "share" / "open" / "closed", 0)
    try:
        with pytest.raises(StorageError, match="permission denied on share/open") as refused:
            list(lake.walk(at("open")))
        assert refused.value.code == "STORAGE_FAILED"
    finally:
        os.chmod(lake.root / "share" / "open" / "closed", 0o750)


def test_posix_other_errors_keep_their_reason(
    lake: PosixStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    lake.write_bytes(at("upload"), b"new", 0o644)
    opened: list[int] = []
    real_open, real_fstat = os.open, os.fstat

    def recording_open(path: str, flags: int, *args: int, dir_fd: int | None = None) -> int:
        opened.append(real_open(path, flags, *args, dir_fd=dir_fd))
        return opened[-1]

    def failing_fstat(descriptor: int) -> os.stat_result:
        if descriptor == opened[-1]:
            raise OSError(errno.EIO, "Input/output error")
        return real_fstat(descriptor)

    monkeypatch.setattr(os, "open", recording_open)
    monkeypatch.setattr(os, "fstat", failing_fstat)
    with pytest.raises(StorageError, match="share/upload: Input/output error"):
        lake.open_file(at("upload"))
    monkeypatch.undo()
    with pytest.raises(OSError, match="Bad file descriptor"):
        real_fstat(opened[-1])  # the failed open released its descriptor


def test_posix_set_group_keeps_a_matching_group(lake: PosixStorage) -> None:
    name = grp.getgrgid(os.lstat(lake.root / "share").st_gid).gr_name
    assert lake.set_group(BASE, name) == GroupResult(GroupOutcome.UNCHANGED)


def test_posix_set_group_is_pending_for_an_unknown_group(lake: PosixStorage) -> None:
    assert lake.set_group(BASE, "no-such-group-xyz") == GroupResult(
        GroupOutcome.PENDING, "this machine does not know the group no-such-group-xyz"
    )


@pytest.mark.parametrize("by_name", [True, False])
def test_posix_set_group_changes_the_group(
    lake: PosixStorage, monkeypatch: pytest.MonkeyPatch, by_name: bool
) -> None:
    other = os.lstat(lake.root / "share").st_gid + 1
    calls: list[tuple[int, int]] = []
    monkeypatch.setattr(grp, "getgrnam", lambda name: SimpleNamespace(gr_gid=other))
    monkeypatch.setattr(os, "fchown", lambda fd, uid, gid: calls.append((uid, gid)))
    group = "helio-readers" if by_name else other
    assert lake.set_group(BASE, group) == GroupResult(GroupOutcome.CHANGED)
    assert calls == [(-1, other)]


def test_posix_set_group_is_pending_when_refused_or_missing(
    lake: PosixStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(grp, "getgrnam", lambda name: SimpleNamespace(gr_gid=os.getgid() + 1))
    for missing in (at("missing"), at("missing", "deeper")):
        result = lake.set_group(missing, "helio-readers")
        assert result.outcome is GroupOutcome.PENDING
        assert result.reason == f"{missing} does not exist"

    def refuse(*args: object, **kwargs: object) -> None:
        raise PermissionError(errno.EPERM, "Operation not permitted")

    monkeypatch.setattr(os, "fchown", refuse)
    assert lake.set_group(BASE, "helio-readers") == GroupResult(
        GroupOutcome.PENDING, "share: Operation not permitted"
    )


def test_posix_a_file_on_the_way_is_not_a_link(lake: PosixStorage) -> None:
    lake.write_bytes(at("f"), b"", 0o644)
    with pytest.raises(StorageError, match="Not a directory") as refused:
        lake.stat(at("f", "x"))
    assert refused.value.code == "STORAGE_FAILED"


@pytest.fixture
def memory() -> MemoryStorage:
    """An in-memory lake whose root is a setgid directory of root's group (gid 0)."""
    return MemoryStorage(LAKE, uid=1000, gid=1000)


def test_memory_add_directory_makes_the_missing_parents(memory: MemoryStorage) -> None:
    memory.add_directory(LakePath.of("data1", "huron"), uid=7)
    assert (memory.nodes[LakePath.of("data1")].uid, found(memory, LakePath.of("data1")).kind) == (
        7,
        "dir",
    )
    assert memory.root == LAKE


def test_memory_make_directory_inherits_the_group_of_a_setgid_parent(
    memory: MemoryStorage,
) -> None:
    memory.member_of.add(0)
    assert memory.make_directory(LakePath.of("helio"), ORGANIZATION_MODE) is True
    made = found(memory, LakePath.of("helio"))
    assert (made.gid, made.mode) == (0, 0o2751)
    assert memory.calls == [("mkdir", LakePath.of("helio"))]


def test_memory_make_directory_drops_setgid_outside_the_callers_groups(
    memory: MemoryStorage,
) -> None:
    memory.make_directory(LakePath.of("helio"), ORGANIZATION_MODE)
    assert found(memory, LakePath.of("helio")).mode == 0o751
    memory.nodes[LakePath.of("plain")] = Node(mode=0o755, uid=1000, gid=1000)
    memory.make_directory(LakePath.of("plain", "d"), DIRECTORY_MODE)
    made = found(memory, LakePath.of("plain", "d"))
    assert (made.gid, made.mode) == (1000, 0o2750)


def test_memory_denied_and_unreadable_directories_refuse(memory: MemoryStorage) -> None:
    memory.make_directory(LakePath.of("d"), DIRECTORY_MODE)
    memory.write_bytes(LakePath.of("upload"), b"new", 0o644)
    inode = found(memory, LakePath.of("upload")).inode
    memory.denied.add(LakePath())
    for refused in (
        lambda: memory.make_directory(LakePath.of("e"), DIRECTORY_MODE),
        lambda: memory.make_inheriting_dir(LakePath.of("e")),
        lambda: memory.write_bytes(LakePath.of("f"), b"", 0o644),
        lambda: memory.link(
            LakePath.of("upload"),
            LakePath.of("a.bin"),
            inode=inode,
            part_name=PART,
            backup_name=BACKUP,
        ),
        lambda: memory.rename(LakePath.of("upload"), LakePath.of("a.bin")),
        lambda: memory.remove_file(LakePath.of("upload")),
        lambda: memory.remove_directory(LakePath.of("d")),
    ):
        with pytest.raises(StorageError, match="permission denied"):
            refused()
    memory.denied.clear()
    memory.unreadable.add(LakePath.of("d"))
    with pytest.raises(StorageError, match="permission denied on d") as unreadable:
        memory.stat(LakePath.of("d", "x"))
    assert unreadable.value.context["error"] == os.strerror(errno.EACCES)
    with pytest.raises(StorageError, match="permission denied"):
        memory.is_empty(LakePath.of("d"))


def test_memory_walk_refuses_an_unreadable_directory_below(memory: MemoryStorage) -> None:
    memory.make_directory(LakePath.of("d"), DIRECTORY_MODE)
    memory.make_directory(LakePath.of("d", "e"), DIRECTORY_MODE)
    memory.unreadable.add(LakePath.of("d", "e"))
    with pytest.raises(StorageError, match="permission denied on d/e"):
        list(memory.walk(LakePath.of("d")))


def test_memory_set_mode_needs_the_owner(memory: MemoryStorage) -> None:
    memory.member_of.add(0)
    memory.make_directory(LakePath.of("d"), 0o750)
    memory.member_of.discard(0)
    assert memory.set_mode(LakePath.of("d"), DIRECTORY_MODE) is True
    assert found(memory, LakePath.of("d")).mode == 0o750
    with pytest.raises(StorageError, match="permission denied"):
        memory.set_mode(LakePath(), 0o755)


def test_memory_set_group_outcomes(memory: MemoryStorage) -> None:
    memory.groups.update({"helio-readers": 2001, "geo-readers": 2002})
    memory.member_of.add(2001)
    target = LakePath.of("cat")
    memory.make_directory(target, DIRECTORY_MODE)
    assert memory.set_group(target, "unknown") == GroupResult.unknown("unknown")
    assert memory.set_group(LakePath.of("missing"), "helio-readers") == GroupResult(
        GroupOutcome.PENDING, "missing does not exist"
    )
    assert memory.set_group(target, "geo-readers") == GroupResult(
        GroupOutcome.PENDING, f"cat: {os.strerror(errno.EPERM)}"
    )
    assert memory.set_group(target, "helio-readers") == GroupResult(GroupOutcome.CHANGED)
    assert found(memory, target).gid == 2001
    assert memory.set_group(target, "helio-readers") == GroupResult(GroupOutcome.UNCHANGED)
    assert memory.set_group(LakePath(), "helio-readers").outcome is GroupOutcome.PENDING
    assert memory.set_group(target, 1000) == GroupResult(GroupOutcome.CHANGED)


def test_memory_write_bytes_gives_a_file_the_group_of_a_setgid_parent(
    memory: MemoryStorage,
) -> None:
    memory.write_bytes(LakePath.of("inherited"), b"", 0o644)
    assert found(memory, LakePath.of("inherited")).gid == 0
    memory.nodes[LakePath.of("plain")] = Node(mode=0o755, uid=1000, gid=2001)
    memory.write_bytes(LakePath.of("plain", "own"), b"", 0o644)
    assert found(memory, LakePath.of("plain", "own")).gid == 1000
    assert memory.calls[-1] == ("write", LakePath.of("plain", "own"))


def test_memory_open_file_refuses_a_directory_and_a_foreign_file(memory: MemoryStorage) -> None:
    with pytest.raises(StorageError, match="Is a directory"):
        memory.open_file(LakePath())
    memory.nodes[LakePath.of("theirs")] = Node("file", 0o600, 0, 0)
    opened = memory.open_file(LakePath.of("theirs"))
    assert opened is not None
    with pytest.raises(StorageError, match="permission denied"):
        opened.set_mode(FILE_MODE)


def test_memory_without_inheritance_refuses_new_directories(memory: MemoryStorage) -> None:
    memory.inherits = False
    with pytest.raises(StorageError, match="did not inherit"):
        memory.make_inheriting_dir(LakePath.of("d"))
    assert memory.stat(LakePath.of("d")) is None


def test_memory_symlink_needs_its_parent(memory: MemoryStorage) -> None:
    with pytest.raises(StorageError, match="does not exist"):
        memory.symlink(LakePath.of("missing", "link"), "/outside")
