"""POSIX descriptor primitives on a real temporary filesystem."""

import asyncio
import errno
import hashlib
import os
import stat
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from huron.pkg.fs import posix
from huron.pkg.hashing import EMPTY_SHA256
from tests.support.disk import (
    WRITE_CLEANUP_FAILURES,
    cleanup_notes,
    exception_chain,
    fail_file_io,
    fail_write_cleanup,
    snapshot,
)

PART = ".a.bin.1.huron-part"


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


def names_in(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir())


def copy_source(lake: Path, parent_fd: int, name: str) -> object:
    """Copy ``up/src`` to ``name`` in ``parent_fd``."""
    source = os.open(lake / "up" / "src", os.O_RDONLY)
    try:
        return posix.copy_sealed(source, parent_fd, name, 3, 0o644)
    finally:
        os.close(source)


def link_once_source(lake: Path, parent_fd: int, name: str) -> object:
    """Link ``up/src`` to the new name ``name`` in ``parent_fd``."""
    with parent(lake, "up") as source_fd:
        posix.link_once(source_fd, "src", parent_fd, name)
    return None


PRIMITIVES: dict[str, Callable[[Path, int, str], object]] = {
    "entry": lambda lake, fd, name: posix.entry(fd, name),
    "open_file": lambda lake, fd, name: posix.open_file(fd, name),
    "open_directory": lambda lake, fd, name: posix.open_directory(fd, name),
    "change_mode": lambda lake, fd, name: posix.change_mode(fd, name, 0o600),
    "change_group": lambda lake, fd, name: posix.change_group(fd, name, os.getgid()),
    "make_dir": lambda lake, fd, name: posix.make_dir(fd, name, 0o750),
    "make_inheriting_dir": lambda lake, fd, name: posix.make_inheriting_dir(fd, name),
    "atomic_write": lambda lake, fd, name: posix.atomic_write(fd, name, b"x", 0o644, PART),
    "copy_sealed": copy_source,
    "link_once": link_once_source,
    "sync_directory": lambda lake, fd, name: posix.sync_directory(fd, name),
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


def test_make_inheriting_dir_refuses_a_mode_that_the_umask_cut(
    lake: Path, setgid_dir: Path
) -> None:
    os.umask(0o077)
    with parent(lake, "a") as fd, pytest.raises(posix.InheritanceError) as refused:
        posix.make_inheriting_dir(fd, "d")
    assert refused.value.strerror == "the directory has the mode 2700, not 2750"
    assert not (setgid_dir / "d").exists()


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


def test_atomic_write_refuses_a_directory_at_the_part_file_and_changes_nothing(
    lake: Path,
) -> None:
    (lake / "a" / PART).mkdir()
    (lake / "a" / PART / "keep").write_bytes(b"keep")
    with parent(lake, "a") as fd, pytest.raises(posix.PartBlocked) as refused:
        posix.atomic_write(fd, "m.json", b"x", 0o644, PART)
    assert (refused.value.errno, refused.value.filename) == (errno.EISDIR, PART)
    assert names_in(lake / "a") == [PART]
    assert (lake / "a" / PART / "keep").read_bytes() == b"keep"


@pytest.mark.parametrize(
    "operation", ["stat", "unlink", "open", "fchmod", "write", "fsync", "close"]
)
@pytest.mark.parametrize("number", [errno.EIO, errno.EACCES])
def test_atomic_write_keeps_the_error_origin_and_old_bytes(
    lake: Path, monkeypatch: pytest.MonkeyPatch, operation: str, number: int
) -> None:
    target = lake / "a" / "m.json"
    target.write_bytes(b"old")
    (lake / "a" / PART).write_bytes(b"stale")
    with parent(lake, "a") as fd:
        fail_file_io(monkeypatch, operation, PART, number)
        with pytest.raises(OSError) as refused:
            posix.atomic_write(fd, "m.json", b"new", 0o644, PART)
    error = refused.value
    assert error.errno == number
    if number == errno.EACCES and operation in {"open", "unlink"}:
        assert isinstance(error, PermissionError)
    else:
        assert isinstance(error, posix.FileError)
        assert error.filename == PART
        assert error.error.errno == number
    assert target.read_bytes() == b"old"


@pytest.mark.parametrize("operation", ["stat", "rename"])
def test_atomic_write_does_not_attribute_target_or_replace_errors_to_the_part(
    lake: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    target = lake / "a" / "m.json"
    target.write_bytes(b"old")
    with parent(lake, "a") as fd:
        fail_file_io(monkeypatch, operation, "m.json" if operation == "stat" else PART, errno.EIO)
        with pytest.raises(OSError) as refused:
            posix.atomic_write(fd, "m.json", b"new", 0o644, PART)
    assert not isinstance(refused.value, posix.FileError)
    assert refused.value.errno == errno.EIO
    assert target.read_bytes() == b"old"


@pytest.mark.parametrize("operation,cleanup", WRITE_CLEANUP_FAILURES)
@pytest.mark.parametrize(
    "number,secondary_number",
    [
        (errno.ENOSPC, errno.EIO),
        (errno.EIO, errno.EACCES),
        (errno.EACCES, errno.ENOSPC),
        (errno.ENOENT, errno.EPERM),
        (errno.EINTR, errno.EBADF),
    ],
)
def test_atomic_write_keeps_the_primary_error_when_cleanup_also_fails(
    lake: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    cleanup: tuple[str, ...],
    number: int,
    secondary_number: int,
) -> None:
    target = lake / "a" / "m.json"
    target.write_bytes(b"old")
    old_inode = target.stat().st_ino
    with parent(lake, "a") as fd, monkeypatch.context() as patch:
        primary, *secondary = fail_write_cleanup(
            patch, PART, operation, cleanup, number, secondary_number
        )
        original_message = str(primary)
        with pytest.raises(OSError) as refused:
            posix.atomic_write(fd, "m.json", b"new", 0o640, PART)
    error = refused.value
    assert exception_chain(error)[-1] is primary
    assert (error.errno, error.strerror) == (number, os.strerror(number))
    assert str(primary) == original_message
    if operation == "rename" or (operation == "open" and number == errno.EACCES):
        assert error is primary
    else:
        assert isinstance(error, posix.FileError)
        assert error.filename == PART
        assert error.error is primary
    expected = [
        f"{'close' if action == 'close' else 'remove'} {PART!r} failed: "
        f"[Errno {secondary_number}] {os.strerror(secondary_number)}"
        for action in cleanup
    ]
    assert sorted(cleanup_notes(error)) == sorted(expected)
    assert all(fault.__traceback__ is not None for fault in secondary)
    assert (target.read_bytes(), target.stat().st_ino) == (b"old", old_inode)
    assert (lake / "a" / PART).exists() == (operation != "open" and cleanup != ("close",))
    with parent(lake, "a") as fd:
        posix.atomic_write(fd, "m.json", b"new", 0o640, PART)
    assert target.read_bytes() == b"new"
    assert stat.S_IMODE(target.stat().st_mode) == 0o640
    assert names_in(lake / "a") == ["m.json"]


@pytest.mark.parametrize("operation", ["fchmod", "write", "fsync", "rename"])
@pytest.mark.parametrize(
    "kind", [asyncio.CancelledError, KeyboardInterrupt, SystemExit, GeneratorExit]
)
def test_atomic_write_preserves_interruption_during_failing_cleanup(
    lake: Path, monkeypatch: pytest.MonkeyPatch, operation: str, kind: type[BaseException]
) -> None:
    target = lake / "a" / "m.json"
    target.write_bytes(b"old")
    interruption = kind("interrupted")
    with parent(lake, "a") as fd, monkeypatch.context() as patch:
        fail_file_io(patch, operation, PART, interruption)
        if operation != "rename":
            fail_file_io(patch, "close", PART, errno.EIO)
        fail_file_io(patch, "unlink", PART, errno.EACCES)
        with pytest.raises(kind) as refused:
            posix.atomic_write(fd, "m.json", b"new", 0o644, PART)
    assert refused.value is interruption
    assert len(cleanup_notes(interruption)) == (1 if operation == "rename" else 2)
    assert target.read_bytes() == b"old"
    with parent(lake, "a") as fd:
        posix.atomic_write(fd, "m.json", b"new", 0o644, PART)
    assert target.read_bytes() == b"new"
    assert not (lake / "a" / PART).exists()


@pytest.mark.parametrize("cleanup", ["close", "stat", "unlink"])
@pytest.mark.parametrize(
    "kind", [asyncio.CancelledError, KeyboardInterrupt, SystemExit, GeneratorExit]
)
def test_atomic_write_does_not_suppress_an_interruption_in_cleanup(
    lake: Path, monkeypatch: pytest.MonkeyPatch, cleanup: str, kind: type[BaseException]
) -> None:
    target = lake / "a" / "m.json"
    target.write_bytes(b"old")
    interruption = kind("cleanup interrupted")
    with parent(lake, "a") as fd, monkeypatch.context() as patch:
        primary = fail_file_io(patch, "fsync", PART, errno.ENOSPC)
        fail_file_io(patch, cleanup, PART, interruption, after=2 if cleanup == "stat" else 0)
        with pytest.raises(kind) as refused:
            posix.atomic_write(fd, "m.json", b"new", 0o644, PART)
    assert refused.value is interruption
    assert primary.__traceback__ is not None
    assert target.read_bytes() == b"old"
    with parent(lake, "a") as fd:
        posix.atomic_write(fd, "m.json", b"new", 0o644, PART)
    assert target.read_bytes() == b"new"


@pytest.mark.parametrize("operation", ["fchmod", "write", "fsync", "rename"])
def test_parent_close_cannot_replace_a_write_error_or_its_cleanup_diagnostics(
    lake: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    target = lake / "a" / "m.json"
    target.write_bytes(b"old")
    with monkeypatch.context() as patch, pytest.raises(OSError) as refused, parent(lake, "a") as fd:
        primary, secondary = fail_write_cleanup(patch, PART, operation, ("unlink",), errno.ENOSPC)
        closed = fail_file_io(patch, "close", "a", errno.EIO)
        posix.atomic_write(fd, "m.json", b"new", 0o644, PART)
    assert exception_chain(refused.value)[-1] is primary
    assert refused.value.errno == errno.ENOSPC
    assert sorted(cleanup_notes(refused.value)) == sorted(
        [
            f"remove {PART!r} failed: [Errno 5] Input/output error",
            "close parent directory failed: [Errno 5] Input/output error",
        ]
    )
    assert secondary.__traceback__ is not None and closed.__traceback__ is not None
    with pytest.raises(OSError) as released:
        os.fstat(fd)
    assert released.value.errno == errno.EBADF
    assert target.read_bytes() == b"old"


@pytest.mark.parametrize("name", [PART, "a"])
def test_a_close_failure_never_retries_a_descriptor_that_can_be_reused(
    lake: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    target = lake / "a" / "m.json"
    target.write_bytes(b"old")
    real_close = os.close
    replacements: list[int] = []
    fault = OSError(errno.EINTR, "interrupted close", "/untrusted/elsewhere")

    def closing(descriptor: int) -> None:
        actual = Path(os.readlink(f"/proc/self/fd/{descriptor}")).name
        real_close(descriptor)
        if actual == name and not replacements:
            replacement = os.open(lake.parent / "outside" / "file", os.O_RDONLY)
            if replacement != descriptor:
                os.dup2(replacement, descriptor)
                real_close(replacement)
                replacement = descriptor
            replacements.append(replacement)
            assert replacement == descriptor
            raise fault

    try:
        with (
            monkeypatch.context() as patch,
            pytest.raises(OSError) as refused,
            parent(lake, "a") as fd,
        ):
            patch.setattr(os, "close", closing)
            posix.atomic_write(fd, "m.json", b"new", 0o644, PART)
        assert exception_chain(refused.value)[-1] is fault
        assert cleanup_notes(refused.value) == []
        assert len(replacements) == 1
        assert os.read(replacements[0], 4) == b"keep"
        assert target.read_bytes() == (b"old" if name == PART else b"new")
        assert not (lake / "a" / PART).exists()
    finally:
        for descriptor in replacements:
            real_close(descriptor)


@pytest.mark.parametrize("final_close_fails", [False, True])
def test_a_traversal_close_failure_releases_the_new_descriptor_without_retrying_the_old(
    lake: Path, monkeypatch: pytest.MonkeyPatch, final_close_fails: bool
) -> None:
    real_open, real_close = os.open, os.close
    opened: list[int] = []
    replacement: list[int] = []
    fault = OSError(errno.EIO, "close failed")

    def opening(*args: object, **kwargs: object) -> int:
        descriptor = real_open(*args, **kwargs)
        opened.append(descriptor)
        return descriptor

    def closing(descriptor: int) -> None:
        real_close(descriptor)
        if descriptor == opened[0] and not replacement:
            replacement.append(real_open(lake.parent / "outside" / "file", os.O_RDONLY))
            assert replacement[0] == descriptor
            raise fault
        if final_close_fails and descriptor == opened[1]:
            raise OSError(errno.EBADF, "secondary close failure")

    try:
        with monkeypatch.context() as patch, pytest.raises(OSError) as refused:
            patch.setattr(os, "open", opening)
            patch.setattr(os, "close", closing)
            with parent(lake, "a"):
                pytest.fail("A failed traversal cannot yield a directory")
        assert refused.value is fault
        assert cleanup_notes(fault) == (
            ["close parent directory failed: [Errno 9] secondary close failure"]
            if final_close_fails
            else []
        )
        assert len(opened) == 2
        assert os.read(replacement[0], 4) == b"keep"
        with pytest.raises(OSError) as released:
            os.fstat(opened[1])
        assert released.value.errno == errno.EBADF
    finally:
        for descriptor in replacement:
            real_close(descriptor)


def test_an_empty_atomic_write_closes_its_descriptor_and_removes_the_part(lake: Path) -> None:
    with parent(lake, "a") as fd:
        posix.atomic_write(fd, "m.json", b"", 0o640, PART)
    assert (lake / "a" / "m.json").read_bytes() == b""
    assert names_in(lake / "a") == ["m.json"]


@pytest.mark.parametrize("replacement", ["symlink", "directory", "missing"])
def test_failed_write_cleanup_never_removes_an_obstruction_or_follows_a_link(
    lake: Path, monkeypatch: pytest.MonkeyPatch, replacement: str
) -> None:
    target = lake / "a" / "m.json"
    target.write_bytes(b"old")
    part = lake / "a" / PART
    outside = lake.parent / "outside"
    before = snapshot(outside)
    primary = OSError(errno.ENOSPC, "rename failed", "/untrusted/elsewhere")

    def replacing(*args: object, **kwargs: object) -> None:
        part.unlink()
        if replacement == "symlink":
            part.symlink_to(outside / "file")
        elif replacement == "directory":
            part.mkdir()
            (part / "keep").write_bytes(b"keep")
        raise primary

    with parent(lake, "a") as fd, monkeypatch.context() as patch:
        patch.setattr(os, "rename", replacing)
        with pytest.raises(OSError) as refused:
            posix.atomic_write(fd, "m.json", b"new", 0o644, PART)
    assert refused.value is primary
    assert snapshot(outside) == before
    assert target.read_bytes() == b"old"
    if replacement == "symlink":
        assert part.is_symlink()
        assert cleanup_notes(primary) == [f"remove {PART!r} failed: [Errno 40] a symbolic link"]
        part.unlink()
    elif replacement == "directory":
        assert (part / "keep").read_bytes() == b"keep"
        assert cleanup_notes(primary) == [f"remove {PART!r} failed: [Errno 21] Is a directory"]
        (part / "keep").unlink()
        part.rmdir()
    else:
        assert not part.exists()
        assert cleanup_notes(primary) == []
    with parent(lake, "a") as fd:
        posix.atomic_write(fd, "m.json", b"new", 0o644, PART)
    assert target.read_bytes() == b"new"


@pytest.mark.parametrize("operation", ["write", "rename"])
def test_cleanup_preserves_custom_primary_text_existing_notes_and_cause(
    lake: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    primary = OSError(errno.ENOSPC, "primary failure at /other/place", "/untrusted/elsewhere")
    cause = ValueError("original cause")
    primary.__cause__ = cause
    primary.add_note("original diagnostic")
    message = str(primary)
    with parent(lake, "a") as fd, monkeypatch.context() as patch:
        fail_file_io(patch, operation, PART, primary)
        fail_file_io(patch, "unlink", PART, OSError(errno.EIO, "secondary cleanup failure"))
        with pytest.raises(OSError) as refused:
            posix.atomic_write(fd, "m.json", b"new", 0o644, PART)
    assert primary in exception_chain(refused.value)
    assert exception_chain(refused.value)[-1] is cause
    assert primary.__cause__ is cause
    assert str(primary) == message
    assert refused.value.strerror == "primary failure at /other/place"
    assert sorted(cleanup_notes(refused.value)) == sorted(
        ["original diagnostic", f"remove {PART!r} failed: [Errno 5] secondary cleanup failure"]
    )
    assert not (lake / "a" / "m.json").exists()


@pytest.mark.parametrize(
    "kind", [asyncio.CancelledError, KeyboardInterrupt, SystemExit, GeneratorExit]
)
def test_parent_close_retains_an_active_interruption(
    lake: Path, monkeypatch: pytest.MonkeyPatch, kind: type[BaseException]
) -> None:
    interruption = kind("interrupted")
    with monkeypatch.context() as patch, pytest.raises(kind) as refused, parent(lake, "a") as fd:
        fail_file_io(patch, "close", "a", errno.EIO)
        raise interruption
    assert refused.value is interruption
    assert cleanup_notes(interruption) == [
        "close parent directory failed: [Errno 5] Input/output error"
    ]
    with pytest.raises(OSError) as released:
        os.fstat(fd)
    assert released.value.errno == errno.EBADF


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


def test_change_group_changes_the_group_without_following_a_link(
    lake: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    changed: list[tuple[str, int, int, bool]] = []

    def chown(path: str, uid: int, gid: int, *, dir_fd: int, follow_symlinks: bool) -> None:
        changed.append((path, uid, gid, follow_symlinks))

    monkeypatch.setattr(os, "chown", chown)
    other = os.lstat(lake / "up" / "src").st_gid + 1
    with parent(lake, "up") as fd:
        assert posix.change_group(fd, "src", other) is True
        with pytest.raises(FileNotFoundError):
            posix.change_group(fd, "missing", other)
    assert changed == [("src", -1, other, False)]


def test_change_group_reports_a_refused_chown(lake: Path) -> None:
    group = os.lstat(lake / "up" / "src").st_gid
    other = next(gid for gid in range(1, 65536) if gid != group and gid not in os.getgroups())
    with parent(lake, "up") as fd, pytest.raises(posix.ChangeRefused) as refused:
        posix.change_group(fd, "src", other)
    assert (refused.value.errno, refused.value.filename) == (errno.EPERM, "src")
    assert os.lstat(lake / "up" / "src").st_gid == group


@pytest.mark.parametrize("mode", [0o000, 0o2000, 0o300, 0o100])
def test_a_directory_this_process_cannot_read_changes_its_mode_and_group(
    lake: Path, temporary_mode: Callable[[Path, int], None], mode: int
) -> None:
    unreadable = lake / "a" / "d"
    unreadable.mkdir()
    temporary_mode(unreadable, mode)
    gid = os.lstat(unreadable).st_gid
    with parent(lake, "a") as fd:
        assert posix.change_group(fd, "d", gid) is False
        assert posix.change_mode(fd, "d", 0o2750) is True
    assert stat.S_IMODE(os.lstat(unreadable).st_mode) == 0o2750


def test_change_mode_reports_a_filesystem_that_cannot_change_without_following(
    lake: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise ValueError("chmod: cannot use dir_fd and follow_symlinks together")

    monkeypatch.setattr(os, "chmod", refuse)
    with parent(lake, "up") as fd, pytest.raises(OSError) as refused:
        posix.change_mode(fd, "src", 0o600)
    assert not isinstance(refused.value, posix.SymlinkError)
    assert refused.value.errno == errno.EOPNOTSUPP
    assert stat.S_IMODE(os.lstat(lake / "up" / "src").st_mode) != 0o600


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


def copy_to(lake: Path, name: str, size: int = 3) -> posix.SealedFile:
    """Copy ``up/src`` to ``a/<name>`` with mode ``0644``, expecting ``size`` bytes."""
    with parent(lake, "a") as fd:
        source = os.open(lake / "up" / "src", os.O_RDONLY)
        try:
            return posix.copy_sealed(source, fd, name, size, 0o644)
        finally:
            os.close(source)


def test_copy_sealed_writes_a_new_file_and_measures_it_on_a_new_descriptor(lake: Path) -> None:
    os.umask(0o077)
    sealed = copy_to(lake, "c")
    copy = lake / "a" / "c"
    assert sealed == posix.SealedFile(3, hashlib.sha256(b"new").hexdigest(), copy.stat().st_ino)
    assert sealed.inode != (lake / "up" / "src").stat().st_ino
    assert (copy.read_bytes(), stat.S_IMODE(copy.stat().st_mode)) == (b"new", 0o644)


def test_copy_sealed_of_an_empty_file(lake: Path) -> None:
    (lake / "up" / "src").write_bytes(b"")
    assert copy_to(lake, "c", 0).sha256 == EMPTY_SHA256


@pytest.mark.parametrize("kind", ["file", "dir"])
def test_copy_sealed_never_replaces_an_existing_name(lake: Path, kind: str) -> None:
    existing = lake / "a" / "c"
    existing.mkdir() if kind == "dir" else existing.write_bytes(b"old")
    before = snapshot(lake)
    with pytest.raises(FileExistsError) as refused:
        copy_to(lake, "c")
    assert (type(refused.value), refused.value.errno, refused.value.filename) == (
        FileExistsError,
        errno.EEXIST,
        "c",
    )
    assert snapshot(lake) == before


def test_copy_sealed_syncs_the_directory_after_the_file(
    lake: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    synced: list[str] = []
    real = os.fsync

    def recording(descriptor: int) -> None:
        synced.append(Path(os.readlink(f"/proc/self/fd/{descriptor}")).name)
        real(descriptor)

    monkeypatch.setattr(os, "fsync", recording)
    copy_to(lake, "c")
    assert synced == ["c", "a"]


def test_copy_sealed_stops_one_byte_after_the_expected_size(lake: Path) -> None:
    endless = os.open("/dev/zero", os.O_RDONLY)
    try:
        with parent(lake, "a") as fd, pytest.raises(posix.SizeMismatch) as refused:
            posix.copy_sealed(endless, fd, "c", 3, 0o644)
    finally:
        os.close(endless)
    assert type(refused.value) is posix.SizeMismatch
    assert (refused.value.size, refused.value.errno, refused.value.strerror) == (
        4,
        errno.EIO,
        "the copy has 4 bytes",
    )
    assert not (lake / "a" / "c").exists()


def test_copy_sealed_of_other_bytes_than_expected_removes_the_copy(lake: Path) -> None:
    with pytest.raises(posix.SizeMismatch) as refused:
        copy_to(lake, "c", size=5)
    assert type(refused.value) is posix.SizeMismatch
    assert (refused.value.size, refused.value.errno, refused.value.strerror) == (
        3,
        errno.EIO,
        "the copy has 3 bytes",
    )
    assert not (lake / "a" / "c").exists()


@pytest.mark.parametrize(
    ("operation", "name", "after"),
    [
        ("fchmod", "c", 0),
        ("write", "c", 0),
        ("fsync", "c", 0),
        ("close", "c", 0),
        ("open", "c", 1),
        ("fstat", "c", 0),
        ("pread", "c", 0),
        ("fsync", "a", 0),
    ],
)
def test_a_failed_copy_removes_its_file(
    lake: Path, monkeypatch: pytest.MonkeyPatch, operation: str, name: str, after: int
) -> None:
    with monkeypatch.context() as patch:
        primary = fail_file_io(patch, operation, name, errno.ENOSPC, after=after)
        with pytest.raises(OSError) as refused:
            copy_to(lake, "c")
    assert refused.value is primary
    assert cleanup_notes(refused.value) == []
    assert not (lake / "a" / "c").exists()
    assert (lake / "up" / "src").read_bytes() == b"new"


@pytest.mark.parametrize(
    "operation,cleanup",
    [
        ("write", (("close", 0),)),
        ("write", (("unlink", 0),)),
        ("write", (("close", 0), ("unlink", 0))),
        ("fstat", (("close", 1),)),
        ("pread", (("close", 1), ("unlink", 0))),
    ],
)
def test_a_failed_copy_keeps_its_error_when_the_cleanup_fails_too(
    lake: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    cleanup: tuple[tuple[str, int], ...],
) -> None:
    with monkeypatch.context() as patch:
        primary = fail_file_io(patch, operation, "c", errno.ENOSPC)
        for action, after in cleanup:
            fail_file_io(patch, action, "c", errno.EIO, after=after)
        with pytest.raises(OSError) as refused:
            copy_to(lake, "c")
    assert exception_chain(refused.value)[-1] is primary
    notes = cleanup_notes(refused.value)
    assert len(notes) == len(cleanup)
    assert all(note.endswith("failed: [Errno 5] Input/output error") for note in notes)


def test_link_once_gives_the_file_a_new_name_and_never_replaces_one(lake: Path) -> None:
    with parent(lake, "a") as fd:
        link_once_source(lake, fd, "l")
        assert (lake / "a" / "l").stat().st_ino == (lake / "up" / "src").stat().st_ino
        (lake / "a" / "d").mkdir()
        for name in ("l", "d"):
            with pytest.raises(FileExistsError) as refused:
                link_once_source(lake, fd, name)
            assert (type(refused.value), refused.value.errno) == (FileExistsError, errno.EEXIST)


def test_link_once_across_two_filesystems_keeps_the_error_of_the_link(
    lake: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary = fail_file_io(monkeypatch, "link", "src", errno.EXDEV)
    with parent(lake, "a") as fd, pytest.raises(OSError) as refused:
        link_once_source(lake, fd, "l")
    assert refused.value is primary
    assert not (lake / "a" / "l").exists()


def test_sync_directory_flushes_a_directory_and_refuses_anything_else(
    lake: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    synced: list[str] = []
    real = os.fsync

    def recording(descriptor: int) -> None:
        synced.append(os.readlink(f"/proc/self/fd/{descriptor}"))
        real(descriptor)

    monkeypatch.setattr(os, "fsync", recording)
    with parent(lake) as fd:
        posix.sync_directory(fd, "a")
    with parent(lake, "up") as fd:
        with pytest.raises(NotADirectoryError) as not_directory:
            posix.sync_directory(fd, "src")
        with pytest.raises(FileNotFoundError) as missing:
            posix.sync_directory(fd, "missing")
    assert (type(not_directory.value), not_directory.value.errno) == (
        NotADirectoryError,
        errno.ENOTDIR,
    )
    assert (type(missing.value), missing.value.errno) == (FileNotFoundError, errno.ENOENT)
    assert synced == [str(lake / "a")]


@pytest.mark.parametrize("close_fails", [False, True])
def test_a_failed_sync_closes_the_directory_and_keeps_its_error(
    lake: Path, monkeypatch: pytest.MonkeyPatch, close_fails: bool
) -> None:
    opened: list[int] = []
    real = os.fsync
    primary = OSError(errno.EIO, os.strerror(errno.EIO))

    def failing(descriptor: int) -> None:
        opened.append(descriptor)
        raise primary

    monkeypatch.setattr(os, "fsync", failing)
    if close_fails:
        fail_file_io(monkeypatch, "close", "a", errno.EIO)
    with parent(lake) as fd, pytest.raises(OSError) as refused:
        posix.sync_directory(fd, "a")
    monkeypatch.setattr(os, "fsync", real)
    assert refused.value is primary
    assert len(cleanup_notes(refused.value)) == int(close_fails)
    with pytest.raises(OSError) as closed:
        os.fstat(opened[0])
    assert closed.value.errno == errno.EBADF
