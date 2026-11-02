"""POSIX filesystem primitives on a temporary directory."""

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
