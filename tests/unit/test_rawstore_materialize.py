"""Real descriptor and concurrent completion contracts for independent payloads."""

from __future__ import annotations

import asyncio
import errno
import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest

from huron.pkg.rawstore import PosixRawStore, materialize
from huron.pkg.rawstore.materialize import candidate, directory, install, observe, rename_exclusive
from tests.unit.support import crash_on, fsync_log

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = pytest.mark.unit


@pytest.fixture
def storage(tmp_path: Path) -> tuple[PosixRawStore, Path]:
    """Create the fixed private session roots once."""
    store = PosixRawStore(tmp_path)
    store.initialize()
    root = tmp_path / ".staging" / "session"
    store.create_staging(root)
    return store, root


def _finish(
    store: PosixRawStore, root: Path, data: bytes, path: str = "payload/nested/file"
) -> tuple[int, str]:
    return store.finish_file(
        root,
        "input",
        path,
        expected_size=len(data),
        expected_sha256=hashlib.sha256(data).hexdigest(),
    )


@pytest.mark.parametrize("data", [b"", b"one", b"a" * (2**20 + 7)])
def test_completion_installs_a_closed_sealed_independent_inode(
    storage: tuple[PosixRawStore, Path], data: bytes
) -> None:
    """The payload has verified bytes and no inode or writable handle shared with upload."""
    store, root = storage
    store.write_part(root, "input", [data], offset=0, length=len(data))
    source = root / "upload/input"
    held = os.open(source, os.O_WRONLY)
    try:
        assert _finish(store, root, data) == (len(data), hashlib.sha256(data).hexdigest())
        payload = root / "envelope/payload/nested/file"
        assert payload.stat().st_ino != source.stat().st_ino
        assert payload.stat().st_nlink == 1
        assert payload.stat().st_mode & 0o222 == 0
        os.pwrite(held, b"changed", 0)
        assert payload.read_bytes() == data
        assert list((root / "completion").iterdir()) == []
    finally:
        os.close(held)


def test_a_trickled_upload_descriptor_cannot_change_a_published_file(
    storage: tuple[PosixRawStore, Path],
) -> None:
    """A request held across completion and publication writes only its private input inode."""
    store, root = storage
    started, resume = Event(), Event()
    data = b"good"

    def trickled() -> Iterator[bytes]:
        started.set()
        assert resume.wait(10)
        yield b"evil"

    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(store.write_part, root, "input", trickled(), offset=0, length=4)
        try:
            assert started.wait(10)
            store.write_part(root, "input", [data], offset=0, length=4)
            _finish(store, root, data)
            store.write_document(root / "envelope", "COMMITTED", b"marker")
            store.seal(root / "envelope")
            final = store.root / "organization" / "final"
            store.commit_envelope(root / "envelope", final)
        finally:
            resume.set()
        pending.result(timeout=10)
    assert (final / "payload/nested/file").read_bytes() == data
    assert not (root / "envelope").exists()


def test_overlapping_completions_converge_on_one_inode(storage: tuple[PosixRawStore, Path]) -> None:
    """Two attempts independently copying one input publish exactly one valid payload inode."""
    store, root = storage
    data = b"same bytes"
    store.write_part(root, "input", [data], offset=0, length=len(data))
    barrier = Barrier(2)

    def complete() -> tuple[int, str]:
        barrier.wait(timeout=10)
        return _finish(store, root, data)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(complete) for _ in range(2)]
        observations = [future.result(timeout=10) for future in futures]
    assert observations == [(len(data), hashlib.sha256(data).hexdigest())] * 2
    installed = root / "envelope/payload/nested/file"
    inode = installed.stat().st_ino
    assert _finish(store, root, data) == observations[0]
    assert installed.stat().st_ino == inode
    assert installed.stat().st_nlink == 1
    assert list((root / "completion").iterdir()) == []


@pytest.mark.parametrize("conflicting", [False, True])
def test_completion_validates_a_winner_that_removes_upload_before_the_loser_opens_it(
    storage: tuple[PosixRawStore, Path], monkeypatch: pytest.MonkeyPatch, conflicting: bool
) -> None:
    """A completion racing input cleanup succeeds only when the installed winner agrees."""
    store, root = storage
    data = b"independent winner"
    store.write_part(root, "input", [data], offset=0, length=len(data))
    waiting, resume = Event(), Event()
    real_open = os.open

    def delayed_open(
        path: str | os.PathLike[str], flags: int, mode: int = 0o777, *, dir_fd: int | None = None
    ) -> int:
        if path == "input" and flags & os.O_ACCMODE == os.O_RDONLY and not waiting.is_set():
            waiting.set()
            assert resume.wait(10)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", delayed_open)
    with ThreadPoolExecutor(max_workers=1) as executor:
        loser = executor.submit(_finish, store, root, data)
        try:
            assert waiting.wait(10)
            installed = b"x" * len(data) if conflicting else data
            store.write_part(root, "input", [installed], offset=0, length=len(installed))
            winner = _finish(store, root, installed)
            store.discard_file(root, "input")
        finally:
            resume.set()
        if conflicting:
            with pytest.raises(ValueError, match="conflicts"):
                loser.result(timeout=10)
        else:
            assert loser.result(timeout=10) == winner
    assert (root / "envelope/payload/nested/file").read_bytes() == installed
    assert not (root / "upload/input").exists()
    assert list((root / "completion").iterdir()) == []


def test_a_mismatch_cannot_remove_an_installed_winner(storage: tuple[PosixRawStore, Path]) -> None:
    """Bad expected content neither replaces nor unlinks an already verified destination."""
    store, root = storage
    store.write_part(root, "input", [b"good"], offset=0, length=4)
    _finish(store, root, b"good")
    with pytest.raises(ValueError, match="conflicts"):
        _finish(store, root, b"evil")
    assert (root / "envelope/payload/nested/file").read_bytes() == b"good"


def test_missing_upload_without_an_installed_winner_is_not_complete(
    storage: tuple[PosixRawStore, Path],
) -> None:
    """Missing input is not mistaken for successful concurrent completion."""
    store, root = storage
    with pytest.raises(FileNotFoundError):
        _finish(store, root, b"missing")
    assert list((root / "completion").iterdir()) == []
    assert not (root / "envelope/payload/nested/file").exists()


def test_mismatch_installs_nothing_and_retains_the_upload_for_retry(
    storage: tuple[PosixRawStore, Path],
) -> None:
    """A bad copy reports its observation and removes only its own candidate."""
    store, root = storage
    store.write_part(root, "input", [b"bad"], offset=0, length=3)
    assert _finish(store, root, b"good") == (3, hashlib.sha256(b"bad").hexdigest())
    assert not (root / "envelope/payload/nested/file").exists()
    assert (root / "upload/input").read_bytes() == b"bad"
    assert list((root / "completion").iterdir()) == []


@pytest.mark.parametrize("operation", ["write", "fsync", "fchmod"])
@pytest.mark.parametrize("error", [errno.ENOSPC, errno.EIO])
def test_failed_candidate_durability_never_installs_partial_bytes(
    storage: tuple[PosixRawStore, Path], monkeypatch: pytest.MonkeyPatch, operation: str, error: int
) -> None:
    """A failed storage syscall leaves no attested payload and an intact retryable upload."""
    store, root = storage
    data = b"candidate bytes"
    store.write_part(root, "input", [data], offset=0, length=len(data))
    with monkeypatch.context() as patch:
        crash_on(patch, operation, errno_=error)
        with pytest.raises(OSError):
            _finish(store, root, data)
    assert not (root / "envelope/payload/nested/file").exists()
    assert _finish(store, root, data) == (len(data), hashlib.sha256(data).hexdigest())


@pytest.mark.parametrize("action", ["part", "complete", "document"])
def test_late_operations_never_recreate_a_relocated_session(
    storage: tuple[PosixRawStore, Path], action: str
) -> None:
    """Every later writer requires the existing session and leaves the old name absent."""
    store, root = storage
    store.write_part(root, "input", [b"x"], offset=0, length=1)
    root.rename(root.with_name("relocated"))
    with pytest.raises(FileNotFoundError):
        if action == "part":
            store.write_part(root, "nested/input", [b"x"], offset=0, length=1)
        elif action == "complete":
            _finish(store, root, b"x")
        else:
            store.write_document(root / "envelope", "metadata.json", b"{}")
    assert not root.exists()


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo"])
def test_upload_refuses_nonindependent_or_special_inputs(
    storage: tuple[PosixRawStore, Path], tmp_path: Path, kind: str
) -> None:
    """Unsafe input inodes are rejected without following, modifying or blocking on them."""
    store, root = storage
    outside = tmp_path / "outside"
    outside.write_bytes(b"safe")
    target = root / "upload/input"
    if kind == "symlink":
        target.symlink_to(outside)
    elif kind == "hardlink":
        os.link(outside, target)
    else:
        os.mkfifo(target)
    with pytest.raises((OSError, ValueError)):
        store.write_part(root, "input", [b"evil"], offset=0, length=4)
    with pytest.raises((OSError, ValueError)):
        _finish(store, root, b"evil")
    assert outside.read_bytes() == b"safe"


def test_nested_symlinks_and_session_symlinks_are_not_followed(
    storage: tuple[PosixRawStore, Path], tmp_path: Path
) -> None:
    """Both the session anchor and each nested directory reject symlink substitution."""
    store, root = storage
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "upload/nested").symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        store.write_part(root, "nested/file", [b"evil"], offset=0, length=4)
    alias = root.with_name("alias")
    alias.symlink_to(root, target_is_directory=True)
    with pytest.raises(OSError):
        store.write_part(alias, "file", [b"evil"], offset=0, length=4)
    assert list(outside.iterdir()) == []


def test_exclusive_rename_and_install_never_replace_existing_bytes(tmp_path: Path) -> None:
    """The syscall refuses replacement and installation accepts only an equal closed winner."""
    with directory(tmp_path) as parent:
        with candidate(parent, [b"first"]) as first:
            expected = observe(parent, first)
            install(parent, first, parent, "target", expected)
        with candidate(parent, [b"second"]) as second:
            with pytest.raises(FileExistsError):
                rename_exclusive(parent, second, parent, "target")
            with pytest.raises(ValueError, match="conflicts"):
                install(parent, second, parent, "target", observe(parent, second))
    assert (tmp_path / "target").read_bytes() == b"first"
    assert [path.name for path in tmp_path.iterdir()] == ["target"]


def test_zero_progress_write_cleans_candidate_and_allows_retry(
    storage: tuple[PosixRawStore, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stalled copy fails with EIO, removes its candidate and preserves retryable input."""
    store, root = storage
    store.write_part(root, "input", [b"good"], offset=0, length=4)
    with monkeypatch.context() as patch:
        patch.setattr(os, "write", lambda *_: 0)
        with pytest.raises(OSError) as caught:
            _finish(store, root, b"good")
    assert caught.value.errno == errno.EIO
    assert list((root / "completion").iterdir()) == []
    assert not (root / "envelope/payload/nested/file").exists()
    assert (root / "upload/input").read_bytes() == b"good"
    assert _finish(store, root, b"good") == (4, hashlib.sha256(b"good").hexdigest())


@pytest.mark.parametrize("file_id", ["nested/input", "payload/input"])
def test_completion_rejects_upload_ids_that_are_not_single_names(
    storage: tuple[PosixRawStore, Path], file_id: str
) -> None:
    """Completion cannot interpret a path or a payload-prefixed name as an upload ID."""
    store, root = storage
    with pytest.raises(ValueError, match="single file name"):
        store.finish_file(root, file_id, "payload/file", expected_size=0, expected_sha256="0" * 64)
    assert list((root / "completion").iterdir()) == []
    assert list((root / "envelope/payload").iterdir()) == []


@pytest.mark.parametrize(
    "platform, symbol, flags", [("linux", "renameat2", 1), ("darwin", "renameatx_np", 4)]
)
@pytest.mark.parametrize("error", [0, errno.EEXIST, errno.ENOTSUP])
def test_exclusive_rename_dispatches_platform_flags_and_preserves_errno(
    monkeypatch: pytest.MonkeyPatch, platform: str, symbol: str, flags: int, error: int
) -> None:
    """The foreign-function boundary receives exclusive flags and propagates syscall errors."""
    function = Mock(return_value=-1 if error else 0)
    library = Mock(spec=[symbol])
    setattr(library, symbol, function)
    monkeypatch.setattr(materialize.sys, "platform", platform)
    monkeypatch.setattr(materialize.ctypes, "CDLL", Mock(return_value=library))
    monkeypatch.setattr(materialize.ctypes, "get_errno", lambda: error)
    if error:
        with pytest.raises(OSError) as caught:
            rename_exclusive(10, "source", 20, "target")
        assert caught.value.errno == error
        assert caught.value.filename == "target"
    else:
        rename_exclusive(10, "source", 20, "target")
    function.assert_called_once_with(10, b"source", 20, b"target", flags)


def test_exclusive_rename_refuses_unsupported_platform_without_moving_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unknown platforms fail closed and leave the source untouched."""
    source = tmp_path / "source"
    source.write_bytes(b"safe")
    with directory(tmp_path) as parent, monkeypatch.context() as patch:
        patch.setattr(materialize.sys, "platform", "unsupported")
        with pytest.raises(OSError) as caught:
            rename_exclusive(parent, "source", parent, "target")
    assert caught.value.errno == errno.ENOTSUP
    assert source.read_bytes() == b"safe"
    assert not (tmp_path / "target").exists()


def test_cancelled_copy_never_installs_or_removes_another_candidate(tmp_path: Path) -> None:
    """Cancellation closes and removes only the interrupted attempt's private inode."""

    def interrupted() -> Iterator[bytes]:
        yield b"partial"
        raise asyncio.CancelledError

    with directory(tmp_path) as parent, candidate(parent, [b"winner"]) as winner:
        with pytest.raises(asyncio.CancelledError), candidate(parent, interrupted()):
            pytest.fail("cancelled candidate was exposed")
        assert (tmp_path / winner).read_bytes() == b"winner"
        assert [path.name for path in tmp_path.iterdir()] == [winner]
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("failed_directory", ["completion", "payload"])
def test_installed_payload_survives_a_failed_directory_flush_and_retries(
    storage: tuple[PosixRawStore, Path], monkeypatch: pytest.MonkeyPatch, failed_directory: str
) -> None:
    """An install-before-receipt failure retains independent bytes that completion can recover."""
    store, root = storage
    data = b"durable candidate"
    store.write_part(root, "input", [data], offset=0, length=len(data))
    installed = root / "envelope/payload/file"
    watched = root / ("completion" if failed_directory == "completion" else "envelope/payload")
    identity = watched.stat()
    real_fsync = os.fsync

    def fail_after_install(descriptor: int) -> None:
        info = os.fstat(descriptor)
        if installed.exists() and (info.st_dev, info.st_ino) == (identity.st_dev, identity.st_ino):
            raise OSError(errno.EIO, "installed directory flush failed")
        real_fsync(descriptor)

    with monkeypatch.context() as patch:
        patch.setattr(os, "fsync", fail_after_install)
        with pytest.raises(OSError, match="installed directory flush failed"):
            _finish(store, root, data, "payload/file")
    inode = installed.stat().st_ino
    log = fsync_log(monkeypatch)
    assert _finish(store, root, data, "payload/file") == (
        len(data),
        hashlib.sha256(data).hexdigest(),
    )
    assert {root / "completion", installed.parent} <= set(log)
    assert installed.stat().st_ino == inode
    assert installed.stat().st_nlink == 1
    assert installed.read_bytes() == data
    assert list((root / "completion").iterdir()) == []
