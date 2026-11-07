"""The lake's disk over a share, and shares that stall like a hung mount or pause in a hash."""

import threading
from pathlib import Path

from huron.applications.api.disk import PROBE_TIMEOUT, LakeDisk
from huron.core.lake.organizations.declarations import UNMANAGED, Declarations
from huron.core.storage import MARKER_FILE, OpenFile, PathLocks, Storage
from huron.core.storage.memory import MemoryStorage
from huron.core.storage.posix import PosixStorage
from huron.pkg.clock import Clock
from huron.pkg.fs.acl import SubprocessRunner
from tests.support.api import INSTANCE_ID, ROOT_MARKER

#: How long a test thread waits for a signal before the test fails instead of hanging.
SIGNAL_TIMEOUT = 5.0

#: Where the in-memory lake is mounted.
LAKE = Path("/lake")
#: The service user of the in-memory lake.
SERVICE_UID = 1000
#: The service group of the in-memory lake, the primary group of its user.
SERVICE_GID = 1000


def memory_lake() -> MemoryStorage:
    """An in-memory lake at :data:`LAKE`, marked for the test service, written by its user."""
    storage = MemoryStorage(LAKE, user="huron", uid=SERVICE_UID, gid=SERVICE_GID)
    storage.write_bytes(LAKE / MARKER_FILE, ROOT_MARKER)
    return storage


def lake_disk(
    storage: Storage,
    clock: Clock,
    *,
    declarations: Declarations = UNMANAGED,
    lake_path: Path = LAKE,
    mount_prefix: Path | None = None,
    service_gid: int = SERVICE_GID,
    probe_timeout: float = PROBE_TIMEOUT,
) -> LakeDisk:
    """The lake's disk over ``storage``; unrooted organizations lie below ``lake_path``.

    The caller closes it.
    """
    return LakeDisk(
        storage,
        lake_path,
        mount_prefix or lake_path,
        str(INSTANCE_ID),
        declarations,
        PathLocks(),
        service_gid=service_gid,
        clock=clock,
        probe_timeout=probe_timeout,
    )


class StalledStorage(MemoryStorage):
    """An in-memory lake whose file writes block until :attr:`release` is set.

    A ``hard`` NFS mount behaves like this during an outage. :attr:`writes` counts the writes
    that started, and :attr:`waiting` is set once a write waits for :attr:`release`.
    """

    def __init__(self) -> None:
        super().__init__(LAKE, user="huron", uid=SERVICE_UID, gid=SERVICE_GID)
        super().write_bytes(LAKE / MARKER_FILE, ROOT_MARKER)
        self.release = threading.Event()
        self.waiting = threading.Event()
        self.writes = 0

    def write_bytes(self, path: Path, data: bytes, mode: int | None = None) -> None:
        """Wait for :attr:`release`, then write."""
        self.writes += 1
        self.waiting.set()
        self.release.wait()
        super().write_bytes(path, data, mode)


class PausingStorage(PosixStorage):
    """POSIX storage whose first hash waits until :attr:`release` is set.

    :attr:`hashing` is set once that hash waits, so a test can act while a placement hashes.
    Later hashes do not wait.
    """

    def __init__(self) -> None:
        super().__init__("none", SubprocessRunner())
        self.hashing = threading.Event()
        self.release = threading.Event()
        self._paused = False

    def open_file(self, path: Path) -> OpenFile | None:
        """Open ``path``; the first file opened pauses in its hash."""
        opened = super().open_file(path)
        if opened is None or self._paused:
            return opened
        self._paused = True
        return _PausedFile(opened, self.hashing, self.release)


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
