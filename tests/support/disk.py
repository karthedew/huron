"""The lake's disk over a lake, lakes that stall or pause, and the link planting of tests."""

import errno
import os
import stat
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from huron.applications.api.disk import PROBE_TIMEOUT, LakeDisk
from huron.core.storage import MARKER_FILE, LakePath, OpenFile, OrganizationPlace, Storage
from huron.core.storage.memory import MemoryStorage
from huron.core.storage.posix import PosixStorage
from huron.pkg.clock import Clock
from tests.support.api import INSTANCE_ID, ROOT_MARKER

#: How long a test thread waits for a signal before the test fails instead of hanging.
SIGNAL_TIMEOUT = 5.0

#: Where the in-memory lake is mounted.
LAKE = Path("/lake")
#: The service user of the in-memory lake.
SERVICE_UID = 1000
#: The service group of the in-memory lake, the primary group of its user.
SERVICE_GID = 1000
#: Where a planted link points: a directory outside every lake.
OUTSIDE = "/outside"

type Snapshot = list[tuple[str, int, bytes]]

#: Primary operations paired with the cleanup failures that can follow them.
WRITE_CLEANUP_FAILURES = [
    (operation, cleanup)
    for operation in ("fchmod", "write", "fsync")
    for cleanup in (("close",), ("stat",), ("unlink",), ("close", "stat"), ("close", "unlink"))
] + [
    (operation, (cleanup,))
    for operation in ("open", "close", "rename")
    for cleanup in ("stat", "unlink")
    if operation != "open" or cleanup == "stat"
]


def fail_file_io(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    name: str,
    number: int | BaseException,
    *,
    after: int = 0,
) -> BaseException:
    """Raise and return one error on the named file, after the given matching calls."""
    real = getattr(os, operation)
    error = (
        OSError(number, os.strerror(number), "/untrusted/elsewhere")
        if isinstance(number, int)
        else number
    )

    def failing(path: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal after
        actual = os.readlink(f"/proc/self/fd/{path}") if isinstance(path, int) else str(path)
        if Path(actual).name == name:
            if after == 0:
                after = -1
                if operation == "close":
                    real(path, *args, **kwargs)
                raise error
            after -= 1
        return real(path, *args, **kwargs)

    monkeypatch.setattr(os, operation, failing)
    return error


def inject_fault(
    storage: Storage,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    location: LakePath,
    number: int,
) -> None:
    """Make the next ``operation`` at ``location`` fail with ``number``, one time.

    ``write`` and ``fsync`` fail the copy to the file ``location`` or the flush of the
    directory ``location``, and ``link`` fails a hard link to the name ``location``. A
    :class:`MemoryStorage` gets the fault in its ``faults``. On a :class:`PosixStorage` the
    system call on a name equal to the last name of ``location`` fails.
    """
    if isinstance(storage, MemoryStorage):
        storage.faults[(operation, location)] = number
    elif operation == "link":
        _fail_link(monkeypatch, location.name, number)
    else:
        fail_file_io(monkeypatch, operation, location.name, number)


def fail_write_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    part: str,
    operation: str,
    cleanup: tuple[str, ...],
    number: int,
    secondary_number: int = errno.EIO,
) -> tuple[BaseException, ...]:
    """Fail a write operation and its cleanup, retaining the exact injected exceptions."""
    primary = fail_file_io(monkeypatch, operation, part, number)
    secondary = tuple(
        fail_file_io(
            monkeypatch, action, part, secondary_number, after=2 if action == "stat" else 0
        )
        for action in cleanup
    )
    return primary, *secondary


def exception_chain(error: BaseException) -> tuple[BaseException, ...]:
    """The explicit causes of a public exception, including the exception itself."""
    chain = [error]
    while error.__cause__ is not None:
        error = error.__cause__
        chain.append(error)
    return tuple(chain)


def cleanup_notes(error: BaseException) -> list[str]:
    """All secondary diagnostics retained on a public exception and its explicit causes."""
    return [note for cause in exception_chain(error) for note in getattr(cause, "__notes__", [])]


def memory_lake() -> MemoryStorage:
    """An in-memory lake at :data:`LAKE`, marked for the test service, written by its user.

    Its root belongs to the service user and group, as ``huron adm provision-orgs`` leaves it.
    """
    storage = MemoryStorage(LAKE, uid=SERVICE_UID, gid=SERVICE_GID)
    root = storage.nodes[LakePath()]
    root.uid, root.gid = SERVICE_UID, SERVICE_GID
    storage.write_bytes(LakePath.of(MARKER_FILE), ROOT_MARKER, 0o644)
    return storage


def lake_disk(
    storage: Storage,
    clock: Clock,
    *,
    places: Mapping[str, OrganizationPlace] | None = None,
    probe_timeout: float = PROBE_TIMEOUT,
) -> LakeDisk:
    """The lake's disk over ``storage``; ``places`` are the declared organizations.

    The caller closes it.
    """
    return LakeDisk(
        storage, places or {}, str(INSTANCE_ID), clock=clock, probe_timeout=probe_timeout
    )


def plant_symlink(storage: Storage, location: LakePath) -> None:
    """Make ``location`` a symbolic link to a directory outside the lake.

    A :class:`MemoryStorage` gets a link node; a :class:`PosixStorage` gets a real link to
    the directory ``outside`` beside its root.
    """
    if isinstance(storage, MemoryStorage):
        storage.symlink(location, OUTSIDE)
        return
    assert isinstance(storage, PosixStorage)
    root = storage.root
    root.joinpath(*location.names).symlink_to(root.parent / "outside")


def snapshot(directory: Path) -> Snapshot:
    """The names, modes and bytes of everything below ``directory``, without following links."""
    found: Snapshot = []
    for path in sorted(directory.rglob("*")):
        info = path.lstat()
        data = path.read_bytes() if stat.S_ISREG(info.st_mode) else b""
        found.append((str(path.relative_to(directory)), info.st_mode, data))
    return found


class StalledStorage(MemoryStorage):
    """An in-memory lake whose file writes block until :attr:`release` is set.

    A ``hard`` NFS mount behaves like this during an outage. :attr:`writes` counts the writes
    that started, and :attr:`waiting` is set once a write waits for :attr:`release`.
    """

    def __init__(self) -> None:
        super().__init__(LAKE, uid=SERVICE_UID, gid=SERVICE_GID)
        super().write_bytes(LakePath.of(MARKER_FILE), ROOT_MARKER, 0o644)
        self.release = threading.Event()
        self.waiting = threading.Event()
        self.writes = 0

    def write_bytes(self, location: LakePath, data: bytes, mode: int) -> None:
        """Wait for :attr:`release`, then write."""
        self.writes += 1
        self.waiting.set()
        self.release.wait()
        super().write_bytes(location, data, mode)


class PausingStorage(PosixStorage):
    """POSIX storage whose first hash waits until :attr:`release` is set.

    :attr:`hashing` is set once that hash waits, so a test can act while a placement hashes.
    Later hashes do not wait, until :meth:`pause_next`.
    """

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.hashing = threading.Event()
        self.release = threading.Event()
        self._paused = False

    def pause_next(self) -> None:
        """Make the next hash wait as the first one did, with both signals cleared."""
        self.hashing.clear()
        self.release.clear()
        self._paused = False

    def open_file(self, location: LakePath) -> OpenFile | None:
        """Open ``location``; the first file opened pauses in its hash."""
        opened = super().open_file(location)
        if opened is None or self._paused:
            return opened
        self._paused = True
        return _PausedFile(opened, self.hashing, self.release)


def _fail_link(monkeypatch: pytest.MonkeyPatch, name: str, number: int) -> None:
    """Fail the first ``os.link`` to a name ``name`` with ``number``."""
    real = os.link
    armed = True

    def failing(source: Any, destination: Any, *args: Any, **kwargs: Any) -> None:
        nonlocal armed
        if armed and Path(destination).name == name:
            armed = False
            raise OSError(number, os.strerror(number), "/untrusted/elsewhere")
        real(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "link", failing)


class _PausedFile:
    def __init__(self, opened: OpenFile, hashing: threading.Event, release: threading.Event):
        self._opened = opened
        self._hashing = hashing
        self._release = release
        self.size = opened.size
        self.inode = opened.inode

    def sha256(self) -> str:
        self._hashing.set()
        if not self._release.wait(SIGNAL_TIMEOUT):
            raise TimeoutError("the test never released the paused hash")
        return self._opened.sha256()

    def set_mode(self, mode: int) -> None:
        self._opened.set_mode(mode)

    def close(self) -> None:
        self._opened.close()
