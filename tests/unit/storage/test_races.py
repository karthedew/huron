"""The POSIX adapter against a lake that changes while it works, on a real filesystem.

Each case changes the lake at the ``os`` boundary, between two system calls of one operation.
"""

import os
import stat
from collections.abc import Callable
from pathlib import Path

import pytest

from huron.core.storage import LakePath, StorageError
from huron.core.storage.posix import PosixStorage
from tests.support.disk import snapshot

STEP = os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW
FILE = LakePath.of("a", "b", "f")


@pytest.fixture
def lake(tmp_path: Path) -> PosixStorage:
    """``lake/a/b/f`` (mode 0640), and ``outside/b/f`` with the same names outside the lake."""
    root = tmp_path / "lake"
    (root / "a" / "b").mkdir(parents=True)
    (root / "a" / "b" / "f").write_bytes(b"in")
    (root / "a" / "b" / "f").chmod(0o640)
    (tmp_path / "outside" / "b").mkdir(parents=True)
    (tmp_path / "outside" / "b" / "f").write_bytes(b"out")
    (tmp_path / "outside" / "b" / "f").chmod(0o640)
    return PosixStorage(root)


def outside(lake: PosixStorage) -> Path:
    return lake.root.parent / "outside"


def swap_on_open(
    monkeypatch: pytest.MonkeyPatch, when: Callable[[str, int], bool], swap: Callable[[], None]
) -> None:
    """Run ``swap`` once, just before the first ``os.open`` that ``when`` selects."""
    real = os.open
    done: list[bool] = []

    def opening(path: str, flags: int, *args: int, dir_fd: int | None = None) -> int:
        if not done and when(path, flags):
            done.append(True)
            swap()
        return real(path, flags, *args, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", opening)


def link_final_name(lake: PosixStorage) -> None:
    """Replace ``a/b/f`` by a link to ``outside/b/f``."""
    (lake.root / "a" / "b" / "f").unlink()
    (lake.root / "a" / "b" / "f").symlink_to(outside(lake) / "b" / "f")


@pytest.mark.parametrize(
    "change",
    [
        lambda lake: lake.set_mode(FILE, 0o666),
        lambda lake: lake.set_group(FILE, os.getgid()),
    ],
    ids=["set_mode", "set_group"],
)
def test_a_link_that_replaces_the_name_after_its_check_is_never_changed(
    lake: PosixStorage, monkeypatch: pytest.MonkeyPatch, change: Callable[[PosixStorage], object]
) -> None:
    before = snapshot(outside(lake))
    real = os.stat
    done: list[bool] = []

    def checked(
        path: str, *, dir_fd: int | None = None, follow_symlinks: bool = True
    ) -> os.stat_result:
        found = real(path, dir_fd=dir_fd, follow_symlinks=follow_symlinks)
        if not done and path == "f":
            done.append(True)
            link_final_name(lake)  # after the check, before the change
        return found

    monkeypatch.setattr(os, "stat", checked)
    with pytest.raises(StorageError) as refused:
        change(lake)
    assert (refused.value.code, refused.value.context["path"]) == ("SYMLINK_IN_LAKE", "a/b/f")
    assert snapshot(outside(lake)) == before
    assert stat.S_IMODE((outside(lake) / "b" / "f").stat().st_mode) == 0o640


OPERATIONS: dict[str, Callable[[PosixStorage], object]] = {
    "write_bytes": lambda lake: lake.write_bytes(FILE, b"new", 0o644),
    "set_mode": lambda lake: lake.set_mode(FILE, 0o600),
    "set_group": lambda lake: lake.set_group(FILE, os.getgid()),
    "remove_file": lambda lake: lake.remove_file(FILE),
    "read_bytes": lambda lake: lake.read_bytes(FILE),
    "make_directory": lambda lake: lake.make_directory(LakePath.of("a", "b", "d"), 0o750),
    "walk": lambda lake: list(lake.walk(LakePath.of("a", "b"))),
}


@pytest.mark.parametrize("operation", sorted(OPERATIONS))
def test_a_directory_replaced_after_its_step_opened_keeps_the_work_inside(
    lake: PosixStorage, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    def swap() -> None:
        os.rename(lake.root / "a", lake.root / "a.moved")
        (lake.root / "a").symlink_to(outside(lake))

    before = snapshot(outside(lake))
    real = os.open
    done: list[bool] = []

    def opening(path: str, flags: int, *args: int, dir_fd: int | None = None) -> int:
        descriptor = real(path, flags, *args, dir_fd=dir_fd)
        if not done and path == "a" and flags == STEP:
            done.append(True)
            swap()
        return descriptor

    monkeypatch.setattr(os, "open", opening)
    OPERATIONS[operation](lake)
    assert snapshot(outside(lake)) == before


def test_a_directory_replaced_by_a_link_during_a_walk_names_the_whole_lake_path(
    lake: PosixStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    def swap() -> None:
        os.rename(lake.root / "a" / "b", lake.root / "a" / "b.moved")
        (lake.root / "a" / "b").symlink_to(outside(lake))

    swap_on_open(monkeypatch, lambda path, flags: path == "b" and not flags & os.O_PATH, swap)
    with pytest.raises(StorageError) as refused:
        list(lake.walk(LakePath.of("a")))
    assert (refused.value.code, refused.value.context["path"]) == ("SYMLINK_IN_LAKE", "a/b")


def open_descriptors() -> int:
    return len(os.listdir("/proc/self/fd"))


@pytest.mark.parametrize(
    "read", [PosixStorage.read_bytes, PosixStorage.open_file], ids=["read_bytes", "open_file"]
)
def test_reading_a_directory_is_refused_without_a_leaked_descriptor(
    lake: PosixStorage, read: Callable[[PosixStorage, LakePath], object]
) -> None:
    before = open_descriptors()
    with pytest.raises(StorageError, match="a/b: Is a directory"):
        read(lake, LakePath.of("a", "b"))
    assert open_descriptors() == before


def test_reading_a_fifo_is_refused_without_blocking(lake: PosixStorage) -> None:
    os.mkfifo(lake.root / "a" / "pipe")
    with pytest.raises(StorageError, match="a/pipe: Invalid argument"):
        lake.open_file(LakePath.of("a", "pipe"))
