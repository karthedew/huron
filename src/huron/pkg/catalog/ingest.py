"""Pure raw-ingest state and upload-plan mechanics.

A raw revision arrives through an ingest session: the client declares a
manifest, uploads what the parent revision does not already hold, and the
service verifies and commits the result as one atomic envelope. This module
holds the session's state machine and lease arithmetic, and the plan that
decides which files must be uploaded and which can be hard-linked from the
parent. Every value is immutable and every operation returns a new value;
persistence, I/O and clocks belong to the service that drives the session.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING

from .errors import IllegalIngestTransition, IngestSessionExpired

if TYPE_CHECKING:
    from uuid import UUID

    from .manifest import Manifest, ManifestEntry


class IngestState(StrEnum):
    """The states of one ingest session, in the order a successful ingest passes them.

    The happy path is ``PREPARING -> UPLOADING -> VERIFYING -> COMMITTING ->
    COMMITTED``. ``ABORTED`` (the client gave up) and ``FAILED`` (the service
    could not finish) are exits available from every non-terminal state
    except that a session already ``COMMITTING`` can no longer be aborted:
    once the commit has begun, it either becomes durable or fails, never
    half of each. ``COMMITTED``, ``ABORTED`` and ``FAILED`` are terminal.
    """

    PREPARING = "PREPARING"
    UPLOADING = "UPLOADING"
    VERIFYING = "VERIFYING"
    COMMITTING = "COMMITTING"
    COMMITTED = "COMMITTED"
    ABORTED = "ABORTED"
    FAILED = "FAILED"


TERMINAL_STATES = frozenset({IngestState.COMMITTED, IngestState.ABORTED, IngestState.FAILED})
_TRANSITIONS = {
    IngestState.PREPARING: frozenset(
        {IngestState.UPLOADING, IngestState.ABORTED, IngestState.FAILED}
    ),
    IngestState.UPLOADING: frozenset(
        {IngestState.VERIFYING, IngestState.ABORTED, IngestState.FAILED}
    ),
    IngestState.VERIFYING: frozenset(
        {IngestState.COMMITTING, IngestState.ABORTED, IngestState.FAILED}
    ),
    IngestState.COMMITTING: frozenset({IngestState.COMMITTED, IngestState.FAILED}),
    IngestState.COMMITTED: frozenset(),
    IngestState.ABORTED: frozenset(),
    IngestState.FAILED: frozenset(),
}


class UploadAction(StrEnum):
    """What the upload plan asks for one file: send its bytes, or reuse the parent's."""

    UPLOAD = "upload"
    HARDLINK = "hardlink"


@dataclass(frozen=True, slots=True)
class UploadPlanEntry:
    """The plan for one manifest entry: upload it, or hard-link it from the parent revision.

    Attributes:
        file: The manifest entry the plan is for.
        action: Whether the client must upload the bytes or the service can
            link them from the parent revision.
        parent_path: The path within the parent revision's payload to link
            from; set only when ``action`` is ``HARDLINK``.
    """

    file: ManifestEntry
    action: UploadAction
    parent_path: str | None = None


@dataclass(frozen=True, slots=True)
class IngestLease:
    """What an ingest session has reserved: the revision it will become, and until when.

    The metastore issues the lease when the session begins, allocating the
    revision id and number up front so the client can be told where its
    files will land. The lease lapses at ``expires_at`` unless renewed by a
    heartbeat, which is what lets an abandoned session be reclaimed.

    Attributes:
        ingest_id: The session's identifier.
        dataset_id: The dataset the revision is being added to.
        revision_id: The identifier reserved for the revision.
        revision_number: The number reserved for the revision.
        expires_at: The instant the lease lapses if not renewed.
    """

    ingest_id: UUID
    dataset_id: UUID
    revision_id: UUID
    revision_number: int
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class IngestSession:
    """One ingest session's durable state: its lease, where it is, and what it promised.

    Immutable; :meth:`transition` and :meth:`heartbeat` return a new session
    with ``etag`` incremented, so a store can compare-and-swap on the etag
    and two drivers acting on stale copies cannot both win.

    Attributes:
        lease: The reserved revision and the lease expiry.
        state: The session's current state.
        manifest_sha256: The content identity of the manifest the client
            declared; the commit must produce exactly this manifest.
        etag: The session's version, starting at 1 and incremented by every
            derived copy.
    """

    lease: IngestLease
    state: IngestState
    manifest_sha256: str
    etag: int = 1

    def transition(self, target: IngestState, *, now: datetime | None = None) -> IngestSession:
        """Return the session moved to ``target``, if the state machine and lease allow it.

        The lease is checked first: an in-progress session past its expiry
        may not advance, so a driver that lost its lease cannot commit over
        a reclaimed session. Terminal sessions skip the lease check and are
        refused by the transition table instead, so the error names the
        real reason.

        Args:
            target: The state to move to.
            now: The instant to judge the lease against; defaults to the
                current UTC time. Passed explicitly by callers with a
                :class:`~huron.pkg.catalog.ports.Clock`, and by tests.

        Returns:
            A copy in state ``target`` with the etag incremented; the lease
            is unchanged.

        Raises:
            IngestSessionExpired: If the lease has lapsed and the session is
                not already terminal.
            IllegalIngestTransition: If the state machine has no edge from
                the current state to ``target``.
        """
        current_time = now or datetime.now(UTC)
        if current_time >= self.lease.expires_at and self.state not in TERMINAL_STATES:
            raise IngestSessionExpired(f"ingest session {self.lease.ingest_id} has expired")
        if target not in _TRANSITIONS[self.state]:
            raise IllegalIngestTransition(f"cannot transition {self.state} to {target}")
        return replace(self, state=target, etag=self.etag + 1)

    def heartbeat(
        self, *, now: datetime | None = None, ttl: timedelta = timedelta(hours=2)
    ) -> IngestSession:
        """Return the session with its lease extended to ``now + ttl``.

        A lease is renewable only while the session is in progress: a
        terminal session has nothing left to protect, and a lease that has
        already lapsed is not revived, because the session may have been
        reclaimed in the meantime.

        Args:
            now: The instant the heartbeat arrived; defaults to the current
                UTC time.
            ttl: How long the renewed lease lasts from ``now``.

        Returns:
            A copy whose lease expires at ``now + ttl``, with the etag
            incremented; the state is unchanged.

        Raises:
            IngestSessionExpired: If the session is terminal or its lease
                has already lapsed.
        """
        current_time = now or datetime.now(UTC)
        if self.state in TERMINAL_STATES or current_time >= self.lease.expires_at:
            raise IngestSessionExpired(f"ingest session {self.lease.ingest_id} is not renewable")
        return replace(
            self,
            lease=replace(self.lease, expires_at=current_time + ttl),
            etag=self.etag + 1,
        )


def compute_upload_plan(
    manifest: Manifest, parent_manifest: Manifest | None = None
) -> tuple[UploadPlanEntry, ...]:
    """Decide, file by file, what the client must upload and what the parent already holds.

    A file is unchanged when the parent revision has an entry at the same
    path with the same SHA-256 and size; it is planned as a hard link from
    the parent, so a revision that touches one file in a thousand costs one
    upload and no duplicate storage. Everything else, and every file when
    there is no parent, is planned as an upload. A change of media type
    alone does not make a file an upload: the bytes are what is linked.

    Args:
        manifest: The validated manifest of the revision being ingested.
        parent_manifest: The manifest of the revision the new one builds on,
            or None for a dataset's first revision.

    Returns:
        One entry per file of ``manifest``, in the manifest's order.
    """
    parent_by_path = (
        {entry.path: entry for entry in parent_manifest.files} if parent_manifest else {}
    )
    plan: list[UploadPlanEntry] = []
    for entry in manifest.files:
        parent = parent_by_path.get(entry.path)
        unchanged = (
            parent is not None and parent.sha256 == entry.sha256 and parent.size == entry.size
        )
        plan.append(
            UploadPlanEntry(
                file=entry,
                action=UploadAction.HARDLINK if unchanged else UploadAction.UPLOAD,
                parent_path=entry.path if unchanged else None,
            )
        )
    return tuple(plan)
