"""Crash-safety tests for the publication primitives in ``pkg.rawstore.commit``.

Each of :func:`fsync_dir`, :func:`flush_tree` and :func:`assert_same_filesystem`
gets its own direct contract test; :func:`commit_envelope` gets the bulk of the
module, because it is the durability boundary between an in-flight upload and a
published revision. The tests inject failures with ``crash_on`` and read back
the exact durability trace with ``fsync_log`` so each named crash point is
pinned to what is actually on disk afterward, not to how the function happens
to be written.
"""

from __future__ import annotations

import ctypes
import errno
import os
import stat
import sys
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from huron.core.rawstore.commit import (
    CrossDeviceCommitError,
    assert_same_filesystem,
    commit_envelope,
    fsync_dir,
)
from huron.core.rawstore.materialize import directory, flush_tree
from tests.unit.support import crash_on, fsync_log

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def _with_different_device(result: os.stat_result) -> os.stat_result:
    """Return a copy of ``result`` with ``st_dev`` changed, every other field kept.

    Args:
        result: The real ``stat`` result to vary.

    Returns:
        An equivalent result reporting a different device number, so a
        caller that only reads ``st_dev`` sees a cross-device pair while
        one that also reads ``st_mode`` (``Path.is_dir()``, for instance)
        keeps working.
    """
    fields = (
        result.st_mode,
        result.st_ino,
        result.st_dev + 1,
        result.st_nlink,
        result.st_uid,
        result.st_gid,
        result.st_size,
        result.st_atime,
        result.st_mtime,
        result.st_ctime,
    )
    return os.stat_result(fields)


def _fail_rename(monkeypatch: pytest.MonkeyPatch, error: int) -> None:
    def fail(source: int, name: bytes, target: int, destination: bytes, flags: int) -> int:
        ctypes.set_errno(error)
        return -1

    symbol = "renameatx_np" if sys.platform == "darwin" else "renameat2"
    monkeypatch.setattr(ctypes, "CDLL", lambda *args, **kwargs: SimpleNamespace(**{symbol: fail}))


def _committed_envelope(base: Path) -> tuple[Path, Path]:
    """Build a minimal staging envelope with a ``COMMITTED`` marker under ``base``.

    Args:
        base: The directory the envelope is built under; created if
            missing.

    Returns:
        The staging envelope's path, and an unclaimed path beside it to
        publish it at.
    """
    base.mkdir(parents=True, exist_ok=True)
    staging = base / "staging"
    staging.mkdir()
    (staging / "COMMITTED").touch()
    return staging, base / "final"


def test_fsync_dir_flushes_a_directory_descriptor_and_refuses_a_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """fsync_dir flushes exactly the directory it is given and refuses a plain file."""
    log = fsync_log(monkeypatch)
    directory = tmp_path / "dir"
    directory.mkdir()

    fsync_dir(directory)

    assert log == [directory]

    file_path = tmp_path / "file.txt"
    file_path.write_text("x")
    with pytest.raises(NotADirectoryError):
        fsync_dir(file_path)


def test_flush_tree_makes_every_child_durable_before_its_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Descriptor traversal flushes every file and directory before the directory naming it."""
    log = fsync_log(monkeypatch)
    root = tmp_path / "tree"
    (root / "a" / "b").mkdir(parents=True)
    top_file = root / "top.txt"
    top_file.write_text("x")
    middle_file = root / "a" / "other.txt"
    middle_file.write_text("y")
    deep_file = root / "a" / "b" / "file.txt"
    deep_file.write_text("z")

    with directory(root) as descriptor:
        flush_tree(descriptor)

    expected = {top_file, middle_file, deep_file, root / "a" / "b", root / "a", root}
    assert set(log) == expected
    assert len(log) == len(expected)
    assert log[-1] == root
    for path in expected - {root}:
        assert log.index(path) < log.index(path.parent)


def test_flush_tree_opens_a_sealed_tree(tmp_path: Path) -> None:
    """Descriptor traversal flushes files and directories even after they are sealed read-only."""
    root = tmp_path / "sealed"
    (root / "child").mkdir(parents=True)
    file_path = root / "child" / "file.txt"
    file_path.write_text("x")
    file_path.chmod(0o444)
    (root / "child").chmod(0o555)
    root.chmod(0o555)

    with directory(root) as descriptor:
        flush_tree(descriptor)


def test_assert_same_filesystem_creates_both_roots_and_accepts_one_device(tmp_path: Path) -> None:
    """Missing roots are created and no error is raised when they share a filesystem."""
    staging_root = tmp_path / "staging"
    final_root = tmp_path / "organization"

    assert_same_filesystem(staging_root, final_root)

    assert staging_root.is_dir()
    assert final_root.is_dir()


def test_assert_same_filesystem_refuses_two_devices(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A staging root reporting a different device raises CrossDeviceCommitError with EXDEV."""
    staging_root = tmp_path / "staging"
    final_root = tmp_path / "organization"
    real_stat = type(staging_root).stat

    def _fake_stat(self: Path, *args: object, **kwargs: object) -> os.stat_result:
        result = real_stat(self, *args, **kwargs)
        return _with_different_device(result) if self == staging_root else result

    monkeypatch.setattr(type(staging_root), "stat", _fake_stat)

    with pytest.raises(CrossDeviceCommitError) as exc_info:
        assert_same_filesystem(staging_root, final_root)

    assert exc_info.value.errno == errno.EXDEV


def test_commit_envelope_refuses_an_existing_final_that_is_not_a_completed_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A final that exists but is not a completed retry's leftover raises FileExistsError."""
    staging, final = _committed_envelope(tmp_path)
    final.mkdir()
    log = fsync_log(monkeypatch)

    with pytest.raises(FileExistsError):
        commit_envelope(staging, final, tmp_path)

    assert staging.is_dir()
    assert log == []


def test_commit_envelope_refuses_a_missing_staging_directory(tmp_path: Path) -> None:
    """A staging path that is not a directory raises FileNotFoundError."""
    staging = tmp_path / "missing"
    final = tmp_path / "final"

    with pytest.raises(FileNotFoundError):
        commit_envelope(staging, final, tmp_path)


def test_commit_envelope_refuses_an_envelope_without_the_committed_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A staging envelope with no COMMITTED marker raises ValueError before any rename."""
    staging = tmp_path / "staging"
    staging.mkdir()
    final = tmp_path / "final"
    renames = crash_on(monkeypatch, "rename")

    with pytest.raises(ValueError, match="COMMITTED"):
        commit_envelope(staging, final, tmp_path)

    assert renames == []


def test_commit_envelope_refuses_a_cross_device_pair_before_any_fsync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A staging and final pair on different devices raises CrossDeviceCommitError, no fsync."""
    staging, final = _committed_envelope(tmp_path)
    identity = staging.stat()
    real_fstat = os.fstat

    def _fake_fstat(descriptor: int) -> os.stat_result:
        result = real_fstat(descriptor)
        return _with_different_device(result) if result.st_ino == identity.st_ino else result

    monkeypatch.setattr(os, "fstat", _fake_fstat)
    log = fsync_log(monkeypatch)

    with pytest.raises(CrossDeviceCommitError) as exc_info:
        commit_envelope(staging, final, tmp_path)

    assert exc_info.value.errno == errno.EXDEV
    assert log == []


def test_commit_envelope_translates_exdev_from_the_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An EXDEV raised by the rename itself is translated to CrossDeviceCommitError."""
    staging, final = _committed_envelope(tmp_path)
    _fail_rename(monkeypatch, errno.EXDEV)

    with pytest.raises(CrossDeviceCommitError) as exc_info:
        commit_envelope(staging, final, tmp_path)

    assert exc_info.value.errno == errno.EXDEV
    assert staging.is_dir()
    assert not final.exists()


def test_commit_envelope_fsyncs_the_whole_tree_before_the_rename_and_the_parent_after(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every staging path is fsynced before the rename; final's parent and final after it."""
    staging, final = _committed_envelope(tmp_path)
    log = fsync_log(monkeypatch)
    original_library = ctypes.CDLL
    symbol = "renameatx_np" if sys.platform == "darwin" else "renameat2"
    split_index: list[int] = []

    def library(*args: object, **kwargs: object) -> SimpleNamespace:
        native = getattr(original_library(*args, **kwargs), symbol)

        def rename(source: int, name: bytes, destination: int, target: bytes, flags: int) -> int:
            split_index.append(len(log))
            return native(source, name, destination, target, flags)

        return SimpleNamespace(**{symbol: rename})

    monkeypatch.setattr(ctypes, "CDLL", library)

    commit_envelope(staging, final, tmp_path)

    before, after = log[: split_index[0]], log[split_index[0] :]
    assert set(before) == {staging, staging / "COMMITTED"}
    assert after[:2] == [staging.parent, final.parent]
    assert after[2:] in ([staging], [final])


def test_commit_envelope_publishes_and_seals_the_root(tmp_path: Path) -> None:
    """A successful commit publishes final as a 0o555 directory and removes staging."""
    staging, final = _committed_envelope(tmp_path)

    commit_envelope(staging, final, tmp_path)

    assert not staging.exists()
    assert final.is_dir()
    assert stat.S_IMODE(final.stat().st_mode) == 0o555


def test_commit_envelope_retry_after_the_rename_is_silent_and_reseals_the_root(
    tmp_path: Path,
) -> None:
    """A retry against an already-published envelope returns silently and reseals the root."""
    staging, final = _committed_envelope(tmp_path)
    commit_envelope(staging, final, tmp_path)
    final.chmod(0o700)

    commit_envelope(staging, final, tmp_path)

    assert stat.S_IMODE(final.stat().st_mode) == 0o555


@pytest.mark.parametrize("failed_parent", ["source", "target"])
def test_publication_retry_flushes_both_rename_parents_before_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failed_parent: str
) -> None:
    """A visible rename with a failed durability barrier is made durable by its retry."""
    staging, _ = _committed_envelope(tmp_path / "session")
    destination = tmp_path / "revisions"
    destination.mkdir()
    final = destination / "revision"
    failed = staging.parent if failed_parent == "source" else final.parent
    identity = failed.stat()
    real_fsync = os.fsync

    def fail_parent(descriptor: int) -> None:
        info = os.fstat(descriptor)
        if (info.st_dev, info.st_ino) == (identity.st_dev, identity.st_ino):
            raise OSError(errno.EIO, "directory flush failed")
        real_fsync(descriptor)

    with monkeypatch.context() as patch:
        patch.setattr(os, "fsync", fail_parent)
        with pytest.raises(OSError, match="directory flush failed"):
            commit_envelope(staging, final, tmp_path)
    assert not staging.exists()
    assert (final / "COMMITTED").is_file()
    log = fsync_log(monkeypatch)
    commit_envelope(staging, final, tmp_path)
    assert {staging.parent, final.parent, final} <= set(log)
    assert stat.S_IMODE(final.stat().st_mode) == 0o555


def test_a_crash_in_the_tree_fsync_attempts_no_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A crash during the pre-rename tree fsync leaves staging intact and never renames."""
    staging, final = _committed_envelope(tmp_path)
    renames = crash_on(monkeypatch, "rename")
    crash_on(monkeypatch, "fsync")

    with pytest.raises(OSError) as exc_info:
        commit_envelope(staging, final, tmp_path)

    assert exc_info.value.errno == errno.EIO
    assert renames == []
    assert staging.is_dir()
    assert not final.exists()


def test_a_crash_in_the_rename_leaves_staging_intact_and_final_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A crash during the rename itself leaves staging intact and final never created."""
    staging, final = _committed_envelope(tmp_path)
    _fail_rename(monkeypatch, errno.EIO)

    with pytest.raises(OSError) as exc_info:
        commit_envelope(staging, final, tmp_path)

    assert exc_info.value.errno == errno.EIO
    assert staging.is_dir()
    assert (staging / "COMMITTED").is_file()
    assert not final.exists()


def test_a_crash_in_the_parent_fsync_leaves_the_envelope_published_and_the_retry_silent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A crash in the parent fsync still leaves final published, and the retry is silent."""
    rehearsal_staging, rehearsal_final = _committed_envelope(tmp_path / "rehearsal")
    log = fsync_log(monkeypatch)
    commit_envelope(rehearsal_staging, rehearsal_final, tmp_path)
    parent_fsync_call = log.index(rehearsal_final.parent) + 1
    monkeypatch.undo()

    staging, final = _committed_envelope(tmp_path / "real")
    crash_on(monkeypatch, "fsync", call=parent_fsync_call)

    with pytest.raises(OSError) as exc_info:
        commit_envelope(staging, final, tmp_path)

    assert exc_info.value.errno == errno.EIO
    assert not staging.exists()
    assert final.is_dir()

    commit_envelope(staging, final, tmp_path)

    assert stat.S_IMODE(final.stat().st_mode) == 0o555


def test_publication_refuses_parent_escape(tmp_path: Path) -> None:
    """Publication rejects a destination that traverses above the trusted root."""
    staging, _ = _committed_envelope(tmp_path)
    with pytest.raises(ValueError, match="escapes"):
        commit_envelope(staging, tmp_path / "../escaped/revision", tmp_path)
    assert staging.is_dir()
