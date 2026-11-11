"""The CLI's local state under ``$XDG_STATE_HOME/huron``: tokens, working copies and drafts.

Each working copy is one file, ``collections/<collection id>/working.json``. Every write is
atomic: a unique temporary file with mode 0600, a sync of the file, a rename over the old file
and a sync of the directory. A kill at any point leaves the complete old or new file.

Two locks, both taken with ``flock`` on a file that the CLI never truncates or removes:

- The state lock, ``state.lock`` in the state root, serializes every read-change-write of the
  local state. A second process waits for it for at most :data:`LOCK_WAIT` seconds.
- The push lock, ``collections/<collection id>/push.lock``, is held for a whole push. A second
  push of the same working copy fails at once.

The kernel releases both locks when the process ends. ``flock`` needs a local file system, so a
state root on NFS is refused before the first lock.
"""

from __future__ import annotations

import errno
import fcntl
import json
import os
import re
import stat
import subprocess
import tempfile
import time
from collections.abc import Callable, Generator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ConfigDict, TypeAdapter, ValidationError

from huron.applications.cli.errors import CliError, ExitCode, UsageError

__all__ = [
    "FORMAT",
    "LOCK_WAIT",
    "LocalState",
    "PendingCommit",
    "StagedAdd",
    "Tokens",
    "WorkingState",
    "filesystem_type",
    "state_root",
    "write_atomically",
]

#: The format version of ``working.json`` that this CLI reads and writes.
FORMAT = 1
#: The most seconds a command waits for the state lock that another process holds.
LOCK_WAIT = 10.0

_WORKING_FILE = "working.json"
_DRAFT_FILE = "metadata.draft.json"
_TOKENS_FILE = "tokens.json"
_STATE_LOCK = "state.lock"
_PUSH_LOCK = "push.lock"
#: The files of a working copy in the format before ``working.json``.
_OLD_FILES = ("copy.json", "stage.json")
#: The seconds between two tries of a lock that another process holds.
_POLL = 0.05
_STRICT = ConfigDict(extra="forbid", strict=True)
#: The longest format version that a message shows, as JSON.
_SHOWN_VERSION = 20
#: A line of the Linux ``mount`` listing: ``/dev/sda1 on / type ext4 (rw,relatime)``.
_LINUX_MOUNT = re.compile(r"^.+? on (?P<point>/.*) type (?P<type>[^\s()]+) \([^()]*\)$")
#: A line of the macOS ``mount`` listing: ``/dev/disk3s1 on / (apfs, local, journaled)``.
_MACOS_MOUNT = re.compile(r"^.*? on (?P<point>/.*) \((?P<type>[^,()\s]+)[,)]")
_PERMISSIONS_HINT = "correct the permissions. Then run the command again"
_SPACE_HINT = "make free space. Then run the command again"
_KIND_HINT = (
    "find the file or directory of the incorrect type in this path."
    " Move it to a different location. Then run the command again"
)
_CAUSE_HINT = "correct the cause that the error message gives. Then run the command again"
#: The hint of a state file error, by the error number; :data:`_CAUSE_HINT` for other numbers.
_ERRNO_HINTS: dict[int | None, str] = {
    errno.EACCES: _PERMISSIONS_HINT,
    errno.EPERM: _PERMISSIONS_HINT,
    errno.EROFS: _PERMISSIONS_HINT,
    errno.ENOSPC: _SPACE_HINT,
    errno.EDQUOT: _SPACE_HINT,
    errno.ENOTDIR: _KIND_HINT,
    errno.EISDIR: _KIND_HINT,
    errno.EEXIST: _KIND_HINT,
}


@dataclass(frozen=True, slots=True)
class Tokens:
    """The Huron token and what is needed to renew it."""

    huron_token: str
    expires_at: float
    subject: str
    refresh_token: str | None = None


@dataclass(slots=True)
class StagedAdd:
    """A local file to upload into the collection at ``rel_path``.

    ``size``, ``mtime_ns`` and ``sha256`` describe the source file when ``huron add`` read it:
    a push checks the size and the modification time, and the commit sends the size and the
    sha256. ``attempt_id`` names the upload attempt before its creation, ``upload_id`` the tus
    upload once it is created, so a later push continues the upload. ``attempt_state`` is
    ``"ready"`` once the service sealed the upload and ``None`` before that.
    """

    rel_path: str
    source: str
    size: int
    mtime_ns: int
    sha256: str
    attempt_id: str | None = None
    upload_id: str | None = None
    attempt_state: str | None = None

    __pydantic_config__ = _STRICT

    def same_file(self, other: StagedAdd) -> bool:
        """Whether ``other`` stages the same file, as ``huron add`` read it, at the same path."""
        return (self.rel_path, self.source, self.size, self.mtime_ns, self.sha256) == (
            other.rel_path,
            other.source,
            other.size,
            other.mtime_ns,
            other.sha256,
        )


@dataclass(slots=True)
class PendingCommit:
    """A commit request that the CLI saved before it sent it: its ID and its exact body."""

    request_id: str
    body: dict[str, Any]

    __pydantic_config__ = _STRICT


@dataclass(slots=True)
class WorkingState:
    """One working copy: the collection, the version the stage is based on, and the stage.

    ``path`` is the collection's directory below the mount prefix, ``None`` for a draft.
    ``pending_commit`` is the commit request that the CLI sent and whose outcome it did not
    read yet.
    """

    collection_id: str
    identifier: str
    path: str | None
    base_version: int
    adds: list[StagedAdd] = field(default_factory=list)
    removes: list[str] = field(default_factory=list)
    pending_commit: PendingCommit | None = None

    __pydantic_config__ = _STRICT

    @property
    def empty(self) -> bool:
        """Whether nothing is staged."""
        return not self.adds and not self.removes


class LocalState:
    """Reads and writes the state root; the directories are created with mode 0700.

    ``lock_wait`` is the most seconds to wait for the state lock, measured with ``clock`` and
    waited with ``sleep``. ``filesystem`` names the file system type of a directory.
    """

    def __init__(
        self,
        root: Path,
        *,
        lock_wait: float = LOCK_WAIT,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        filesystem: Callable[[Path], str] | None = None,
    ) -> None:
        self.root = root
        self._lock_wait = lock_wait
        self._clock = clock
        self._sleep = sleep
        self._filesystem = filesystem or filesystem_type
        self._held = 0
        self._local = False

    @contextmanager
    def locked(self) -> Generator[None]:
        """Hold the state lock; a nested use in this process holds it once."""
        if self._held:
            self._held += 1
            try:
                yield
            finally:
                self._held -= 1
            return
        descriptor = self._open_lock(_STATE_LOCK)
        try:
            self._wait_for(descriptor)
            self._held = 1
            try:
                yield
            finally:
                self._held = 0
        finally:
            os.close(descriptor)

    @contextmanager
    def push_lock(self, collection_id: str) -> Generator[None]:
        """Hold the push lock of a working copy; refuses at once when another push holds it."""
        descriptor = self._open_lock(_PUSH_LOCK, collection_id)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise CliError(
                    "another `huron push` of this working copy holds the push lock",
                    ExitCode.CONFLICT,
                    hint="wait for that push to stop. Then run `huron push` again",
                ) from error
            yield
        finally:
            os.close(descriptor)

    def working(self, collection_id: str) -> WorkingState | None:
        """The working copy of a collection, if checked out; creates nothing.

        Refuses a working copy in an old format, a file of another format version and a file
        that is not a working copy, such as a file of another collection. The CLI does not
        change such files.
        """
        directory = self._copy(collection_id)
        _refuse_old(directory)
        path = directory / _WORKING_FILE
        raw = _read(path)
        if raw is None:
            return None
        working = _parse(path, raw)
        if working.collection_id != collection_id:
            raise _unreadable(path)
        return working

    def working_copies(self) -> list[WorkingState]:
        """Every working copy recorded here, by identifier; creates nothing.

        A collection directory without ``working.json`` (only a draft) is skipped.
        """
        base = self.root / "collections"
        try:
            names = sorted(os.listdir(base))
        except (FileNotFoundError, NotADirectoryError):
            return []
        except OSError as error:
            raise _cannot_read(base, error) from error
        found = [self.working(name) for name in names]
        return sorted((item for item in found if item is not None), key=lambda w: w.identifier)

    def check_out(
        self, collection_id: str, identifier: str, base_version: int, path: str | None
    ) -> WorkingState:
        """Record a working copy at ``base_version``; the stage of an earlier checkout stays."""
        with self.locked():
            working = self.working(collection_id) or WorkingState(
                collection_id, identifier, path, base_version
            )
            working.identifier, working.path = identifier, path
            working.base_version = base_version
            self._save(working)
        return working

    @contextmanager
    def changing(self, collection_id: str) -> Generator[WorkingState]:
        """Read a working copy under the state lock, and write it when the block ends.

        A block that raises writes nothing. Refuses when the collection has no working copy.
        """
        with self.locked():
            working = self.working(collection_id)
            if working is None:
                raise UsageError(
                    f"there is no working copy of the collection {collection_id}",
                    hint="run `huron checkout <identifier>`",
                )
            yield working
            self._save(working)

    def read_tokens(self) -> Tokens | None:
        """The stored tokens; refused when the file is readable by others."""
        path = self.root / _TOKENS_FILE
        raw = _read(path)
        if raw is None:
            return None
        info = path.stat()
        if stat.S_IMODE(info.st_mode) & 0o077 or info.st_uid != os.getuid():
            raise CliError(
                f"you must own {path}, and its mode must be 0600",
                ExitCode.NOT_LOGGED_IN,
                hint=f"run `chmod 600 {path}`, or run `huron login`",
            )
        return Tokens(**json.loads(raw))

    def write_tokens(self, tokens: Tokens) -> None:
        """Store tokens with mode 0600."""
        with self.locked():
            write_atomically(self.root / _TOKENS_FILE, _encode(asdict(tokens)))

    def delete_tokens(self) -> bool:
        """Forget the tokens; returns whether any were stored."""
        with self.locked():
            path = self.root / _TOKENS_FILE
            if path.exists():
                path.unlink()
                return True
            return False

    def read_draft(self, collection_id: str) -> dict[str, Any] | None:
        """The local metadata draft of a collection."""
        raw = _read(self._copy(collection_id) / _DRAFT_FILE)
        if raw is None:
            return None
        document: dict[str, Any] = json.loads(raw)
        return document

    def write_draft(self, collection_id: str, document: Mapping[str, Any]) -> None:
        """Store a local metadata draft."""
        with self.locked():
            write_atomically(self._private(collection_id) / _DRAFT_FILE, _encode(document))

    def delete_draft(self, collection_id: str) -> None:
        """Forget the local metadata draft."""
        with self.locked():
            (self._copy(collection_id) / _DRAFT_FILE).unlink(missing_ok=True)

    def _copy(self, collection_id: str) -> Path:
        """The directory of a working copy; refuses an ID that is not a name in ``collections``.

        The ID comes from the API, from the configuration or from a directory name.
        """
        if collection_id in ("", ".", "..") or "/" in collection_id or "\0" in collection_id:
            raise CliError(
                f"{json.dumps(collection_id)} is not a valid collection ID",
                ExitCode.FAILED,
                hint="run `huron checkout <identifier>`",
            )
        return self.root / "collections" / collection_id

    def _private(self, collection_id: str | None = None) -> Path:
        """The state root, or the directory of a working copy, created when missing.

        Each missing directory from the state root down gets mode 0700, and an existing one keeps
        its mode. Missing parents of the state root get the default mode of ``mkdir``.
        """
        chain = [self.root]
        if collection_id is not None:
            chain += [self.root / "collections", self._copy(collection_id)]
        try:
            try:
                _make_private(self.root)
            except FileNotFoundError:
                self.root.parent.mkdir(parents=True, exist_ok=True)
                _make_private(self.root)
            for directory in chain[1:]:
                _make_private(directory)
        except OSError as error:
            raise _cannot_save(Path(error.filename or chain[-1]), error) from error
        return chain[-1]

    def _save(self, working: WorkingState) -> None:
        document = {"format": FORMAT, **_ADAPTER.dump_python(working, mode="json")}
        directory = self._private(working.collection_id)
        write_atomically(directory / _WORKING_FILE, _encode(document))

    def _open_lock(self, name: str, collection_id: str | None = None) -> int:
        """Open a lock file for ``flock``; it is created once and keeps its inode.

        The lock file is in the state root, or in the directory of a working copy.
        """
        self._private()
        self._refuse_network()
        path = self._private(collection_id) / name
        try:
            return os.open(path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
        except OSError as error:
            raise _cannot_save(path, error) from error

    def _refuse_network(self) -> None:
        if self._local:
            return
        if self._filesystem(self.root).startswith("nfs"):
            raise CliError(
                f"the state directory {self.root} is on NFS."
                " The CLI needs a local file system for its locks",
                ExitCode.FAILED,
                hint="set `XDG_STATE_HOME` to a directory on a local disk of this machine",
            )
        self._local = True

    def _wait_for(self, descriptor: int) -> None:
        deadline = self._clock() + self._lock_wait
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except BlockingIOError as error:
                remaining = deadline - self._clock()
                if remaining <= 0:
                    raise CliError(
                        f"another huron command holds the lock of {self.root}"
                        f" for more than {self._lock_wait:g} seconds",
                        ExitCode.CONFLICT,
                        hint="wait for the other command to stop. Then run the command again",
                    ) from error
                self._sleep(min(_POLL, remaining))


def state_root(environ: Mapping[str, str]) -> Path:
    """``$XDG_STATE_HOME/huron``."""
    base = environ.get("XDG_STATE_HOME") or str(
        Path(environ.get("HOME", "~")).expanduser() / ".local" / "state"
    )
    return Path(base) / "huron"


def write_atomically(path: Path, data: bytes) -> None:
    """Replace ``path`` with ``data`` so that a kill leaves the complete old or new file.

    The data goes into a unique temporary file with mode 0600 next to ``path``. The file is
    synced, renamed over ``path``, and the directory is synced. A failure, such as a full disk,
    removes the temporary file, keeps the old file and raises an error that names ``path``.
    """
    try:
        _replace(path, data)
    except OSError as error:
        raise _cannot_save(path, error) from error


def filesystem_type(
    path: Path,
    *,
    mountinfo: Path = Path("/proc/self/mountinfo"),
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> str:
    """The type of the file system that holds ``path``, such as ``ext4`` or ``nfs4``.

    On Linux, the mount of ``path`` is the line of ``mountinfo`` with the device of ``path``.
    Without ``mountinfo`` (macOS), the mount is the longest mount point of ``/sbin/mount`` that
    holds ``path``, from a listing line in the macOS or the Linux format. An empty string means
    that the type is not known: no line matches, or ``/sbin/mount`` cannot run.
    """
    try:
        table = mountinfo.read_text()
    except OSError:
        return _listed_type(_mount_listing(run), path.resolve())
    return _mountinfo_type(table, os.stat(path).st_dev)


def _replace(path: Path, data: bytes) -> None:
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        try:
            view = memoryview(data)
            while view:
                view = view[os.write(descriptor, view) :]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _make_private(directory: Path) -> None:
    """Create ``directory`` with mode 0700 whatever the umask; an existing directory stays."""
    try:
        directory.mkdir(mode=0o700)
    except FileExistsError:
        if directory.is_dir():
            return
        raise NotADirectoryError(
            errno.ENOTDIR, os.strerror(errno.ENOTDIR), str(directory)
        ) from None
    os.chmod(directory, 0o700)


def _read(path: Path) -> bytes | None:
    """The bytes of a state file; ``None`` when it does not exist."""
    try:
        return path.read_bytes()
    except (FileNotFoundError, NotADirectoryError):
        return None
    except OSError as error:
        raise _cannot_read(path, error) from error


def _exists(path: Path) -> bool:
    """Whether ``path`` exists; refuses a path that the CLI cannot look at."""
    try:
        os.stat(path)
    except (FileNotFoundError, NotADirectoryError):
        return False
    except OSError as error:
        raise _cannot_read(path, error) from error
    return True


def _cannot_read(path: Path, error: OSError) -> CliError:
    return CliError(
        f"the CLI cannot read {path}: {error.strerror}",
        ExitCode.FAILED,
        hint=_os_error_hint(error),
    )


def _cannot_save(path: Path, error: OSError) -> CliError:
    return CliError(
        f"the CLI cannot save {path}: {error.strerror}",
        ExitCode.FAILED,
        hint=_os_error_hint(error),
    )


def _os_error_hint(error: OSError) -> str:
    """The hint that tells how to correct the cause of ``error``."""
    return _ERRNO_HINTS.get(error.errno, _CAUSE_HINT)


def _encode(document: Mapping[str, Any]) -> bytes:
    return (json.dumps(document, indent=2, sort_keys=True) + "\n").encode()


def _parse(path: Path, raw: bytes) -> WorkingState:
    """The working copy in ``raw``; refuses another format version and a broken file."""
    try:
        document = json.loads(raw)
    except ValueError:
        document = None
    if not isinstance(document, dict) or "format" not in document:
        raise _unreadable(path)
    version = document.pop("format")
    if type(version) is not int or version != FORMAT:
        raise _unknown_version(path, version)
    try:
        return _ADAPTER.validate_json(json.dumps(document))
    except ValidationError as error:
        raise _unreadable(path) from error


def _refuse_old(directory: Path) -> None:
    """Refuse a working copy that the CLI wrote before ``working.json``; changes nothing."""
    if any(_exists(directory / name) for name in _OLD_FILES):
        raise CliError(
            f"{directory} holds a working copy in an old format. This CLI cannot read it",
            ExitCode.FAILED,
            hint=_start_again(directory),
        )


def _unknown_version(path: Path, version: object) -> CliError:
    """Refuse ``version``; the message shows it only as a short integer or text."""
    shown = json.dumps(version)
    simple = type(version) is int or isinstance(version, str)
    has = (
        f"the format version {shown}"
        if simple and len(shown) <= _SHOWN_VERSION
        else "a format version that is not valid"
    )
    return CliError(
        f"{path} has {has}. This CLI can read only the format version {FORMAT}",
        ExitCode.FAILED,
        hint=_start_again(path.parent),
    )


def _unreadable(path: Path) -> CliError:
    return CliError(
        f"{path} is not a valid working copy file",
        ExitCode.FAILED,
        hint=_start_again(path.parent),
    )


def _start_again(directory: Path) -> str:
    return (
        f"the CLI did not change the files in {directory}. Move the directory to a different"
        " location. Then run `huron checkout <identifier>` again"
    )


def _mountinfo_type(table: str, device: int) -> str:
    """The type of the mount of ``device`` in ``/proc/self/mountinfo``."""
    wanted = f"{os.major(device)}:{os.minor(device)}"
    for line in table.splitlines():
        fields = line.split()
        if len(fields) > 2 and fields[2] == wanted and "-" in fields:
            return fields[fields.index("-") + 1]
    return ""


def _mount_listing(run: Callable[..., subprocess.CompletedProcess[str]]) -> str:
    """The output of ``/sbin/mount``; empty when it cannot run."""
    try:
        return run(["/sbin/mount"], capture_output=True, text=True, check=False).stdout
    except OSError:
        return ""


def _listed_type(listing: str, path: Path) -> str:
    """The type of the longest mount point in the ``mount`` listing that holds ``path``."""
    best, kind = -1, ""
    for line in listing.splitlines():
        found = _LINUX_MOUNT.match(line) or _MACOS_MOUNT.match(line)
        if found is None:
            continue
        point = Path(found["point"])
        if path.is_relative_to(point) and len(point.parts) > best:
            best, kind = len(point.parts), found["type"]
    return kind


_ADAPTER = TypeAdapter(WorkingState)
