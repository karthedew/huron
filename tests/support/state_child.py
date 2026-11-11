"""Child processes for the local-state tests: a real ``huron`` command, or a held lock.

The test process starts a child with :class:`Child`. The child runs one of these commands:

- ``huron [--pause POINT] [--report-wait] ARGS...``: the real ``huron`` console script. With
  ``--pause``, the child stops at ``POINT`` of the atomic write, prints ``paused`` and waits for
  a line on stdin. With ``--report-wait``, it prints ``waiting`` the first time a lock is busy.
- ``hold-state ROOT``: hold the state lock of ``ROOT``, print ``held`` and wait for a line.
- ``hold-push ROOT COLLECTION_ID``: the same with the push lock of a working copy.

The pause points wrap the real system calls: the first ``os.fsync`` syncs the file, ``os.replace``
renames it, and the second ``os.fsync`` syncs the directory.
"""

from __future__ import annotations

import fcntl
import os
import select
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
#: The most seconds a test waits for one line or for the end of a child.
DEADLINE = 30.0
POINTS = (
    "before-file-sync",
    "after-file-sync",
    "before-rename",
    "after-rename",
    "before-directory-sync",
    "after-directory-sync",
)


class Child:
    """One child process of this module, with its stdin and stdout as pipes."""

    def __init__(self, environ: Mapping[str, str], *args: str) -> None:
        self.process = subprocess.Popen(
            [sys.executable, "-m", "tests.support.state_child", *args],
            cwd=ROOT,
            env=dict(environ),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._buffer = b""

    def expect(self, line: str) -> None:
        """Wait until the child prints ``line``; fail when it prints another line or ends."""
        assert self.read_line() == line, self._failure()

    def read_line(self) -> str:
        """The next line that the child prints, within :data:`DEADLINE` seconds."""
        assert self.process.stdout is not None
        deadline = time.monotonic() + DEADLINE
        while b"\n" not in self._buffer:
            remaining = deadline - time.monotonic()
            assert remaining > 0, "the child printed no line in time"
            readable, _, _ = select.select([self.process.stdout], [], [], remaining)
            if readable:
                chunk = os.read(self.process.stdout.fileno(), 4096)
                if not chunk:
                    return ""
                self._buffer += chunk
        line, self._buffer = self._buffer.split(b"\n", 1)
        return line.decode()

    def resume(self) -> None:
        """Let a paused or holding child continue."""
        assert self.process.stdin is not None
        self.process.stdin.write(b"go\n")
        self.process.stdin.flush()

    def finish(self) -> int:
        """Wait for the end of the child; its exit code."""
        self.process.communicate(timeout=DEADLINE)
        return self.process.returncode

    def kill(self) -> None:
        """Stop the child with SIGKILL and wait for its end."""
        self.process.send_signal(signal.SIGKILL)
        self.process.communicate(timeout=DEADLINE)

    def running(self) -> bool:
        """Whether the child did not end yet."""
        return self.process.poll() is None

    def _failure(self) -> str:
        if self.running():
            return "the child printed another line"
        _, stderr = self.process.communicate(timeout=DEADLINE)
        return stderr.decode()


def child_environment(home: Path) -> dict[str, str]:
    """The environment of a child: its own XDG directories below ``home`` and no coverage."""
    kept = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("HURON_", "COV_CORE_", "XDG_"))
    }
    return {
        **kept,
        "HOME": str(home),
        "XDG_STATE_HOME": str(home / "state"),
        "XDG_CONFIG_HOME": str(home / "config"),
    }


def _main(args: list[str]) -> None:
    from huron.applications.cli.localstate import LocalState

    command = args.pop(0)
    if command == "huron":
        _huron(args)
    lock = LocalState(Path(args[0]))
    held = lock.locked() if command == "hold-state" else lock.push_lock(args[1])
    with held:
        _announce("held")
        sys.stdin.readline()


def _huron(args: list[str]) -> None:
    from huron.applications.cli.main import main

    if args[0] == "--pause":
        _pause_at(args[1])
        args = args[2:]
    if args[0] == "--report-wait":
        _report_wait()
        args = args[1:]
    sys.argv = ["huron", *args]
    main()


def _pause_at(point: str) -> None:
    syncs: list[int] = []
    real_fsync, real_replace = os.fsync, os.replace

    def fsync(descriptor: int) -> None:
        syncs.append(descriptor)
        name = "file" if len(syncs) == 1 else "directory"
        _maybe_pause(point, f"before-{name}-sync")
        real_fsync(descriptor)
        _maybe_pause(point, f"after-{name}-sync")

    def replace(source: Any, target: Any) -> None:
        _maybe_pause(point, "before-rename")
        real_replace(source, target)
        _maybe_pause(point, "after-rename")

    os.fsync, os.replace = fsync, replace


def _report_wait() -> None:
    real: Callable[[int, int], None] = fcntl.flock
    reported: list[bool] = []

    def flock(descriptor: int, operation: int) -> None:
        try:
            real(descriptor, operation)
        except BlockingIOError:
            if not reported:
                reported.append(True)
                _announce("waiting")
            raise

    fcntl.flock = flock


def _maybe_pause(point: str, here: str) -> None:
    if point == here:
        _announce("paused")
        sys.stdin.readline()


def _announce(line: str) -> None:
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    _main(sys.argv[1:])
