"""Shared test builders for the API tier's injectable storage seam and the ingest domain."""

from __future__ import annotations

import errno
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from huron.applications.api.runtime import ApiStores
from huron.pkg.auth import (
    MemoryApiKeyStore,
    MemoryCredentialStore,
    MemoryPrincipalStore,
    MemorySessionStore,
)
from huron.pkg.catalog.ingest import (
    FileState,
    IngestFile,
    IngestLease,
    IngestSession,
    IngestState,
    UploadAction,
)
from huron.pkg.metastore import InMemoryHierarchyStore, InMemoryRbacStore

if TYPE_CHECKING:
    from datetime import timedelta

    import pytest

    from huron.pkg.catalog.ports import Clock

#: The instant every ingest-domain test fixture below treats as "now".
INGEST_NOW: datetime = datetime(2024, 1, 1, tzinfo=UTC)


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


#: The state each named ``IngestSession`` operation moves to on success.
INGEST_OPERATION_TARGETS: dict[str, IngestState] = {
    "open": IngestState.UPLOADING,
    "verify": IngestState.VERIFYING,
    "begin_commit": IngestState.COMMITTING,
    "commit": IngestState.COMMITTED,
    "abort": IngestState.ABORTED,
    "fail": IngestState.FAILED,
}


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


def ingest_lease(*, expires_at: datetime) -> IngestLease:
    """Build an ``IngestLease`` with arbitrary identifiers and the given expiry.

    Args:
        expires_at: The instant the lease lapses.

    Returns:
        A lease reserving an arbitrary revision under an arbitrary dataset.
    """
    return IngestLease(
        ingest_id=uuid4(),
        dataset_id=uuid4(),
        revision_id=uuid4(),
        revision_number=1,
        expires_at=expires_at,
    )


def ingest_session(
    state: IngestState, *, expires_in: timedelta, manifest_sha256: str = "a" * 64
) -> IngestSession:
    """Build a session in ``state`` whose lease expires ``expires_in`` from :data:`INGEST_NOW`.

    Args:
        state: The state to build the session in.
        expires_in: How long after (positive) or before (negative)
            :data:`INGEST_NOW` the lease expires.
        manifest_sha256: The manifest digest the session declares.

    Returns:
        A session owned by an arbitrary principal, with no parent revision.
    """
    return IngestSession(
        lease=ingest_lease(expires_at=INGEST_NOW + expires_in),
        state=state,
        manifest_sha256=manifest_sha256,
        created_by="user:alice",
    )


def ingest_file(
    *,
    path: str = "payload/a.bin",
    size: int = 10,
    expected_sha256: str = "a" * 64,
    action: UploadAction = UploadAction.UPLOAD,
    part_count: int = 1,
    state: FileState = FileState.PENDING,
    completed_parts: frozenset[int] = frozenset(),
) -> IngestFile:
    """Build an ``IngestFile``, defaulting to a pending single-part upload.

    Args:
        path: The manifest path this file was planned for.
        size: The size the manifest declares for this file.
        expected_sha256: The digest the manifest declares for this file.
        action: Whether the file uploads or hard-links from the parent.
        part_count: The number of upload parts the plan allows.
        state: Whether the ledger currently vouches for this file's bytes.
        completed_parts: The 1-based part numbers already recorded.

    Returns:
        An ``IngestFile`` with an arbitrary identifier and the given fields.
    """
    return IngestFile(
        file_id=uuid4(),
        path=path,
        size=size,
        expected_sha256=expected_sha256,
        action=action,
        part_count=part_count,
        state=state,
        completed_parts=completed_parts,
    )


def run_ingest_operation(session: IngestSession, operation: str, *, now: datetime) -> IngestSession:
    """Invoke ``operation`` on ``session``, supplying whatever it needs beyond the state edge.

    Args:
        session: The session to operate on.
        operation: One of ``"open"``, ``"verify"``, ``"begin_commit"``,
            ``"commit"``, ``"abort"``, ``"fail"``, ``"renew"`` or
            ``"expire"``.
        now: The instant to judge the lease against.

    Returns:
        The session ``operation`` returns on success.
    """
    if operation == "open":
        return session.open(now=now)
    if operation == "verify":
        complete_file = ingest_file(state=FileState.COMPLETE, completed_parts=frozenset({1}))
        return session.verify((complete_file,), now=now)
    if operation == "begin_commit":
        return session.begin_commit(manifest_sha256=session.manifest_sha256, now=now)
    if operation == "commit":
        return session.commit()
    if operation == "abort":
        return session.abort()
    if operation == "fail":
        return session.fail()
    if operation == "expire":
        return session.expire(now=now)
    return session.renew(now=now)


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
    log: list[Path] = []

    def _tracking_open(path: str | os.PathLike[str], *args: object, **kwargs: object) -> int:
        descriptor = original_open(path, *args, **kwargs)
        paths_by_descriptor[descriptor] = Path(path)
        return descriptor

    def _tracking_fsync(descriptor: int) -> None:
        original_fsync(descriptor)
        log.append(paths_by_descriptor[descriptor])

    monkeypatch.setattr(os, "open", _tracking_open)
    monkeypatch.setattr(os, "fsync", _tracking_fsync)
    return log
