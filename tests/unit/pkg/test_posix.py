"""POSIX descriptor primitives on a real temporary filesystem."""

import errno
import os
import stat
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from huron.pkg.fs import posix
from tests.support.disk import snapshot

PART = ".a.bin.1.huron-part"
BACKUP = ".a.bin.1.huron-prev"


@pytest.fixture
def lake(tmp_path: Path) -> Path:
    """``lake/a`` with a file ``lake/up/src`` of the bytes ``new``; ``outside`` beside it."""
    root = tmp_path / "lake"
    (root / "a").mkdir(parents=True)
    (root / "up").mkdir()
    (root / "up" / "src").write_bytes(b"new")
    (tmp_path / "outside" / "inner").mkdir(parents=True)
    (tmp_path / "outside" / "file").write_bytes(b"keep")
    return root


@contextmanager
def parent(lake: Path, *names: str) -> Iterator[int]:
    """The ``O_PATH`` descriptor of ``lake/<names>``."""
    with posix.open_beneath(lake, names) as descriptor:
        yield descriptor


def link_source(lake: Path, parent_fd: int, name: str) -> object:
    """Link ``up/src`` to ``name`` in ``parent_fd``."""
    inode = os.lstat(lake / "up" / "src").st_ino
    with parent(lake, "up") as source_fd:
        return posix.link_into_place(source_fd, "src", inode, parent_fd, name, PART, BACKUP)


PRIMITIVES: dict[str, Callable[[Path, int, str], object]] = {
    "entry": lambda lake, fd, name: posix.entry(fd, name),
    "open_file": lambda lake, fd, name: posix.open_file(fd, name),
    "open_directory": lambda lake, fd, name: posix.open_directory(fd, name),
    "open_entry": lambda lake, fd, name: posix.open_entry(fd, name),
    "change_mode": lambda lake, fd, name: posix.change_mode(fd, name, 0o600),
    "change_group": lambda lake, fd, name: posix.change_group(fd, name, os.getgid()),
    "make_dir": lambda lake, fd, name: posix.make_dir(fd, name, 0o750),
    "make_inheriting_dir": lambda lake, fd, name: posix.make_inheriting_dir(fd, name),
    "atomic_write": lambda lake, fd, name: posix.atomic_write(fd, name, b"x", 0o644, PART),
    "link_into_place": link_source,
    "remove_file": lambda lake, fd, name: posix.remove_file(fd, name),
    "remove_empty_dir": lambda lake, fd, name: posix.remove_empty_dir(fd, name),
}


@pytest.mark.parametrize("primitive", sorted(PRIMITIVES))
@pytest.mark.parametrize("target", ["inner", "file"])
def test_a_link_as_the_last_name_is_refused_and_outside_stays(
    lake: Path, primitive: str, target: str
) -> None:
    outside = lake.parent / "outside"
    (lake / "a" / "link").symlink_to(outside / target)
    before = snapshot(outside)
    with parent(lake, "a") as fd, pytest.raises(posix.SymlinkError) as refused:
        PRIMITIVES[primitive](lake, fd, "link")
    assert refused.value.names == ("link",)
    assert refused.value.errno == errno.ELOOP
    assert (lake / "a" / "link").is_symlink()
    assert snapshot(outside) == before


@pytest.mark.parametrize("depth", [1, 2])
def test_a_link_as_an_intermediate_directory_is_refused_with_the_names_up_to_it(
    lake: Path, depth: int
) -> None:
    outside = lake.parent / "outside"
    (lake / "a" / "b").mkdir()
    planted = ("a", "link") if depth == 1 else ("a", "b", "link")
    lake.joinpath(*planted).symlink_to(outside)
    before = snapshot(outside)
    with pytest.raises(posix.SymlinkError) as refused, parent(lake, *planted, "inner"):
        pass
    assert refused.value.names == planted
    assert snapshot(outside) == before


def test_open_beneath_yields_the_last_directory(lake: Path) -> None:
    with parent(lake, "a") as fd:
        assert os.fstat(fd).st_ino == os.lstat(lake / "a").st_ino
    with parent(lake) as fd:
        assert os.fstat(fd).st_ino == os.lstat(lake).st_ino


def test_open_beneath_through_a_file_keeps_the_not_a_directory_error(lake: Path) -> None:
    with pytest.raises(NotADirectoryError), parent(lake, "up", "src", "x"):
        pass


def test_open_beneath_a_missing_directory_keeps_the_not_found_error(lake: Path) -> None:
    with pytest.raises(FileNotFoundError), parent(lake, "missing"):
        pass


def test_open_beneath_a_directory_without_search_permission_keeps_the_permission_error(
    lake: Path,
) -> None:
    (lake / "a" / "b").mkdir()
    os.chmod(lake / "a", 0)
    try:
        with pytest.raises(PermissionError), parent(lake, "a", "b"):
            pass
    finally:
        os.chmod(lake / "a", 0o755)


def test_open_beneath_a_missing_root_is_root_unavailable(tmp_path: Path) -> None:
    with pytest.raises(posix.RootUnavailable) as refused, parent(tmp_path / "missing"):
        pass
    assert refused.value.errno == errno.ENOENT


def test_entry_is_the_lstat_or_none(lake: Path) -> None:
    with parent(lake, "up") as fd:
        found = posix.entry(fd, "src")
        assert found is not None
        assert found.st_size == 3
        assert posix.entry(fd, "missing") is None


def test_open_file_and_open_directory(lake: Path) -> None:
    with parent(lake, "up") as fd:
        opened = posix.open_file(fd, "src")
        try:
            assert os.read(opened, 10) == b"new"
        finally:
            os.close(opened)
        with pytest.raises(NotADirectoryError):
            posix.open_directory(fd, "src")
        with pytest.raises(FileNotFoundError):
            posix.open_file(fd, "missing")


def test_make_dir_gives_exactly_the_mode_and_keeps_an_existing_directory(lake: Path) -> None:
    with parent(lake, "a") as fd:
        assert posix.make_dir(fd, "d", 0o2750) is True
        assert stat.S_IMODE(os.lstat(lake / "a" / "d").st_mode) == 0o2750
        os.chmod(lake / "a" / "d", 0o700)
        assert posix.make_dir(fd, "d", 0o2750) is False
        assert stat.S_IMODE(os.lstat(lake / "a" / "d").st_mode) == 0o700
        (lake / "a" / "f").write_bytes(b"")
        with pytest.raises(FileExistsError):
            posix.make_dir(fd, "f", 0o750)


@pytest.fixture
def setgid_dir(lake: Path) -> Path:
    """A directory with the setgid bit, so new directories below it inherit its group."""
    os.chmod(lake / "a", 0o2750)
    return lake / "a"


def test_make_inheriting_dir_keeps_the_inherited_setgid_bit_and_group(
    lake: Path, setgid_dir: Path
) -> None:
    with parent(lake, "a") as fd:
        assert posix.make_inheriting_dir(fd, "d") is True
        info = os.lstat(setgid_dir / "d")
        assert stat.S_IMODE(info.st_mode) == 0o2750
        assert info.st_gid == os.lstat(setgid_dir).st_gid
        assert posix.make_inheriting_dir(fd, "d") is False


def test_make_inheriting_dir_refuses_a_directory_without_an_inherited_setgid_bit(
    lake: Path,
) -> None:
    os.chmod(lake / "a", 0o750)
    with parent(lake, "a") as fd, pytest.raises(posix.InheritanceError, match="did not inherit"):
        posix.make_inheriting_dir(fd, "d")
    assert not (lake / "a" / "d").exists()


def test_make_inheriting_dir_refuses_an_existing_file(lake: Path, setgid_dir: Path) -> None:
    (setgid_dir / "f").write_bytes(b"")
    with parent(lake, "a") as fd, pytest.raises(FileExistsError):
        posix.make_inheriting_dir(fd, "f")


def test_make_inheriting_dir_refuses_a_group_other_than_the_parents(
    lake: Path, setgid_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_stat = os.stat

    def server_stat(
        path: str, *, dir_fd: int | None = None, follow_symlinks: bool = True
    ) -> os.stat_result:
        info = real_stat(path, dir_fd=dir_fd, follow_symlinks=follow_symlinks)
        if path != "d":
            return info
        fields = list(info[:10])
        fields[5] = info.st_gid + 1  # the server gave the new directory another group
        return os.stat_result(fields)

    monkeypatch.setattr(os, "stat", server_stat)
    with parent(lake, "a") as fd, pytest.raises(posix.InheritanceError, match="did not inherit"):
        posix.make_inheriting_dir(fd, "d")
    assert not (setgid_dir / "d").exists()


def test_atomic_write_replaces_through_the_part_file_with_exactly_the_mode(lake: Path) -> None:
    (lake / "a" / PART).write_bytes(b"stale")
    with parent(lake, "a") as fd:
        posix.atomic_write(fd, "m.json", b"{}", 0o666, PART)
        posix.atomic_write(fd, "m.json", b'{"a":1}', 0o640, PART)
    target = lake / "a" / "m.json"
    assert target.read_bytes() == b'{"a":1}'
    assert stat.S_IMODE(os.lstat(target).st_mode) == 0o640
    assert sorted(p.name for p in (lake / "a").iterdir()) == ["m.json"]


def test_a_failed_atomic_write_leaves_no_part_file(lake: Path) -> None:
    (lake / "a" / "d").mkdir()
    with parent(lake, "a") as fd, pytest.raises(IsADirectoryError):
        posix.atomic_write(fd, "d", b"x", 0o644, PART)
    assert sorted(p.name for p in (lake / "a").iterdir()) == ["d"]


def test_atomic_write_refuses_a_part_file_that_is_a_link(lake: Path) -> None:
    outside = lake.parent / "outside"
    (lake / "a" / PART).symlink_to(outside / "file")
    with parent(lake, "a") as fd, pytest.raises(posix.SymlinkError) as refused:
        posix.atomic_write(fd, "m.json", b"x", 0o644, PART)
    assert refused.value.names == (PART,)
    assert (outside / "file").read_bytes() == b"keep"


def place(lake: Path, name: str = "a.bin", inode: int | None = None) -> str | None:
    """Link ``up/src`` to ``a/<name>``; ``inode`` stands in for the measured one."""
    measured = os.lstat(lake / "up" / "src").st_ino if inode is None else inode
    with parent(lake, "up") as source_fd, parent(lake, "a") as fd:
        return posix.link_into_place(source_fd, "src", measured, fd, name, PART, BACKUP)


def names_in(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir())


def test_link_into_place_links_a_new_name_without_a_backup(lake: Path) -> None:
    assert place(lake) is None
    assert os.path.samefile(lake / "a" / "a.bin", lake / "up" / "src")
    assert names_in(lake / "a") == ["a.bin"]


@pytest.mark.parametrize("stale", [(), (PART,), (BACKUP,), (PART, BACKUP)])
def test_link_into_place_replaces_an_existing_file_and_keeps_its_bytes_in_a_backup(
    lake: Path, stale: tuple[str, ...]
) -> None:
    destination = lake / "a" / "a.bin"
    destination.write_bytes(b"old")
    old_inode = os.lstat(destination).st_ino
    for name in stale:
        (lake / "a" / name).write_bytes(b"stale")
    assert place(lake) == BACKUP
    assert destination.read_bytes() == b"new"
    assert os.path.samefile(destination, lake / "up" / "src")
    backup = lake / "a" / BACKUP
    assert (backup.read_bytes(), os.lstat(backup).st_ino) == (b"old", old_inode)
    assert names_in(lake / "a") == [BACKUP, "a.bin"]


def test_link_into_place_over_a_link_of_the_same_file_changes_nothing(lake: Path) -> None:
    os.link(lake / "up" / "src", lake / "a" / "a.bin")
    assert place(lake) is None
    assert names_in(lake / "a") == ["a.bin"]


def test_link_into_place_after_an_interrupted_replacement_reports_its_backup(lake: Path) -> None:
    destination = lake / "a" / "a.bin"
    destination.write_bytes(b"old")
    os.link(destination, lake / "a" / BACKUP)
    os.link(lake / "up" / "src", lake / "a" / PART)
    os.rename(lake / "a" / PART, destination)
    assert place(lake) == BACKUP
    assert (lake / "a" / BACKUP).read_bytes() == b"old"
    assert os.path.samefile(destination, lake / "up" / "src")


def test_link_into_place_without_a_source_changes_nothing(lake: Path) -> None:
    (lake / "a" / "a.bin").write_bytes(b"old")
    inode = os.lstat(lake / "up" / "src").st_ino
    (lake / "up" / "src").unlink()
    with pytest.raises(FileNotFoundError):
        place(lake, inode=inode)
    assert (lake / "a" / "a.bin").read_bytes() == b"old"
    assert names_in(lake / "a") == ["a.bin"]


def test_link_into_place_refuses_a_source_with_another_inode(lake: Path) -> None:
    with pytest.raises(posix.SourceMismatch):
        place(lake, inode=os.lstat(lake / "up" / "src").st_ino + 1)
    assert names_in(lake / "a") == []


def test_link_into_place_refuses_a_source_that_is_a_link(lake: Path) -> None:
    (lake / "up" / "real").write_bytes(b"x")
    (lake / "up" / "src").unlink()
    (lake / "up" / "src").symlink_to(lake / "up" / "real")
    with pytest.raises(posix.SourceMismatch):
        place(lake, inode=os.lstat(lake / "up" / "src").st_ino)
    assert names_in(lake / "a") == []


@pytest.mark.parametrize("planted", [PART, BACKUP])
def test_link_into_place_refuses_a_part_or_backup_name_that_is_a_link(
    lake: Path, planted: str
) -> None:
    outside = lake.parent / "outside"
    (lake / "a" / "a.bin").write_bytes(b"old")
    (lake / "a" / planted).symlink_to(outside / "file")
    with pytest.raises(posix.SymlinkError) as refused:
        place(lake)
    assert refused.value.names == (planted,)
    assert (lake / "a" / "a.bin").read_bytes() == b"old"
    assert (outside / "file").read_bytes() == b"keep"


def test_link_into_place_that_cannot_back_up_the_destination_removes_its_part(
    lake: Path,
) -> None:
    (lake / "a" / "a.bin").mkdir()
    with pytest.raises(PermissionError):
        place(lake)
    assert names_in(lake / "a") == ["a.bin"]


def test_link_into_place_that_cannot_rename_keeps_the_old_file_alone(
    lake: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (lake / "a" / "a.bin").write_bytes(b"old")

    def refuse(source: str, target: str, **kwargs: int) -> None:
        raise OSError(errno.EIO, "I/O error")

    monkeypatch.setattr(os, "rename", refuse)
    with pytest.raises(OSError, match="I/O error"):
        place(lake)
    assert (lake / "a" / "a.bin").read_bytes() == b"old"
    assert names_in(lake / "a") == ["a.bin"]


def test_remove_helpers_report_whether_anything_was_removed(lake: Path) -> None:
    (lake / "a" / "d").mkdir()
    (lake / "a" / "full").mkdir()
    (lake / "a" / "full" / "x").write_bytes(b"x")
    with parent(lake, "up") as fd:
        assert posix.remove_file(fd, "src") is True
        assert posix.remove_file(fd, "src") is False
    with parent(lake, "a") as fd:
        assert posix.remove_empty_dir(fd, "d") is True
        assert posix.remove_empty_dir(fd, "d") is False
        with pytest.raises(OSError) as refused:
            posix.remove_empty_dir(fd, "full")
    assert refused.value.errno == errno.ENOTEMPTY


def test_walk_is_top_down_sorted_and_never_enters_a_link(lake: Path) -> None:
    outside = lake.parent / "outside"
    (lake / "a" / "b").mkdir()
    (lake / "a" / "b" / "c.txt").write_bytes(b"12345")
    (lake / "a" / "a.txt").write_bytes(b"1")
    (lake / "a" / "link").symlink_to(outside)
    os.mkfifo(lake / "a" / "pipe")
    descriptor = os.open(lake / "a", os.O_RDONLY | os.O_DIRECTORY)
    try:
        entries = list(posix.walk(descriptor))
    finally:
        os.close(descriptor)
    assert [(e.names, e.kind) for e in entries] == [
        (("a.txt",), "file"),
        (("b",), "dir"),
        (("b", "c.txt"), "file"),
        (("link",), "symlink"),
        (("pipe",), "other"),
    ]
    assert entries[2].size == 5


def test_change_mode_and_change_group_act_through_the_entry(lake: Path) -> None:
    (lake / "a" / "d").mkdir()
    gid = os.lstat(lake / "up" / "src").st_gid
    with parent(lake, "up") as fd:
        assert posix.change_mode(fd, "src", 0o600) is True
        assert posix.change_mode(fd, "src", 0o600) is False
        assert posix.change_group(fd, "src", gid) is False
        with pytest.raises(FileNotFoundError):
            posix.change_mode(fd, "missing", 0o600)
    assert stat.S_IMODE(os.lstat(lake / "up" / "src").st_mode) == 0o600
    with parent(lake, "a") as fd:
        assert posix.change_mode(fd, "d", 0o2750) is True
    assert stat.S_IMODE(os.lstat(lake / "a" / "d").st_mode) == 0o2750


def test_change_group_changes_the_group_through_the_descriptor(
    lake: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    changed: list[tuple[int, int]] = []
    monkeypatch.setattr(os, "fchown", lambda fd, uid, gid: changed.append((uid, gid)))
    other = os.lstat(lake / "up" / "src").st_gid + 1
    with parent(lake, "up") as fd:
        assert posix.change_group(fd, "src", other) is True
    assert changed == [(-1, other)]


def test_walk_names_a_directory_that_a_link_replaced_from_the_walked_directory(
    lake: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (lake / "a" / "b" / "c").mkdir(parents=True)
    real = os.open

    def opening(path: str, flags: int, *args: int, dir_fd: int | None = None) -> int:
        if path == "c":
            os.rename(lake / "a" / "b" / "c", lake / "a" / "b" / "c.moved")
            (lake / "a" / "b" / "c").symlink_to(lake.parent / "outside")
        return real(path, flags, *args, dir_fd=dir_fd)

    descriptor = os.open(lake / "a", os.O_RDONLY | os.O_DIRECTORY)
    monkeypatch.setattr(os, "open", opening)
    try:
        with pytest.raises(posix.SymlinkError) as refused:
            list(posix.walk(descriptor))
    finally:
        os.close(descriptor)
    assert refused.value.names == ("b", "c")
