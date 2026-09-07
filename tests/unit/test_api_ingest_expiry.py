"""``IngestService.expire_lapsed``: the pass that reaps abandoned ingest sessions.

Every test shares one ``FakeClock`` between an ``InMemoryHierarchyStore``
and the facade under test, so a lapsed lease is produced by advancing the
clock rather than by sleeping.
"""

from __future__ import annotations

import dataclasses
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from huron.pkg.catalog import FileState, IngestFile, IngestSession, IngestState, UploadAction
from huron.pkg.catalog.errors import DatasetLocked
from huron.pkg.catalog.ids import uuid7
from huron.pkg.catalog.ingest import LEASE_TTL
from huron.pkg.rawstore import PosixRawStore
from huron.service.api.ingest import SWEEP_ACTOR, ExpiryReport, IngestService
from huron.service.api.stores.hierarchy import InMemoryHierarchyStore
from tests.hierarchy_contract import seed_hierarchy
from tests.unit.support import FakeClock

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from uuid import UUID

    from huron.pkg.catalog.ports import Clock
    from huron.service.api.stores.ports import HierarchyWriter

pytestmark = pytest.mark.unit

_T0 = datetime(2026, 1, 1, tzinfo=UTC)


async def _open_session(
    hierarchy: InMemoryHierarchyStore,
    dataset_id: UUID,
    clock: FakeClock,
    *,
    manifest_sha256: str = "a" * 64,
) -> IngestSession:
    """Reserve one session on ``dataset_id`` and move it to UPLOADING, as a real upload would.

    Args:
        hierarchy: The store to reserve the session on.
        dataset_id: The dataset the session opens on.
        clock: The clock driving the store; read once for the
            reservation's lease and once for the open edge.
        manifest_sha256: The content identity the session declares.

    Returns:
        The session, in UPLOADING with its lease from the reservation.
    """
    async with hierarchy.transaction() as writer:
        reserved = await writer.begin_ingest(
            dataset_id,
            manifest_sha256,
            created_by="user:alice",
            parent_revision_id=None,
            files=(),
        )
    opened = reserved.open(now=clock.now())
    async with hierarchy.transaction() as writer:
        await writer.update_ingest_session(opened, expected_etag=reserved.etag)
    return opened


def _committing_session(
    session: IngestSession, *, manifest_sha256: str, now: datetime
) -> IngestSession:
    """Advance a PREPARING session straight to COMMITTING, in memory only.

    Args:
        session: The session to advance, currently PREPARING.
        manifest_sha256: The manifest identity to commit; must match what
            the session declared.
        now: The instant every edge is judged against.

    Returns:
        The session in COMMITTING, three edges ahead.
    """
    uploading = session.open(now=now)
    complete = IngestFile(
        file_id=uuid7(),
        path="payload/complete.bin",
        size=1,
        expected_sha256="a" * 64,
        action=UploadAction.UPLOAD,
        part_count=1,
        state=FileState.COMPLETE,
        completed_parts=frozenset({1}),
    )
    verifying = uploading.verify((complete,), now=now)
    return verifying.begin_commit(manifest_sha256=manifest_sha256, now=now)


class _RenewingListStore(InMemoryHierarchyStore):
    """A hierarchy store that renews every session it lists before the sweep can flip it.

    Stands in for a client's ``renew`` landing between the sweep's listing
    and its flip: the renewal is applied directly at the store layer,
    exactly as a concurrent request would leave it, without going through
    the domain's own lease guard.
    """

    async def lapsed_ingest_sessions(
        self, now: datetime, *, limit: int
    ) -> tuple[IngestSession, ...]:
        """List as the base store would, then renew every session listed.

        Args:
            now: The instant a session's lease is judged lapsed against.
            limit: The maximum number of sessions to return.

        Returns:
            The sessions the base store reported, exactly as it read them
            before the renewal below lands.
        """
        listed = await super().lapsed_ingest_sessions(now, limit=limit)
        for session in listed:
            renewed_lease = dataclasses.replace(session.lease, expires_at=now + LEASE_TTL)
            async with self.transaction() as writer:
                await writer.renew_ingest_session(dataclasses.replace(session, lease=renewed_lease))
        return listed


class _AuditFailingWriter:
    """A transaction writer that flips a session but refuses to record its audit row."""

    def __init__(self, inner: HierarchyWriter) -> None:
        """Wrap ``inner``, keeping every write except the audit insert.

        Args:
            inner: The real writer this one delegates every write to,
                except ``insert_audit_event``.
        """
        self._inner = inner

    async def expire_ingest_session(
        self, session: IngestSession, *, expected_etag: int, now: datetime
    ) -> None:
        """Delegate to the wrapped writer.

        Args:
            session: The session as it should read after the edge.
            expected_etag: The etag the sweep last read.
            now: The instant the sweep is running at.
        """
        await self._inner.expire_ingest_session(session, expected_etag=expected_etag, now=now)

    async def insert_audit_event(self, event: object) -> None:
        """Always raise, simulating an audit row that failed to write.

        Args:
            event: The audit row the caller tried to insert; never used.

        Raises:
            RuntimeError: Unconditionally.
        """
        raise RuntimeError("audit store unavailable")


class _AuditFailingStore(InMemoryHierarchyStore):
    """A hierarchy store whose transactions refuse to record an audit event once armed.

    Starts disarmed, so a test can seed its hierarchy and open a session
    through ordinary transactions before arming the failure for the one
    transaction under test.
    """

    def __init__(self, *, clock: Clock | None = None) -> None:
        """Start like the base store, with audit failure disarmed.

        Args:
            clock: The source of the current time, threaded to the base
                store unchanged.
        """
        super().__init__(clock=clock)
        self.fail_audit = False

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[HierarchyWriter]:
        """Open a transaction whose writer raises on ``insert_audit_event`` once armed.

        Yields:
            The base writer while disarmed; once armed, a writer that
            persists everything except an audit row.
        """
        async with super().transaction() as writer:
            yield _AuditFailingWriter(writer) if self.fail_audit else writer


async def test_expire_lapsed_flips_a_lapsed_session_and_frees_its_dataset() -> None:
    """A session lapsed exactly at the lease boundary is flipped, freeing its dataset."""
    clock = FakeClock(_T0)
    hierarchy = InMemoryHierarchyStore(clock=clock)
    service = IngestService(PosixRawStore("/unused"), hierarchy, clock=clock)
    ids = await seed_hierarchy(hierarchy)
    dataset_id = ids.datasets["run-0001"]
    session = await _open_session(hierarchy, dataset_id, clock)
    clock.advance(LEASE_TTL)

    report = await service.expire_lapsed(limit=10)

    assert report == ExpiryReport(listed=1, expired=1, skipped=0)
    updated = await hierarchy.ingest_session(session.lease.ingest_id)
    assert updated.state is IngestState.ABORTED
    assert updated.etag == session.etag + 1
    async with hierarchy.transaction() as writer:
        retaken = await writer.begin_ingest(
            dataset_id, "b" * 64, created_by="user:alice", parent_revision_id=None, files=()
        )
    assert retaken.lease.revision_number == session.lease.revision_number


async def test_expire_lapsed_leaves_a_live_session_untouched() -> None:
    """A session whose lease has not yet lapsed is left exactly as it was."""
    clock = FakeClock(_T0)
    hierarchy = InMemoryHierarchyStore(clock=clock)
    service = IngestService(PosixRawStore("/unused"), hierarchy, clock=clock)
    ids = await seed_hierarchy(hierarchy)
    dataset_id = ids.datasets["run-0001"]
    session = await _open_session(hierarchy, dataset_id, clock)
    clock.set(session.lease.expires_at - timedelta(seconds=1))

    report = await service.expire_lapsed(limit=10)

    assert report == ExpiryReport(listed=0, expired=0, skipped=0)
    assert await hierarchy.ingest_session(session.lease.ingest_id) == session
    with pytest.raises(DatasetLocked):
        async with hierarchy.transaction() as writer:
            await writer.begin_ingest(
                dataset_id, "b" * 64, created_by="user:alice", parent_revision_id=None, files=()
            )


async def test_expire_lapsed_never_touches_a_lapsed_committing_session() -> None:
    """A COMMITTING session is never listed or flipped, even long past its lease."""
    clock = FakeClock(_T0)
    hierarchy = InMemoryHierarchyStore(clock=clock)
    service = IngestService(PosixRawStore("/unused"), hierarchy, clock=clock)
    ids = await seed_hierarchy(hierarchy)
    dataset_id = ids.datasets["run-0001"]
    async with hierarchy.transaction() as writer:
        reserved = await writer.begin_ingest(
            dataset_id, "c" * 64, created_by="user:alice", parent_revision_id=None, files=()
        )
    committing = _committing_session(reserved, manifest_sha256="c" * 64, now=clock.now())
    async with hierarchy.transaction() as writer:
        await writer.update_ingest_session(committing, expected_etag=reserved.etag)
    clock.advance(timedelta(days=9))

    report = await service.expire_lapsed(limit=10)

    assert report == ExpiryReport(listed=0, expired=0, skipped=0)
    updated = await hierarchy.ingest_session(reserved.lease.ingest_id)
    assert updated.state is IngestState.COMMITTING
    with pytest.raises(DatasetLocked):
        async with hierarchy.transaction() as writer:
            await writer.begin_ingest(
                dataset_id, "d" * 64, created_by="user:alice", parent_revision_id=None, files=()
            )


async def test_a_renewal_between_listing_and_flip_beats_the_sweep() -> None:
    """A renewal landing between the sweep's list and its flip wins the race."""
    clock = FakeClock(_T0)
    hierarchy = _RenewingListStore(clock=clock)
    service = IngestService(PosixRawStore("/unused"), hierarchy, clock=clock)
    ids = await seed_hierarchy(hierarchy)
    dataset_id = ids.datasets["run-0001"]
    session = await _open_session(hierarchy, dataset_id, clock)
    clock.advance(LEASE_TTL)

    report = await service.expire_lapsed(limit=10)

    assert report == ExpiryReport(listed=1, expired=0, skipped=1)
    updated = await hierarchy.ingest_session(session.lease.ingest_id)
    assert updated.state is IngestState.UPLOADING
    assert updated.etag == session.etag
    assert updated.lease.expires_at == clock.now() + LEASE_TTL
    assert not [event for event in hierarchy._audit if event.kind == "ingest.expired"]


async def test_expire_lapsed_flips_at_most_limit_sessions_oldest_first() -> None:
    """A pass flips only up to ``limit`` sessions, the oldest-lapsed leases first."""
    clock = FakeClock(_T0)
    hierarchy = InMemoryHierarchyStore(clock=clock)
    service = IngestService(PosixRawStore("/unused"), hierarchy, clock=clock)
    ids = await seed_hierarchy(hierarchy, {"astro": {"sims": ("run-0001", "run-0002", "run-0003")}})
    first = await _open_session(
        hierarchy, ids.datasets["run-0001"], clock, manifest_sha256="a" * 64
    )
    clock.advance(timedelta(minutes=1))
    second = await _open_session(
        hierarchy, ids.datasets["run-0002"], clock, manifest_sha256="b" * 64
    )
    clock.advance(timedelta(minutes=1))
    third = await _open_session(
        hierarchy, ids.datasets["run-0003"], clock, manifest_sha256="c" * 64
    )
    clock.advance(LEASE_TTL)

    first_pass = await service.expire_lapsed(limit=2)
    assert first_pass == ExpiryReport(listed=2, expired=2, skipped=0)
    assert (await hierarchy.ingest_session(first.lease.ingest_id)).state is IngestState.ABORTED
    assert (await hierarchy.ingest_session(second.lease.ingest_id)).state is IngestState.ABORTED
    assert (await hierarchy.ingest_session(third.lease.ingest_id)).state is IngestState.UPLOADING

    second_pass = await service.expire_lapsed(limit=2)
    assert second_pass == ExpiryReport(listed=1, expired=1, skipped=0)
    assert (await hierarchy.ingest_session(third.lease.ingest_id)).state is IngestState.ABORTED


async def test_expire_lapsed_audits_each_flip_as_the_sweep() -> None:
    """Each flip writes one audit row attributing itself to the sweep, not a principal."""
    clock = FakeClock(_T0)
    hierarchy = InMemoryHierarchyStore(clock=clock)
    service = IngestService(PosixRawStore("/unused"), hierarchy, clock=clock)
    ids = await seed_hierarchy(hierarchy)
    dataset_id = ids.datasets["run-0001"]
    session = await _open_session(hierarchy, dataset_id, clock)
    clock.advance(LEASE_TTL)

    await service.expire_lapsed(limit=10)

    events = [event for event in hierarchy._audit if event.kind == "ingest.expired"]
    assert len(events) == 1
    event = events[0]
    assert event.actor == SWEEP_ACTOR
    assert event.subject_kind == "ingest_session"
    assert event.subject_id == session.lease.ingest_id
    assert event.created_at == clock.now()
    assert event.payload == {
        "state": IngestState.UPLOADING.value,
        "expires_at": session.lease.expires_at.isoformat().replace("+00:00", "Z"),
        "dataset_id": str(dataset_id),
    }


async def test_a_flip_and_its_audit_row_commit_together() -> None:
    """A failing audit insert rolls back the flip too: neither one lands without the other."""
    clock = FakeClock(_T0)
    hierarchy = _AuditFailingStore(clock=clock)
    service = IngestService(PosixRawStore("/unused"), hierarchy, clock=clock)
    ids = await seed_hierarchy(hierarchy)
    dataset_id = ids.datasets["run-0001"]
    session = await _open_session(hierarchy, dataset_id, clock)
    clock.advance(LEASE_TTL)
    hierarchy.fail_audit = True

    with pytest.raises(RuntimeError, match="audit store unavailable"):
        await service.expire_lapsed(limit=10)

    updated = await hierarchy.ingest_session(session.lease.ingest_id)
    assert updated == session
    assert not [event for event in hierarchy._audit if event.kind == "ingest.expired"]


async def test_a_second_pass_over_the_same_rows_expires_nothing() -> None:
    """A second pass over rows the first already flipped expires nothing further."""
    clock = FakeClock(_T0)
    hierarchy = InMemoryHierarchyStore(clock=clock)
    service = IngestService(PosixRawStore("/unused"), hierarchy, clock=clock)
    ids = await seed_hierarchy(hierarchy)
    dataset_id = ids.datasets["run-0001"]
    await _open_session(hierarchy, dataset_id, clock)
    clock.advance(LEASE_TTL)

    first = await service.expire_lapsed(limit=10)
    second = await service.expire_lapsed(limit=10)

    assert first == ExpiryReport(listed=1, expired=1, skipped=0)
    assert second == ExpiryReport(listed=0, expired=0, skipped=0)
    events = [event for event in hierarchy._audit if event.kind == "ingest.expired"]
    assert len(events) == 1
