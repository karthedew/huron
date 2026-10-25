"""Shared test builders for injectable storage, clocks and filesystem failures."""

from __future__ import annotations

import errno
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from huron.applications.api.runtime import ApiStores
from huron.core.metastore import (
    InMemoryHierarchyStore,
    InMemoryRbacStore,
    MemoryApiKeyStore,
    MemoryCredentialStore,
    MemoryPrincipalStore,
    MemorySessionStore,
)

if TYPE_CHECKING:
    from datetime import timedelta

    import pytest

    from huron.core.foundation.clock import Clock


@dataclass(slots=True)
class FakeClock:
    """A ``Clock`` a test drives explicitly, never the wall clock.

    Attributes:
        _now: The instant ``now()`` currently returns.
    """

    _now: datetime

    def now(self) -> datetime:
        """Return the clock's current instant.

        Returns:
            The instant this clock is currently set to.
        """
        return self._now

    def advance(self, delta: timedelta) -> None:
        """Move the clock forward by ``delta``.

        Args:
            delta: How far forward to move the clock.
        """
        self._now += delta

    def set(self, instant: datetime) -> None:
        """Move the clock to exactly ``instant``, forward or backward.

        Args:
            instant: The instant the clock should read from now on.
        """
        self._now = instant


def memory_stores(*, clock: Clock | None = None) -> ApiStores:
    """Build a fresh in-memory ``ApiStores`` for one test's application.

    Args:
        clock: The source of the current time for the hierarchy store's
            idempotency and lease arithmetic. Defaults to the system's UTC
            clock.

    Returns:
        A store bundle backed entirely by process memory, with nothing
        shared with any other call.
    """
    return ApiStores(
        hierarchy=InMemoryHierarchyStore(clock=clock),
        rbac=InMemoryRbacStore(),
        api_keys=MemoryApiKeyStore(),
        credentials=MemoryCredentialStore(),
        sessions=MemorySessionStore(),
        principals=MemoryPrincipalStore(),
    )


def crash_on(
    monkeypatch: pytest.MonkeyPatch, name: str, *, call: int = 1, errno_: int = errno.EIO
) -> list[object]:
    """Make the ``call``-th invocation of ``os.<name>`` raise, recording every call's target.

    Injects the crash a fixed number of calls into a code path, the way a
    process killed mid-commit stops at one particular syscall rather than
    the first: earlier and later calls run the real function unchanged.

    Args:
        monkeypatch: The active monkeypatch fixture.
        name: The attribute of the :mod:`os` module to patch, such as
            ``"rename"``, ``"fsync"``, ``"link"``, ``"pwrite"``,
            ``"replace"`` or ``"chmod"``.
        call: The 1-based invocation count that raises.
        errno_: The ``errno`` value the injected ``OSError`` carries.

    Returns:
        The first positional argument of every call made so far; it grows
        as the patched function keeps being called.
    """
    original = getattr(os, name)
    calls: list[object] = []

    def _patched(*args: object, **kwargs: object) -> object:
        calls.append(args[0])
        if len(calls) == call:
            raise OSError(errno_, os.strerror(errno_))
        return original(*args, **kwargs)

    monkeypatch.setattr(os, name, _patched)
    return calls


def fsync_log(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Record the path behind every ``os.fsync`` call, in the order they happen.

    Pairs each descriptor with the path passed to the ``os.open`` that
    produced it, so an ordering assertion can read as a list of paths
    instead of a list of opaque integers.

    Args:
        monkeypatch: The active monkeypatch fixture.

    Returns:
        The path fsynced by each call so far; it grows as more happen.
    """
    paths_by_descriptor: dict[int, Path] = {}
    original_open = os.open
    original_fsync = os.fsync
    original_dup = os.dup
    log: list[Path] = []

    def _tracking_open(path: str | os.PathLike[str], *args: object, **kwargs: object) -> int:
        descriptor = original_open(path, *args, **kwargs)
        parent = kwargs.get("dir_fd")
        paths_by_descriptor[descriptor] = (
            paths_by_descriptor[parent] / path if isinstance(parent, int) else Path(path)
        )
        return descriptor

    def _tracking_dup(descriptor: int) -> int:
        result = original_dup(descriptor)
        paths_by_descriptor[result] = paths_by_descriptor[descriptor]
        return result

    def _tracking_fsync(descriptor: int) -> None:
        original_fsync(descriptor)
        log.append(paths_by_descriptor[descriptor])

    monkeypatch.setattr(os, "dup", _tracking_dup)
    monkeypatch.setattr(os, "open", _tracking_open)
    monkeypatch.setattr(os, "fsync", _tracking_fsync)
    return log
