"""Real descriptor and concurrent completion contracts for independent payloads."""

from __future__ import annotations

import asyncio
import ctypes
import errno
import fcntl
import hashlib
import os
import stat
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest

from huron.core.rawstore import PosixRawStore, materialize
from huron.core.rawstore.materialize import candidate, directory, install, observe, rename_exclusive
from tests.unit.support import crash_on, fsync_log

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = pytest.mark.unit


@pytest.fixture
def storage(tmp_path: Path) -> tuple[PosixRawStore, Path]:
    """Create the fixed private session roots once."""
    store = PosixRawStore(tmp_path, max_concurrent_completions=2)
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


def _watch_installs(
    monkeypatch: pytest.MonkeyPatch, expected: bytes, barrier: Barrier | None = None
) -> list[tuple[int, int, int]]:
    observations: list[tuple[int, int, int]] = []
    real_library = ctypes.CDLL
    symbol = "renameatx_np" if sys.platform == "darwin" else "renameat2"

    def library(*args: object, **kwargs: object) -> SimpleNamespace:
        native = getattr(real_library(*args, **kwargs), symbol)

        def rename(
            source_dir: int, source: bytes, target_dir: int, target: bytes, flags: int
        ) -> int:
            info = os.stat(source, dir_fd=source_dir)
            for entry in os.listdir("/dev/fd"):
                descriptor = int(entry)
                try:
                    opened = os.fstat(descriptor)
                    access = fcntl.fcntl(descriptor, fcntl.F_GETFL) & os.O_ACCMODE
                except OSError as error:
                    assert error.errno == errno.EBADF
                    continue
                if (opened.st_dev, opened.st_ino) == (info.st_dev, info.st_ino):
                    assert access == os.O_RDONLY, "candidate still has a writable descriptor"
            descriptor = os.open(source, os.O_RDONLY, dir_fd=source_dir)
            with os.fdopen(descriptor, "rb") as copied:
                assert copied.read() == expected
            assert info.st_nlink == 1
            assert info.st_mode & 0o222 == 0
            if barrier is not None:
                barrier.wait(timeout=10)
            result = native(source_dir, source, target_dir, target, flags)
            error = ctypes.get_errno()
            installed = os.stat(target, dir_fd=target_dir)
            observations.append((info.st_ino, result, installed.st_ino))
            ctypes.set_errno(error)
            return result

        return SimpleNamespace(**{symbol: rename})

    monkeypatch.setattr(ctypes, "CDLL", library)
    return observations


@pytest.mark.parametrize("data", [b"", b"one", b"a" * (2**20 + 7)])
def test_completion_installs_a_closed_sealed_independent_inode(
    storage: tuple[PosixRawStore, Path], data: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The payload has verified bytes and no inode or writable handle shared with upload."""
    store, root = storage
    store.write_part(root, "input", [data], offset=0, length=len(data))
    observations = _watch_installs(monkeypatch, data)
    source = root / "upload/input"
    held = os.open(source, os.O_WRONLY)
    try:
        assert _finish(store, root, data) == (len(data), hashlib.sha256(data).hexdigest())
        payload = root / "envelope/payload/nested/file"
        assert observations == [(payload.stat().st_ino, 0, payload.stat().st_ino)]
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


def test_overlapping_completions_converge_on_one_inode(
    storage: tuple[PosixRawStore, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two closed independent candidates race installation without replacing the winner."""
    store, root = storage
    data = b"same bytes"
    store.write_part(root, "input", [data], offset=0, length=len(data))
    with monkeypatch.context() as patch:
        installs = _watch_installs(patch, data, Barrier(2))
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(_finish, store, root, data) for _ in range(2)]
            observations = [future.result(timeout=10) for future in futures]
    assert observations == [(len(data), hashlib.sha256(data).hexdigest())] * 2
    installed = root / "envelope/payload/nested/file"
    inode = installed.stat().st_ino
    assert len({source for source, _, _ in installs}) == 2
    assert sorted(result for _, result, _ in installs) == [-1, 0]
    assert {target for _, _, target in installs} == {inode}
    assert inode != (root / "upload/input").stat().st_ino
    assert _finish(store, root, data) == observations[0]
    assert installed.stat().st_ino == inode
    assert installed.read_bytes() == data
    assert installed.stat().st_nlink == 1
    assert list((root / "completion").iterdir()) == []


def test_immutable_documents_have_no_writable_candidate_at_installation(
    storage: tuple[PosixRawStore, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Immutable document exposure requires a sealed inode with every writer closed."""
    store, root = storage
    installs = _watch_installs(monkeypatch, b"{}")
    store.write_document(root / "envelope", "metadata.json", b"{}")
    document = root / "envelope/metadata.json"
    assert installs == [(document.stat().st_ino, 0, document.stat().st_ino)]
    assert document.read_bytes() == b"{}"
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


@pytest.mark.parametrize("action", ["complete", "document"])
def test_held_candidate_writer_cannot_change_a_relocated_and_published_envelope(
    storage: tuple[PosixRawStore, Path], monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    """A real writer paused with open descriptors cannot replace published inodes on resumption."""
    store, root = storage
    data = b"verified bytes"
    store.write_part(root, "input", [data], offset=0, length=len(data))
    waiting, resume = Event(), Event()
    original_write = os.write

    def held_write(descriptor: int, content: bytes) -> int:
        count = original_write(descriptor, content)
        if not waiting.is_set():
            waiting.set()
            assert resume.wait(10)
        return count

    with monkeypatch.context() as patch, ThreadPoolExecutor(max_workers=1) as executor:
        patch.setattr(os, "write", held_write)
        pending = (
            executor.submit(_finish, store, root, data)
            if action == "complete"
            else executor.submit(store.write_document, root / "envelope", "metadata.json", b"{}")
        )
        try:
            assert waiting.wait(10)
            relocated = root.with_name("relocated")
            root.rename(relocated)
            _finish(store, relocated, data)
            store.write_document(relocated / "envelope", "metadata.json", b"{}")
            store.write_document(relocated / "envelope", "COMMITTED", b"marker")
            store.seal(relocated / "envelope")
            final = store.root / "organization/final"
            store.commit_envelope(relocated / "envelope", final)
            before = {
                path.relative_to(final): (path.stat().st_ino, path.read_bytes())
                for path in final.rglob("*")
                if path.is_file()
            }
        finally:
            resume.set()
        try:
            pending.result(timeout=10)
        except OSError as error:
            assert error.errno in {errno.EACCES, errno.EPERM}
    assert not root.exists()
    assert not (relocated / "envelope").exists()
    assert list((relocated / "completion").iterdir()) == []
    assert {
        path.relative_to(final): (path.stat().st_ino, path.read_bytes())
        for path in final.rglob("*")
        if path.is_file()
    } == before


@pytest.mark.parametrize("parts", [(), ("nested",), ("nested", "deep")])
def test_descendant_creates_only_requested_directories_and_closes_its_descriptor(
    tmp_path: Path, parts: tuple[str, ...]
) -> None:
    """Empty and nested traversal retain the ancestor and close only the borrowed descriptor."""
    with directory(tmp_path) as root:
        for create in (True, False):
            with materialize.descendant(root, parts, create=create) as child:
                assert os.fstat(child).st_ino == tmp_path.joinpath(*parts).stat().st_ino
            with pytest.raises(OSError) as caught:
                os.fstat(child)
            assert caught.value.errno == errno.EBADF
            assert os.fstat(root).st_ino == tmp_path.stat().st_ino


@pytest.mark.parametrize("kind", ["missing", "file", "symlink"])
def test_descendant_refuses_missing_or_non_directory_components(tmp_path: Path, kind: str) -> None:
    """Traversal fails without following links or closing the caller's root."""
    target = tmp_path / "target"
    if kind == "file":
        target.write_bytes(b"safe")
    elif kind == "symlink":
        target.symlink_to(tmp_path, target_is_directory=True)
    with directory(tmp_path) as root:
        with pytest.raises(OSError), materialize.descendant(root, ("target",)):
            pytest.fail("unsafe directory accepted")
        assert os.fstat(root).st_ino == tmp_path.stat().st_ino


@pytest.mark.parametrize("data", [b"", b"small", b"x" * (2**20 + 1)])
def test_file_chunks_streams_exact_bytes_in_bounded_blocks(tmp_path: Path, data: bytes) -> None:
    """Empty and multiblock files are read exactly without changing their inode or bytes."""
    path = tmp_path / "input"
    path.write_bytes(data)
    with directory(tmp_path) as root:
        chunks = list(materialize.file_chunks(root, "input"))
    assert b"".join(chunks) == data
    assert all(0 < len(chunk) <= 2**20 for chunk in chunks)
    assert path.read_bytes() == data


@pytest.mark.parametrize("operation", ["chunks", "flush"])
@pytest.mark.parametrize("kind", ["fifo", "hardlink", "symlink", "foreign"])
def test_file_read_and_flush_refuse_unsafe_inodes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str, kind: str
) -> None:
    """Reading and flushing refuse special, shared, linked and foreign-owned input."""
    target = tmp_path / "input"
    if kind == "fifo":
        os.mkfifo(target)
    elif kind == "symlink":
        target.symlink_to(tmp_path / "absent")
    else:
        target.write_bytes(b"safe")
        if kind == "hardlink":
            os.link(target, tmp_path / "alias")
        else:
            owner = os.geteuid()
            monkeypatch.setattr(os, "geteuid", lambda: owner + 1)
    with directory(tmp_path) as root, pytest.raises((OSError, ValueError)):
        if operation == "chunks":
            list(materialize.file_chunks(root, "input"))
        else:
            materialize.flush_tree(root, seal=True)


@pytest.mark.parametrize("seal", [False, True])
@pytest.mark.parametrize("empty", [False, True])
def test_flush_tree_preserves_bytes_and_seals_only_descendants(
    tmp_path: Path, seal: bool, empty: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Flush reaches every inode, including an empty root, without sealing the root itself."""
    if not empty:
        (tmp_path / "nested").mkdir()
        (tmp_path / "nested/file").write_bytes(b"safe")
    original_mode = stat.S_IMODE(tmp_path.stat().st_mode)
    log = fsync_log(monkeypatch)
    with directory(tmp_path) as root:
        materialize.flush_tree(root, seal=seal)
    assert set(log) == {tmp_path, *tmp_path.rglob("*")}
    assert stat.S_IMODE(tmp_path.stat().st_mode) == original_mode
    if not empty:
        assert (tmp_path / "nested/file").read_bytes() == b"safe"
        assert bool((tmp_path / "nested").stat().st_mode & 0o222) is not seal
        assert bool((tmp_path / "nested/file").stat().st_mode & 0o222) is not seal


@pytest.mark.parametrize("operation", ["read", "fsync", "fchmod", "mkdir"])
def test_descriptor_operations_propagate_io_failure_and_leave_the_root_usable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    """Failed reads, flushes, seals and traversal creation do not leak borrowed descriptors."""
    (tmp_path / "input").write_bytes(b"safe")
    closed: list[int] = []
    original_close = os.close

    def close(descriptor: int) -> None:
        closed.append(descriptor)
        original_close(descriptor)

    with directory(tmp_path) as root, monkeypatch.context() as patch:
        patch.setattr(os, "close", close)
        crash_on(patch, operation)
        with pytest.raises(OSError) as caught:
            if operation == "read":
                list(materialize.file_chunks(root, "input"))
            elif operation == "mkdir":
                with materialize.descendant(root, ("new",), create=True):
                    pytest.fail("failed creation yielded a directory")
            else:
                materialize.flush_tree(root, seal=operation == "fchmod")
        assert caught.value.errno == errno.EIO
        assert closed
        assert root not in closed
        for descriptor in closed:
            with pytest.raises(OSError) as invalid:
                os.fstat(descriptor)
            assert invalid.value.errno == errno.EBADF
        assert os.fstat(root).st_ino == tmp_path.stat().st_ino
    assert (tmp_path / "input").read_bytes() == b"safe"


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


def _killed_completion(root: str, checkpoint: str) -> None:
    from pathlib import Path

    session = Path(root)
    installed = session / "envelope/payload/nested/file"
    original_write, original_fsync = os.write, os.fsync

    def written(descriptor: int, data: bytes) -> int:
        count = original_write(descriptor, data)
        if checkpoint == "copy":
            os._exit(91)
        return count

    def flushed(descriptor: int) -> None:
        original_fsync(descriptor)
        if (checkpoint == "fsync" and stat.S_ISREG(os.fstat(descriptor).st_mode)) or (
            checkpoint == "install" and installed.exists()
        ):
            os._exit(91)

    os.write, os.fsync = written, flushed
    _finish(PosixRawStore(session.parent.parent), session, b"verified bytes")
    os._exit(91)


@pytest.mark.parametrize("checkpoint", ["copy", "fsync", "install", "complete"])
def test_process_death_leaves_only_unpublished_candidates_or_verified_payload(
    storage: tuple[PosixRawStore, Path], checkpoint: str
) -> None:
    """Abrupt death bypasses cleanup, and retry never publishes leftover candidates."""
    store, root = storage
    data = b"verified bytes"
    store.write_part(root, "input", [data], offset=0, length=len(data))
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "from tests.unit.test_rawstore_materialize import _killed_completion; "
            "import sys; _killed_completion(sys.argv[1], sys.argv[2])",
            str(root),
            checkpoint,
        ],
        check=False,
        capture_output=True,
        timeout=20,
    )
    assert completed.returncode == 91, completed.stderr.decode()
    leftover = {path.name: path.read_bytes() for path in (root / "completion").iterdir()}
    assert bool(leftover) == (checkpoint in {"copy", "fsync"})
    installed = root / "envelope/payload/nested/file"
    assert installed.exists() == (checkpoint in {"install", "complete"})
    assert _finish(store, root, data) == (len(data), hashlib.sha256(data).hexdigest())
    assert {path.name: path.read_bytes() for path in (root / "completion").iterdir()} == leftover
    store.write_document(root / "envelope", "COMMITTED", b"marker")
    store.seal(root / "envelope")
    final = store.root / "organization/final"
    store.commit_envelope(root / "envelope", final)
    assert (final / "payload/nested/file").read_bytes() == data
    assert (final / "payload/nested/file").stat().st_nlink == 1
    assert sorted(path.name for path in final.iterdir()) == ["COMMITTED", "payload"]


def test_exclusive_rename_refuses_a_system_library_without_the_required_symbol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An older system library cannot silently substitute a replacing rename."""
    monkeypatch.setattr(materialize.sys, "platform", "linux")
    monkeypatch.setattr(materialize.ctypes, "CDLL", lambda *args, **kwargs: object())
    with pytest.raises(OSError) as caught:
        rename_exclusive(1, "source", 2, "target")
    assert caught.value.errno == errno.ENOTSUP


@pytest.mark.parametrize(
    "operation", ["write", "finish", "document", "discard", "seal", "inspect", "begin"]
)
def test_session_operations_refuse_a_relocated_staging_ancestor(
    storage: tuple[PosixRawStore, Path], operation: str
) -> None:
    """A staging-prefix link cannot redirect session operations outside the trusted root."""
    store, root = storage
    store.write_part(root, "input", [b"bytes"], offset=0, length=5)
    relocated = store.root / "relocated"
    root.parent.rename(relocated)
    root.parent.symlink_to(relocated, target_is_directory=True)
    with pytest.raises(OSError):
        if operation == "write":
            store.write_part(root, "input", [b"other"], offset=0, length=5)
        elif operation == "finish":
            _finish(store, root, b"bytes")
        elif operation == "document":
            store.write_document(root / "envelope", "COMMITTED", b"marker")
        elif operation == "discard":
            store.discard_file(root, "input")
        elif operation == "seal":
            store.seal(root / "envelope")
        elif operation == "inspect":
            store.verify_envelope(root / "envelope", [], {})
        else:
            store.create_staging(root.parent / "new-session")
    assert (relocated / "session/upload/input").read_bytes() == b"bytes"
    assert list((relocated / "session/completion").iterdir()) == []
    assert not (relocated / "session/envelope/COMMITTED").exists()
    assert not (relocated / "new-session").exists()


def test_publication_refuses_a_link_in_the_final_hierarchy(
    storage: tuple[PosixRawStore, Path],
) -> None:
    """A final hierarchy prefix cannot redirect publication or create escaped parents."""
    store, root = storage
    store.write_document(root / "envelope", "COMMITTED", b"marker")
    relocated = store.root / "relocated"
    (store.root / "organization").rename(relocated)
    (store.root / "organization").symlink_to(relocated, target_is_directory=True)
    with pytest.raises(OSError):
        store.commit_envelope(root / "envelope", store.root / "organization/project/revision")
    assert list(relocated.iterdir()) == []
    assert (root / "envelope/COMMITTED").read_bytes() == b"marker"


@pytest.mark.parametrize("name", ["fifo", "linked"])
def test_sealing_refuses_special_or_shared_files(
    storage: tuple[PosixRawStore, Path], name: str
) -> None:
    """Sealing cannot hang on a FIFO or change permissions on a shared inode."""
    store, root = storage
    path = root / "envelope/payload" / name
    if name == "fifo":
        os.mkfifo(path)
    else:
        source = root / "upload/input"
        source.write_bytes(b"bytes")
        os.link(source, path)
    with pytest.raises(ValueError, match="unsafe file"):
        store.seal(root / "envelope")


def test_directory_traversal_refuses_parent_escape(storage: tuple[PosixRawStore, Path]) -> None:
    """An anchored directory path cannot traverse a parent component."""
    store, _ = storage
    with (
        pytest.raises(ValueError, match="escapes"),
        materialize.directory(store.root / "..", anchor=store.root),
    ):
        pytest.fail("escaped the trusted root")
