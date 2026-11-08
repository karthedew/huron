"""POSIX filesystem primitives on a temporary directory."""

import errno
import hashlib
import os
import stat
from pathlib import Path

import pytest

from huron.pkg.fs import posix


def test_make_dir_creates_with_the_exact_mode(tmp_path: Path) -> None:
    target = tmp_path / "d"
    assert posix.make_dir(target, 0o2770) is True
    assert stat.S_IMODE(os.lstat(target).st_mode) == 0o2770
    assert posix.make_dir(target, 0o2770) is False


def test_make_dir_fixes_the_mode_of_an_existing_directory(tmp_path: Path) -> None:
    target = tmp_path / "d"
    target.mkdir(mode=0o755)
    assert posix.make_dir(target, 0o3770) is False
    assert stat.S_IMODE(os.lstat(target).st_mode) == 0o3770


def test_make_dir_refuses_files_and_symlinks(tmp_path: Path) -> None:
    (tmp_path / "file").write_text("x")
    (tmp_path / "real").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "real")
    for name in ("file", "link"):
        with pytest.raises(NotADirectoryError):
            posix.make_dir(tmp_path / name, 0o770)


def test_atomic_copy_writes_through_a_part_file(tmp_path: Path) -> None:
    source = tmp_path / "src.bin"
    source.write_bytes(b"payload")
    destination = tmp_path / "dest.bin"
    (tmp_path / "dest.bin.huron-part").write_bytes(b"stale")
    size, digest = posix.atomic_copy(source, destination)
    assert (size, digest) == (7, hashlib.sha256(b"payload").hexdigest())
    assert destination.read_bytes() == b"payload"
    assert not (tmp_path / "dest.bin.huron-part").exists()


def test_failed_copy_leaves_no_part_and_keeps_the_destination(tmp_path: Path) -> None:
    destination = tmp_path / "dest.bin"
    destination.write_bytes(b"old")
    with pytest.raises(FileNotFoundError):
        posix.atomic_copy(tmp_path / "missing", destination)
    assert destination.read_bytes() == b"old"
    assert not (tmp_path / "dest.bin.huron-part").exists()


def test_atomic_write_replaces_and_cleans_up(tmp_path: Path) -> None:
    target = tmp_path / "metadata.json"
    posix.atomic_write(target, b"{}")
    posix.atomic_write(target, b'{"a":1}')
    assert target.read_bytes() == b'{"a":1}'
    with pytest.raises(FileNotFoundError):
        posix.atomic_write(tmp_path / "missing" / "x", b"")
    assert not list((tmp_path).glob("*.huron-part"))


def test_remove_helpers_report_whether_anything_was_removed(tmp_path: Path) -> None:
    (tmp_path / "f").write_text("x")
    (tmp_path / "d").mkdir()
    assert posix.remove_file(tmp_path / "f") is True
    assert posix.remove_file(tmp_path / "f") is False
    assert posix.remove_empty_dir(tmp_path / "d") is True
    assert posix.remove_empty_dir(tmp_path / "d") is False
    (tmp_path / "full").mkdir()
    (tmp_path / "full" / "x").write_text("x")
    with pytest.raises(OSError):
        posix.remove_empty_dir(tmp_path / "full")


def test_walk_is_sorted_recursive_and_does_not_follow_links(tmp_path: Path) -> None:
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "c.txt").write_bytes(b"12345")
    (tmp_path / "a.txt").write_bytes(b"1")
    (tmp_path / "link").symlink_to(tmp_path / "b")
    os.mkfifo(tmp_path / "pipe")
    entries = list(posix.walk(tmp_path))
    assert [(e.rel_path, e.kind, e.is_symlink) for e in entries] == [
        ("a.txt", "file", False),
        ("b", "dir", False),
        ("b/c.txt", "file", False),
        ("link", "other", True),
        ("pipe", "other", False),
    ]
    assert entries[2].size == 5


def test_stat_and_is_dir(tmp_path: Path) -> None:
    (tmp_path / "f").write_bytes(b"abc")
    assert posix.stat(tmp_path / "f").size == 3
    assert posix.is_dir(tmp_path) is True
    assert posix.is_dir(tmp_path / "f") is False
    assert posix.is_dir(tmp_path / "missing") is False


@pytest.fixture
def setgid_dir(tmp_path: Path) -> Path:
    """A directory with the setgid bit, so new directories below it inherit its group."""
    directory = tmp_path / "catalog"
    directory.mkdir()
    os.chmod(directory, 0o2750)
    return directory


def test_make_inheriting_dir_keeps_the_inherited_setgid_bit_and_group(setgid_dir: Path) -> None:
    target = setgid_dir / "d"
    assert posix.make_inheriting_dir(target) is True
    info = os.lstat(target)
    assert stat.S_IMODE(info.st_mode) == 0o2750
    assert info.st_gid == os.lstat(setgid_dir).st_gid
    assert posix.make_inheriting_dir(target) is False


def test_make_inheriting_dir_refuses_a_directory_without_an_inherited_group(
    tmp_path: Path,
) -> None:
    os.chmod(tmp_path, 0o750)
    with pytest.raises(posix.InheritanceError, match="did not inherit the setgid bit"):
        posix.make_inheriting_dir(tmp_path / "d")
    assert not (tmp_path / "d").exists()


def test_make_inheriting_dir_refuses_an_existing_file(setgid_dir: Path) -> None:
    (setgid_dir / "f").write_bytes(b"")
    with pytest.raises(FileExistsError):
        posix.make_inheriting_dir(setgid_dir / "f")


PART = ".a.bin.1.huron-part"
BACKUP = ".a.bin.1.huron-prev"


@pytest.fixture
def upload(tmp_path: Path) -> Path:
    """A finished upload with the bytes ``new``."""
    source = tmp_path / "upload"
    source.write_bytes(b"new")
    return source


def test_link_into_place_links_a_new_name_without_a_backup(tmp_path: Path, upload: Path) -> None:
    destination = tmp_path / "a.bin"
    assert posix.link_into_place(upload, destination, PART, BACKUP) is None
    assert posix.inode(destination) == posix.inode(upload)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.bin", "upload"]


@pytest.mark.parametrize("stale", [(), (PART,), (BACKUP,), (PART, BACKUP)])
def test_link_into_place_replaces_an_existing_file_and_keeps_its_bytes_in_a_backup(
    tmp_path: Path, upload: Path, stale: tuple[str, ...]
) -> None:
    destination = tmp_path / "a.bin"
    destination.write_bytes(b"old")
    old_inode = posix.inode(destination)
    for name in stale:
        (tmp_path / name).write_bytes(b"stale")
    backup = posix.link_into_place(upload, destination, PART, BACKUP)
    assert backup == tmp_path / BACKUP
    assert (destination.read_bytes(), posix.inode(destination)) == (b"new", posix.inode(upload))
    assert (backup.read_bytes(), posix.inode(backup)) == (b"old", old_inode)
    assert sorted(p.name for p in tmp_path.iterdir()) == [BACKUP, "a.bin", "upload"]


def test_link_into_place_over_a_link_of_the_same_file_changes_nothing(
    tmp_path: Path, upload: Path
) -> None:
    destination = tmp_path / "a.bin"
    os.link(upload, destination)
    assert posix.link_into_place(upload, destination, PART, BACKUP) is None
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.bin", "upload"]


def test_link_into_place_after_an_interrupted_replacement_reports_its_backup(
    tmp_path: Path, upload: Path
) -> None:
    destination = tmp_path / "a.bin"
    destination.write_bytes(b"old")
    old_inode = posix.inode(destination)
    os.link(destination, tmp_path / BACKUP)
    os.link(upload, tmp_path / PART)
    os.rename(tmp_path / PART, destination)
    backup = posix.link_into_place(upload, destination, PART, BACKUP)
    assert backup == tmp_path / BACKUP
    assert (backup.read_bytes(), posix.inode(backup)) == (b"old", old_inode)
    assert posix.inode(destination) == posix.inode(upload)


def test_link_into_place_without_a_source_changes_nothing(tmp_path: Path) -> None:
    destination = tmp_path / "a.bin"
    destination.write_bytes(b"old")
    with pytest.raises(FileNotFoundError):
        posix.link_into_place(tmp_path / "missing", destination, PART, BACKUP)
    assert destination.read_bytes() == b"old"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.bin"]


def test_link_into_place_that_cannot_back_up_the_destination_removes_its_part(
    tmp_path: Path, upload: Path
) -> None:
    (tmp_path / "a.bin").mkdir()
    with pytest.raises(PermissionError):
        posix.link_into_place(upload, tmp_path / "a.bin", PART, BACKUP)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.bin", "upload"]


def test_link_into_place_that_cannot_rename_keeps_the_old_file_alone(
    tmp_path: Path, upload: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "a.bin"
    destination.write_bytes(b"old")

    def refuse(source: Path, target: Path) -> None:
        raise OSError(errno.EIO, "I/O error")

    monkeypatch.setattr(os, "rename", refuse)
    with pytest.raises(OSError, match="I/O error"):
        posix.link_into_place(upload, destination, PART, BACKUP)
    assert destination.read_bytes() == b"old"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.bin", "upload"]


def test_inode_does_not_follow_a_symlink(tmp_path: Path) -> None:
    (tmp_path / "f").write_bytes(b"")
    (tmp_path / "link").symlink_to(tmp_path / "f")
    assert posix.inode(tmp_path / "f") == os.lstat(tmp_path / "f").st_ino
    assert posix.inode(tmp_path / "link") != posix.inode(tmp_path / "f")
    with pytest.raises(FileNotFoundError):
        posix.inode(tmp_path / "missing")


def test_make_inheriting_dir_refuses_a_group_other_than_the_parents(
    setgid_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = setgid_dir / "d"
    real_lstat = os.lstat

    def server_lstat(path: Path) -> os.stat_result:
        info = real_lstat(path)
        if Path(path) != target:
            return info
        fields = list(info[:10])
        fields[5] = info.st_gid + 1  # the server gave the new directory another group
        return os.stat_result(fields)

    monkeypatch.setattr(os, "lstat", server_lstat)
    with pytest.raises(posix.InheritanceError, match="did not inherit"):
        posix.make_inheriting_dir(target)
    assert not target.exists()
