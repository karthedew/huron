"""Layout, modes, the marker and the storage port on both adapters."""

import errno
import grp
import hashlib
import os
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest

from huron.core.storage import (
    DIRECTORY_MODE,
    FILE_MODE,
    MARKER_FILE,
    ORGANIZATION_MODE,
    UPLOAD_DIR_MODE,
    FreeSpace,
    GroupOutcome,
    GroupResult,
    InheritanceFailed,
    LakePath,
    Marker,
    Outcome,
    SealedFile,
    SourceSizeMismatch,
    Stat,
    Storage,
    StorageError,
    is_reserved_entry,
    read_marker,
    render_marker,
    verify_marker,
)
from huron.core.storage.memory import FREE_BYTES, MemoryStorage, Node
from huron.core.storage.posix import PosixStorage
from tests.support.disk import LAKE, inject_fault

BASE = LakePath.of("share")
OLD = "old.bin"


def at(*names: str) -> LakePath:
    """A lake path below :data:`BASE`."""
    return BASE.joinpath(*names)


def test_reserved_entries() -> None:
    assert is_reserved_entry("metadata.json")
    assert is_reserved_entry("x/a.bin.huron-part")
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


def test_read_bytes(share: Storage) -> None:
    share.write_bytes(at("f"), b"abc", 0o644)
    assert share.read_bytes(at("f")) == b"abc"


def test_is_empty(share: Storage) -> None:
    share.make_directory(at("d"), DIRECTORY_MODE)
    assert share.is_empty(at("d")) is True
    share.write_bytes(at("d", "f"), b"", 0o644)
    assert share.is_empty(at("d")) is False


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


def test_make_directory_gives_exactly_the_mode_and_keeps_an_existing_one(share: Storage) -> None:
    assert share.make_directory(at("helio"), 0o2751) is True
    assert found(share, at("helio")).mode == 0o2751
    share.set_mode(at("helio"), 0o755)
    assert share.make_directory(at("helio"), ORGANIZATION_MODE) is False
    assert found(share, at("helio")).mode == 0o755


def test_make_inheriting_dir_inherits_setgid_and_the_group(share: Storage) -> None:
    assert share.make_inheriting_dir(at("run7")) is True
    made = found(share, at("run7"))
    assert (made.mode, made.gid) == (DIRECTORY_MODE, found(share, BASE).gid)
    assert share.make_inheriting_dir(at("run7")) is False


def test_make_inheriting_dir_refuses_a_mode_that_the_umask_cut(share: Storage) -> None:
    if isinstance(share, PosixStorage):
        os.umask(0o077)
    else:
        assert isinstance(share, MemoryStorage)
        share.umask = 0o077
    with pytest.raises(InheritanceFailed) as refused:
        share.make_inheriting_dir(at("d"))
    assert refused.value.message == "share/d: the directory has the mode 2700, not 2750"
    assert refused.value.context == {"path": "share/d"}
    assert share.stat(at("d")) is None


def test_make_inheriting_dir_refuses_a_parent_without_the_setgid_bit(share: Storage) -> None:
    share.make_directory(at("plain"), 0o750)
    with pytest.raises(InheritanceFailed) as refused:
        share.make_inheriting_dir(at("plain", "d"))
    gid = found(share, at("plain")).gid
    assert refused.value.message == (
        f"share/plain/d: the directory did not inherit the setgid bit and the group {gid}"
    )
    assert refused.value.context == {"path": "share/plain/d"}
    assert share.stat(at("plain", "d")) is None


def test_set_mode_changes_only_a_different_mode(share: Storage) -> None:
    share.write_bytes(at("f"), b"", 0o600)
    assert share.set_mode(at("f"), FILE_MODE) is True
    assert found(share, at("f")).mode == FILE_MODE
    assert share.set_mode(at("f"), FILE_MODE) is False


def test_mode_and_group_change_on_a_directory_this_process_cannot_read(
    share: Storage, temporary_mode: Callable[[Path, int], None]
) -> None:
    share.make_directory(at("closed"), DIRECTORY_MODE)
    if isinstance(share, PosixStorage):
        temporary_mode(share.root / "share" / "closed", 0o2000)
    else:
        assert isinstance(share, MemoryStorage)
        share.nodes[at("closed")].mode = 0o2000
        share.unreadable.add(at("closed"))
    gid = found(share, at("closed")).gid
    assert share.set_group(at("closed"), gid) == GroupResult(GroupOutcome.UNCHANGED)
    assert share.set_mode(at("closed"), DIRECTORY_MODE) is True
    assert found(share, at("closed")).mode == DIRECTORY_MODE


def test_a_directory_this_process_cannot_list_is_named_by_walk_and_is_empty(
    share: Storage, temporary_mode: Callable[[Path, int], None]
) -> None:
    share.make_directory(at("closed"), DIRECTORY_MODE)
    if isinstance(share, PosixStorage):
        temporary_mode(share.root / "share" / "closed", 0o000)
    else:
        assert isinstance(share, MemoryStorage)
        share.unreadable.add(at("closed"))
    for refused in (lambda: list(share.walk(at("closed"))), lambda: share.is_empty(at("closed"))):
        with pytest.raises(StorageError) as raised:
            refused()
        assert (raised.value.message, raised.value.context["path"]) == (
            "permission denied on share/closed",
            "share/closed",
        )


def test_write_bytes_replaces_a_file_with_exactly_the_mode(share: Storage) -> None:
    share.write_bytes(at("m.json"), b"{}", 0o600)
    share.write_bytes(at("m.json"), b'{"a":1}', 0o640)
    assert share.read_bytes(at("m.json")) == b'{"a":1}'
    assert found(share, at("m.json")).mode == 0o640
    assert [e.names for e in share.walk(BASE)] == [("m.json",)]


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


def test_rename_replaces_the_destination(share: Storage) -> None:
    share.write_bytes(at(OLD), b"old", 0o644)
    share.write_bytes(at("a.bin"), b"new", 0o644)
    inode = found(share, at(OLD)).inode
    share.rename(at(OLD), at("a.bin"))
    assert (share.read_bytes(at("a.bin")), found(share, at("a.bin")).inode) == (b"old", inode)
    assert share.stat(at(OLD)) is None


def test_remove_file_answers_its_outcome(share: Storage) -> None:
    share.write_bytes(at("f"), b"", 0o644)
    inode = found(share, at("f")).inode
    assert share.remove_file(at("f"), inode=inode + 1) is Outcome.KEPT
    assert share.remove_file(at("f"), inode=inode) is Outcome.REMOVED
    assert share.remove_file(at("f")) is Outcome.MISSING
    share.write_bytes(at("g"), b"", 0o644)
    assert share.remove_file(at("g")) is Outcome.REMOVED


def test_remove_directory_answers_its_outcome(share: Storage) -> None:
    share.make_directory(at("d"), DIRECTORY_MODE)
    share.write_bytes(at("d", "f"), b"", 0o644)
    assert share.remove_directory(at("d")) is Outcome.KEPT
    share.remove_file(at("d", "f"))
    assert share.remove_directory(at("d")) is Outcome.REMOVED
    assert share.remove_directory(at("d")) is Outcome.MISSING


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
    calls: list[tuple[str, int, int]] = []

    def chown(path: str, uid: int, gid: int, *, dir_fd: int, follow_symlinks: bool) -> None:
        assert follow_symlinks is False
        calls.append((path, uid, gid))

    monkeypatch.setattr(grp, "getgrnam", lambda name: SimpleNamespace(gr_gid=other))
    monkeypatch.setattr(os, "chown", chown)
    group = "helio-readers" if by_name else other
    assert lake.set_group(BASE, group) == GroupResult(GroupOutcome.CHANGED)
    assert calls == [("share", -1, other)]


def test_posix_set_group_is_pending_when_the_chown_is_refused(
    lake: PosixStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(grp, "getgrnam", lambda name: SimpleNamespace(gr_gid=os.getgid() + 1))

    def refuse(*args: object, **kwargs: object) -> None:
        raise PermissionError(errno.EPERM, "Operation not permitted")

    monkeypatch.setattr(os, "chown", refuse)
    assert lake.set_group(BASE, "helio-readers") == GroupResult(
        GroupOutcome.PENDING, "share: Operation not permitted"
    )


def test_posix_in_group_trusts_the_effective_group_and_the_first_16_groups(
    lake: PosixStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    groups = list(range(5000, 5020))
    monkeypatch.setattr(os, "getegid", lambda: 4000)
    monkeypatch.setattr(os, "getgroups", lambda: groups)
    assert lake.in_group(4000) is True
    assert lake.in_group(groups[0]) is True
    assert lake.in_group(groups[15]) is True
    assert lake.in_group(groups[16]) is False
    assert lake.in_group(6000) is False


def test_posix_in_group_holds_the_group_of_the_process(lake: PosixStorage) -> None:
    assert lake.in_group(os.getegid()) is True


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


def test_memory_walk_refuses_an_unreadable_directory_below(memory: MemoryStorage) -> None:
    memory.make_directory(LakePath.of("d"), DIRECTORY_MODE)
    memory.make_directory(LakePath.of("d", "e"), DIRECTORY_MODE)
    memory.unreadable.add(LakePath.of("d", "e"))
    with pytest.raises(StorageError) as refused:
        list(memory.walk(LakePath.of("d")))
    assert refused.value.message == "permission denied on d"


def test_memory_set_mode_needs_the_owner(memory: MemoryStorage) -> None:
    memory.member_of.add(0)
    memory.make_directory(LakePath.of("d"), 0o750)
    memory.member_of.discard(0)
    assert memory.set_mode(LakePath.of("d"), DIRECTORY_MODE) is True
    assert found(memory, LakePath.of("d")).mode == 0o750
    with pytest.raises(StorageError, match="permission denied"):
        memory.set_mode(LakePath(), 0o755)


def test_memory_in_group_is_membership_of_member_of(memory: MemoryStorage) -> None:
    assert memory.in_group(1000) is True
    assert memory.in_group(2001) is False
    memory.member_of.add(2001)
    assert memory.in_group(2001) is True


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


def test_memory_open_file_of_a_foreign_file_cannot_change_its_mode(memory: MemoryStorage) -> None:
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


def test_memory_symlink_needs_its_parent_and_a_free_name(memory: MemoryStorage) -> None:
    with pytest.raises(StorageError, match="does not exist"):
        memory.symlink(LakePath.of("missing", "link"), "/outside")
    memory.make_directory(LakePath.of("d"), DIRECTORY_MODE)
    with pytest.raises(StorageError, match="d: File exists"):
        memory.symlink(LakePath.of("d"), "/outside")
    assert found(memory, LakePath.of("d")).kind == "dir"


def write_in_place(share: Storage, location: LakePath, data: bytes) -> None:
    """Change the bytes of the file at ``location`` in place, as tusd writes through its
    descriptor: the inode stays.
    """
    if isinstance(share, PosixStorage):
        with share.root.joinpath(*location.names).open("r+b") as handle:
            handle.write(data)
    else:
        assert isinstance(share, MemoryStorage)
        share.nodes[location].data = data


@pytest.mark.parametrize("data", [b"payload", b""], ids=["bytes", "empty"])
def test_copy_sealed_makes_a_new_file_that_a_later_write_to_the_source_does_not_change(
    share: Storage, data: bytes
) -> None:
    share.write_bytes(at("upload"), data, 0o600)
    source_inode = found(share, at("upload")).inode
    sealed = share.copy_sealed(at("upload"), at("object"), len(data))
    assert sealed == SealedFile(len(data), hashlib.sha256(data).hexdigest(), sealed.inode)
    copy = found(share, at("object"))
    assert (copy.inode, copy.mode, copy.size) == (sealed.inode, FILE_MODE, len(data))
    assert sealed.inode != source_inode
    write_in_place(share, at("upload"), b"PAYLOAD")
    assert found(share, at("upload")).inode == source_inode
    assert share.read_bytes(at("upload")) == b"PAYLOAD"
    assert share.read_bytes(at("object")) == data


@pytest.mark.parametrize(
    ("operation", "place", "number"),
    [
        ("write", at("object"), errno.ENOSPC),
        ("fsync", at("object"), errno.EIO),
        ("fsync", BASE, errno.EIO),
    ],
    ids=["enospc", "file sync", "directory sync"],
)
def test_a_failed_copy_gives_no_object_and_can_run_again(
    share: Storage, monkeypatch: pytest.MonkeyPatch, operation: str, place: LakePath, number: int
) -> None:
    share.write_bytes(at("upload"), b"payload", 0o600)
    with monkeypatch.context() as patch:
        inject_fault(share, patch, operation, place, number)
        with pytest.raises(StorageError) as refused:
            share.copy_sealed(at("upload"), at("object"), 7)
    assert type(refused.value) is StorageError
    assert refused.value.message == f"share/object: {os.strerror(number)}"
    assert refused.value.context == {"path": "share/object"}
    assert share.stat(at("object")) is None
    assert share.copy_sealed(at("upload"), at("object"), 7).size == 7


def test_copy_sealed_of_a_source_that_tusd_still_writes_is_a_size_mismatch(
    lake: PosixStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    lake.write_bytes(at("upload"), b"payload", 0o600)
    real = os.pread
    grown = False

    def growing(descriptor: int, length: int, offset: int) -> bytes:
        nonlocal grown
        if not grown:
            grown = True
            with (lake.root / "share" / "upload").open("ab") as handle:
                handle.write(b"+")
        return real(descriptor, length, offset)

    monkeypatch.setattr(os, "pread", growing)
    with pytest.raises(SourceSizeMismatch) as refused:
        lake.copy_sealed(at("upload"), at("object"), 7)
    assert type(refused.value) is SourceSizeMismatch
    assert refused.value.message == "the upload file share/upload has 8 bytes, not 7 bytes"
    assert refused.value.context == {"path": "share/upload", "expected": 7, "size": 8}
    assert lake.stat(at("object")) is None


def test_link_once_gives_a_file_a_second_name(share: Storage) -> None:
    share.write_bytes(at("object"), b"new", 0o644)
    share.link_once(at("object"), at("a.bin"))
    assert found(share, at("a.bin")).inode == found(share, at("object")).inode
    assert share.read_bytes(at("a.bin")) == b"new"


def test_link_once_across_two_mounts_is_refused_and_names_the_destination(
    share: Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    share.write_bytes(at("object"), b"new", 0o644)
    share.make_directory(at("mounted"), DIRECTORY_MODE)
    if isinstance(share, MemoryStorage):
        share.mounts.add(at("mounted"))
    else:
        inject_fault(share, monkeypatch, "link", at("mounted", "a.bin"), errno.EXDEV)
    with pytest.raises(StorageError) as refused:
        share.link_once(at("object"), at("mounted", "a.bin"))
    assert type(refused.value) is StorageError
    assert refused.value.message == f"share/mounted/a.bin: {os.strerror(errno.EXDEV)}"
    assert refused.value.context == {"path": "share/mounted/a.bin"}
    assert share.stat(at("mounted", "a.bin")) is None


def test_a_failed_link_once_makes_no_name(share: Storage, monkeypatch: pytest.MonkeyPatch) -> None:
    share.write_bytes(at("object"), b"new", 0o644)
    inject_fault(share, monkeypatch, "link", at("a.bin"), errno.ENOSPC)
    with pytest.raises(StorageError) as refused:
        share.link_once(at("object"), at("a.bin"))
    assert type(refused.value) is StorageError
    assert refused.value.message == "share/a.bin: No space left on device"
    assert refused.value.context == {"path": "share/a.bin"}
    assert share.stat(at("a.bin")) is None
    share.link_once(at("object"), at("a.bin"))
    assert share.read_bytes(at("a.bin")) == b"new"


def test_a_failed_sync_is_an_error_one_time(
    share: Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    inject_fault(share, monkeypatch, "fsync", BASE, errno.EIO)
    with pytest.raises(StorageError) as refused:
        share.sync_directory(BASE)
    assert type(refused.value) is StorageError
    assert refused.value.message == "share: Input/output error"
    assert refused.value.context == {"path": "share"}
    share.sync_directory(BASE)
    share.sync_directory(LakePath())


def test_memory_records_each_copy_link_and_sync(memory: MemoryStorage) -> None:
    memory.write_bytes(LakePath.of("upload"), b"x", 0o600)
    memory.copy_sealed(LakePath.of("upload"), LakePath.of("object"), 1)
    memory.link_once(LakePath.of("object"), LakePath.of("a.bin"))
    memory.sync_directory(LakePath())
    assert memory.calls[-4:] == [
        ("copy", LakePath.of("object")),
        ("sync", LakePath()),
        ("link", LakePath.of("a.bin")),
        ("sync", LakePath()),
    ]
    assert memory.faults == {}


def test_memory_links_only_inside_one_mount(memory: MemoryStorage) -> None:
    for directory in (".huron-objects", "orgx", "orgx/.huron-objects", "orgx/coll"):
        memory.make_directory(LakePath.parse(directory), 0o700)
    memory.mounts.add(LakePath.of("orgx"))
    memory.write_bytes(LakePath.of(".huron-objects", "x"), b"x", 0o644)
    memory.write_bytes(LakePath.of("orgx", ".huron-objects", "x"), b"x", 0o644)
    with pytest.raises(StorageError) as refused:
        memory.link_once(LakePath.of(".huron-objects", "x"), LakePath.of("orgx", "coll", "y"))
    assert type(refused.value) is StorageError
    assert refused.value.message == "orgx/coll/y: Invalid cross-device link"
    assert refused.value.context == {"path": "orgx/coll/y"}
    memory.link_once(LakePath.of("orgx", ".huron-objects", "x"), LakePath.of("orgx", "coll", "y"))
    assert memory.stat(LakePath.of("orgx", "coll", "y")) is not None


def test_memory_renames_only_inside_one_mount(memory: MemoryStorage) -> None:
    memory.make_directory(LakePath.of("orgx"), 0o700)
    memory.mounts.add(LakePath.of("orgx"))
    memory.write_bytes(LakePath.of("f"), b"x", 0o644)
    with pytest.raises(StorageError) as refused:
        memory.rename(LakePath.of("f"), LakePath.of("orgx", "f"))
    assert type(refused.value) is StorageError
    assert refused.value.message == "orgx/f: Invalid cross-device link"
    assert refused.value.context == {"path": "orgx/f"}
    assert memory.stat(LakePath.of("f")) is not None


def test_free_space_names_one_filesystem_for_two_directories_of_one_mount(share: Storage) -> None:
    share.make_directory(at("a"), 0o750)
    share.make_directory(at("b"), 0o750)
    first, second = share.free_space(at("a")), share.free_space(at("b"))
    assert first.filesystem == second.filesystem
    assert first.free > 0


def test_free_space_of_a_memory_mount_is_its_own() -> None:
    memory = MemoryStorage(LAKE, uid=1000, gid=1000)
    outer, mount = LakePath.of("a"), LakePath.of("a", "m")
    memory.make_directory(outer, 0o750)
    memory.make_directory(mount, 0o750)
    memory.mounts.add(mount)
    memory.free[mount] = 5
    assert memory.free_space(outer) == FreeSpace(1, FREE_BYTES)
    assert memory.free_space(mount) == FreeSpace(memory.nodes[mount].inode, 5)
    assert memory.nodes[mount].inode != 1
