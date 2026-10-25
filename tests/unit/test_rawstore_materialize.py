"""Descriptor safety, complete writes and durable directory operations."""

from __future__ import annotations

import errno
import hashlib
import os
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest

from huron.core.rawstore import materialize
from huron.core.rawstore.materialize import (
    directory,
    fsync_dir,
    observe,
    rename_exclusive,
    write_all,
)
from tests.unit.support import crash_on, fsync_log

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


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


def test_exclusive_rename_refuses_a_system_library_without_the_required_symbol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An older system library cannot silently substitute a replacing rename."""
    monkeypatch.setattr(materialize.sys, "platform", "linux")
    monkeypatch.setattr(materialize.ctypes, "CDLL", lambda *args, **kwargs: object())
    with pytest.raises(OSError) as caught:
        rename_exclusive(1, "source", 2, "target")
    assert caught.value.errno == errno.ENOTSUP


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


@pytest.mark.parametrize("parts", [(), ("nested", "deep")])
def test_anchored_directory_holds_the_requested_descendant(
    tmp_path: Path, parts: tuple[str, ...]
) -> None:
    """Anchored traversal opens the exact directory and closes its descriptor."""
    path = tmp_path.joinpath(*parts)
    path.mkdir(parents=True, exist_ok=True)
    with directory(path, anchor=tmp_path) as descriptor:
        assert os.fstat(descriptor).st_ino == path.stat().st_ino
    with pytest.raises(OSError):
        os.fstat(descriptor)


def test_directory_traversal_refuses_parent_escape(tmp_path: Path) -> None:
    """An anchored directory path cannot traverse a parent component."""
    with pytest.raises(ValueError, match="escapes"), directory(tmp_path / "..", anchor=tmp_path):
        pytest.fail("escaped the trusted root")


@pytest.mark.parametrize("operation", ["read", "fsync", "mkdir"])
def test_descriptor_operations_propagate_io_failure_and_leave_the_root_usable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    """Failed reads and traversal creation close borrowed descriptors and preserve the root."""
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
                observe(root, "input", sealed=False)
            else:
                with materialize.descendant(root, ("new",), create=True):
                    pytest.fail("failed creation yielded a directory")
        assert caught.value.errno == errno.EIO
        assert closed
        assert root not in closed
        for descriptor in closed:
            with pytest.raises(OSError) as invalid:
                os.fstat(descriptor)
            assert invalid.value.errno == errno.EBADF
        assert os.fstat(root).st_ino == tmp_path.stat().st_ino
    assert (tmp_path / "input").read_bytes() == b"safe"


@pytest.mark.parametrize("data", [b"", b"small", b"x" * (2**20 + 1)])
@pytest.mark.parametrize("sealed", [True, False])
def test_observe_hashes_complete_regular_file_bytes(
    tmp_path: Path, data: bytes, sealed: bool
) -> None:
    """Empty and multiblock files yield their exact size and digest without mutation."""
    path = tmp_path / "file"
    path.write_bytes(data)
    path.chmod(0o444 if sealed else 0o600)
    with directory(tmp_path) as parent:
        assert observe(parent, "file", sealed=sealed) == (
            len(data),
            hashlib.sha256(data).hexdigest(),
        )
    assert path.read_bytes() == data


@pytest.mark.parametrize("kind", ["fifo", "hardlink", "symlink", "foreign", "writable"])
def test_observe_refuses_unsafe_inodes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    """Observation refuses special, shared, linked, foreign-owned and unsealed files."""
    path = tmp_path / "file"
    if kind == "fifo":
        os.mkfifo(path)
    elif kind == "symlink":
        path.symlink_to(tmp_path / "absent")
    else:
        path.write_bytes(b"safe")
        if kind != "writable":
            path.chmod(0o444)
        if kind == "hardlink":
            os.link(path, tmp_path / "alias")
        elif kind == "foreign":
            owner = os.geteuid()
            monkeypatch.setattr(os, "geteuid", lambda: owner + 1)
    with directory(tmp_path) as parent, pytest.raises((OSError, ValueError)):
        observe(parent, "file")


@pytest.mark.parametrize("offset", [None, 6])
def test_short_writes_complete_bytes_and_stalls_refuse_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, offset: int | None
) -> None:
    """Both write modes complete short writes, preserve adjacent bytes and refuse zero progress."""
    path = tmp_path / "file"
    path.write_bytes(b"prefix------suffix")
    descriptor = os.open(path, os.O_WRONLY)
    original_write, original_pwrite = os.write, os.pwrite
    try:
        with monkeypatch.context() as patch:
            patch.setattr(os, "write", lambda fd, data: original_write(fd, data[:2]))
            patch.setattr(
                os, "pwrite", lambda fd, data, position: original_pwrite(fd, data[:2], position)
            )
            write_all(descriptor, b"middle", offset=offset)
        assert path.read_bytes() == (
            b"middle------suffix" if offset is None else b"prefixmiddlesuffix"
        )
        with monkeypatch.context() as patch:
            patch.setattr(os, "write", lambda *_: 0)
            patch.setattr(os, "pwrite", lambda *_: 0)
            with pytest.raises(OSError) as caught:
                write_all(descriptor, b"replacement", offset=offset)
            assert caught.value.errno == errno.EIO
    finally:
        os.close(descriptor)


def test_exclusive_rename_moves_a_file_and_refuses_existing_bytes(tmp_path: Path) -> None:
    """Exclusive rename moves the source once and never replaces an existing target."""
    (tmp_path / "source").write_bytes(b"first")
    with directory(tmp_path) as parent:
        rename_exclusive(parent, "source", parent, "target")
        assert not (tmp_path / "source").exists()
        (tmp_path / "source").write_bytes(b"second")
        with pytest.raises(FileExistsError):
            rename_exclusive(parent, "source", parent, "target")
    assert (tmp_path / "target").read_bytes() == b"first"
    assert (tmp_path / "source").read_bytes() == b"second"
