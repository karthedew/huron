"""Pure raw-ingest state and upload-plan mechanics.

A raw revision arrives through an ingest session: the client declares a
manifest, uploads every declared file, and the
service verifies and commits the result as one atomic envelope. This module
holds the session's state machine and lease arithmetic, the per-file ledger
that tracks upload progress, and the plan that divides each file into upload parts. Every value is
immutable and every operation returns a new value; persistence, I/O and
clocks belong to the service that drives the session.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from math import ceil
from typing import TYPE_CHECKING

from .errors import IllegalIngestTransition, IngestSessionExpired, ManifestMismatch
from .types import OutboxEvent, RevisionRecord

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from uuid import UUID

    from .manifest import Manifest, ManifestEntry

LEASE_TTL = timedelta(hours=2)  # renewed by renew and by every accepted part
PART_BYTES = 64 * 1024**2  # one upload part; a file needs max(1, ceil(size / PART_BYTES)) of them


class IngestState(StrEnum):
    """The normal, recovery and terminal states of one ingest session.

    The happy path is ``PREPARING -> UPLOADING -> VERIFYING -> COMMITTING ->
    COMMITTED``. ``ABORTED`` is available only before COMMITTING; ``FAILED``
    is available from every nonterminal state. COMMITTING can re-enter itself
    so a retry can finish after publication, or enter the fenced nonterminal
    state RECOVERING. RECOVERING retains the session's claims and permits
    only COMMITTED or FAILED next; it cannot abort or resume client work.
    COMMITTED, ABORTED and FAILED are terminal.
    """

    PREPARING = "PREPARING"
    UPLOADING = "UPLOADING"
    VERIFYING = "VERIFYING"
    COMMITTING = "COMMITTING"
    RECOVERING = "RECOVERING"
    COMMITTED = "COMMITTED"
    ABORTED = "ABORTED"
    FAILED = "FAILED"


TERMINAL_STATES = frozenset({IngestState.COMMITTED, IngestState.ABORTED, IngestState.FAILED})

#: Every legal edge of the ingest state machine, keyed by source state. An
#: operation that changes state consults this and nothing else; the
#: self-loop on COMMITTING is what lets a crashed commit's retry re-enter
#: and finish, rather than stranding the dataset lock until a reconciler
#: runs.
TRANSITIONS: Mapping[IngestState, frozenset[IngestState]] = {
    IngestState.PREPARING: frozenset(
        {IngestState.UPLOADING, IngestState.ABORTED, IngestState.FAILED}
    ),
    IngestState.UPLOADING: frozenset(
        {IngestState.VERIFYING, IngestState.ABORTED, IngestState.FAILED}
    ),
    IngestState.VERIFYING: frozenset(
        {IngestState.COMMITTING, IngestState.ABORTED, IngestState.FAILED}
    ),
    IngestState.COMMITTING: frozenset(
        {IngestState.COMMITTING, IngestState.RECOVERING, IngestState.COMMITTED, IngestState.FAILED}
    ),
    IngestState.RECOVERING: frozenset({IngestState.COMMITTED, IngestState.FAILED}),
    IngestState.COMMITTED: frozenset(),
    IngestState.ABORTED: frozenset(),
    IngestState.FAILED: frozenset(),
}


class UploadAction(StrEnum):
    """The upload disposition for one file's complete bytes."""

    UPLOAD = "upload"


class FileState(StrEnum):
    """Whether a planned file's bytes are in the envelope and proven.

    ``PENDING`` means the ledger does not yet vouch for the file's bytes,
    whether none, some or all of its parts have arrived, or an observation
    was found not to match and discarded. ``COMPLETE`` means the bytes are
    proven: every part arrived and the whole-file observation matched the
    manifest. There is no
    third state; a mismatch never becomes one, it returns the file to
    ``PENDING``.
    """

    PENDING = "PENDING"
    COMPLETE = "COMPLETE"


@dataclass(frozen=True, slots=True)
class IngestLease:
    """What an ingest session has reserved: the revision it will become, and until when.

    Issued by ``begin_ingest`` when the session opens, allocating the
    revision id and number up front so the client can be told where its
    files will land. The lease lapses at ``expires_at`` unless renewed by
    :meth:`IngestSession.renew`, which is what lets an abandoned session be
    reclaimed.

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
class IngestFile:
    """One manifest entry's progress through the session: planned, arrived, proven.

    Attributes:
        file_id: The file's identifier within the session.
        path: The manifest path this file was planned for, NFC and
            beginning with ``payload/``.
        size: The size the manifest declares for this file.
        expected_sha256: The digest the manifest declares for this file.
        action: The upload disposition; every file is uploaded.
        part_count: The number of upload parts the plan allows: at least
            one, including for an empty file.
        state: Whether the ledger currently vouches for this file's bytes.
        completed_parts: The 1-based part numbers durably in the envelope.
    """

    file_id: UUID
    path: str
    size: int
    expected_sha256: str
    action: UploadAction
    part_count: int
    state: FileState = FileState.PENDING
    completed_parts: frozenset[int] = frozenset()

    @property
    def received(self) -> bool:
        """Return whether every part the plan calls for has arrived.

        Returns:
            Whether ``completed_parts`` covers ``1..part_count`` in full.
        """
        return self.completed_parts == frozenset(range(1, self.part_count + 1))

    def part_received(self, part: int) -> IngestFile:
        """Record part ``part`` as durably in the envelope.

        Args:
            part: The 1-based part number that arrived.

        Returns:
            A copy with ``part`` added to ``completed_parts``; identical to
            this file if ``part`` was already held.

        Raises:
            IllegalIngestTransition: If the file is already COMPLETE.
            ValueError: If ``part`` is outside ``1..part_count``.
        """
        if self.state is FileState.COMPLETE:
            raise IllegalIngestTransition(
                f"{self.path} cannot receive a part in its current state",
                context={"state": self.state, "operation": "part_received"},
            )
        if part < 1 or part > self.part_count:
            raise ValueError(f"part {part} is outside 1..{self.part_count} for {self.path}")
        return replace(self, completed_parts=self.completed_parts | {part})

    def completed(self, *, observed_size: int, observed_sha256: str) -> IngestFile:
        """Prove the received bytes against the manifest.

        Args:
            observed_size: The whole-file size the store measured.
            observed_sha256: The whole-file digest the store measured.

        Returns:
            A copy in state COMPLETE, with its parts unchanged.

        Raises:
            IllegalIngestTransition: If this is not a pending upload file
                with every part already received.
            ManifestMismatch: If the observation does not match the size
                or digest the manifest declared; the observation and the
                declared values travel in ``context``.
        """
        ready = (
            self.action is UploadAction.UPLOAD and self.state is FileState.PENDING and self.received
        )
        if not ready:
            raise IllegalIngestTransition(
                f"{self.path} is not ready to be proven complete",
                context={"state": self.state, "operation": "completed"},
            )
        if observed_size != self.size or observed_sha256 != self.expected_sha256:
            raise ManifestMismatch(
                f"{self.path} does not match the declared manifest",
                context={
                    "path": self.path,
                    "expected_size": self.size,
                    "observed_size": observed_size,
                    "expected_sha256": self.expected_sha256,
                    "observed_sha256": observed_sha256,
                },
            )
        return replace(self, state=FileState.COMPLETE)


@dataclass(frozen=True, slots=True)
class UploadPlanEntry:
    """The complete upload plan for one manifest entry.

    Attributes:
        file: The manifest entry the plan is for.
        action: The upload disposition; every file requires its complete bytes.
        part_count: The number of upload parts the client must send, as
            :attr:`IngestFile.part_count`.
    """

    file: ManifestEntry
    action: UploadAction
    part_count: int


@dataclass(frozen=True, slots=True)
class IngestSession:
    """One ingest session's durable state: its lease, its place in the machine, what it promised.

    Immutable: every named operation below returns a new session, bumping
    ``etag`` by one on a state edge, so a store can compare-and-swap on the
    etag and two drivers acting on stale copies cannot both win.
    :meth:`renew` is the one exception, leaving the etag untouched because
    renewing the lease is monotone and commutative, unlike a state edge.

    Attributes:
        lease: The reserved revision and the lease expiry.
        state: The session's current state.
        manifest_sha256: The content identity of the manifest the client
            declared; the commit must produce exactly this manifest.
        created_by: The principal who opened the session; the only one,
            besides a project admin driving a force-abort, allowed to
            advance it.
        etag: The session's version, starting at 1 and incremented by
            every state edge.
    """

    lease: IngestLease
    state: IngestState
    manifest_sha256: str
    created_by: str
    etag: int = 1

    def _lapsed(self, *, now: datetime) -> bool:
        """Return whether the lease has lapsed on a session still in progress.

        Args:
            now: The instant to judge the lease against.

        Returns:
            True if the session is not already terminal and its lease has
            lapsed; a terminal session is never reported as lapsed, so its
            caller's own transition check is what names the real reason.
        """
        return self.state not in TERMINAL_STATES and now >= self.lease.expires_at

    def _fence(self, *, now: datetime) -> None:
        """Raise unless the lease is live on a session still in progress.

        A terminal session never trips this (:meth:`_lapsed` says so), so
        its own transition check is what names the real refusal.

        Args:
            now: The instant to judge the lease against.

        Raises:
            IngestSessionExpired: If the session is in progress and its
                lease has lapsed.
        """
        if self._lapsed(now=now):
            raise IngestSessionExpired(
                f"ingest session {self.lease.ingest_id} has expired",
                context={"expires_at": self.lease.expires_at.isoformat()},
            )

    def _advance(self, target: IngestState, *, operation: str) -> IngestSession:
        """Move to ``target`` if :data:`TRANSITIONS` has an edge there from the current state.

        Args:
            target: The candidate next state.
            operation: The operation's name, carried in the refusal and
                its context.

        Returns:
            A copy in state ``target`` with the etag incremented.

        Raises:
            IllegalIngestTransition: If there is no edge from the current
                state to ``target``.
        """
        if target not in TRANSITIONS[self.state]:
            raise IllegalIngestTransition(
                f"cannot {operation} from {self.state}",
                context={"state": self.state, "operation": operation},
            )
        return replace(self, state=target, etag=self.etag + 1)

    def open(self, *, now: datetime) -> IngestSession:
        """Move from PREPARING to UPLOADING once the staging envelope exists.

        Refuses with :class:`IngestSessionExpired` when the lease has
        lapsed, and with :class:`IllegalIngestTransition` when the session
        is not PREPARING.

        Args:
            now: The instant to judge the lease against.

        Returns:
            A copy in state UPLOADING with the etag incremented.
        """
        self._fence(now=now)
        return self._advance(IngestState.UPLOADING, operation="open")

    def renew(self, *, now: datetime, ttl: timedelta = LEASE_TTL) -> IngestSession:
        """Extend the lease to ``now + ttl``.

        Args:
            now: The instant the renewal is judged and measured from.
            ttl: How long the renewed lease lasts from ``now``.

        Returns:
            A copy whose lease expires at ``now + ttl``; the state and
            etag are unchanged.

        Raises:
            IngestSessionExpired: If the session is terminal, is RECOVERING,
                or its lease has already lapsed.
        """
        if self.state in TERMINAL_STATES | {IngestState.RECOVERING} or now >= self.lease.expires_at:
            raise IngestSessionExpired(
                f"ingest session {self.lease.ingest_id} is not renewable",
                context={"expires_at": self.lease.expires_at.isoformat()},
            )
        return replace(self, lease=replace(self.lease, expires_at=now + ttl))

    def require(self, state: IngestState, *, now: datetime) -> None:
        """Refuse unless the session is in ``state`` with a live lease.

        Every per-file step, including part upload and whole-file completion,
        runs this first, so a driver cannot advance a file's ledger
        once its session has moved on or its lease has lapsed. Refuses with
        :class:`IngestSessionExpired` when the lease has lapsed, and with
        :class:`IllegalIngestTransition` when the session is not in
        ``state``.

        Args:
            state: The state the session must currently be in.
            now: The instant to judge the lease against.

        Raises:
            IllegalIngestTransition: If the session is not in ``state``.
        """
        self._fence(now=now)
        if self.state is not state:
            raise IllegalIngestTransition(
                f"session is {self.state}, not {state}",
                context={"state": self.state, "operation": "require"},
            )

    def verify(self, files: Sequence[IngestFile], *, now: datetime) -> IngestSession:
        """Move from UPLOADING to VERIFYING once every planned file is COMPLETE.

        The ledger is the sole authority for what has arrived; nothing is
        rehashed here. Refuses with :class:`IngestSessionExpired` when the
        lease has lapsed, and with :class:`IllegalIngestTransition` when
        the session is not UPLOADING.

        Args:
            files: Every file the session's plan calls for.
            now: The instant to judge the lease against.

        Returns:
            A copy in state VERIFYING with the etag incremented.

        Raises:
            ValueError: If ``files`` is empty.
            ManifestMismatch: If any file is not COMPLETE; ``context``
                carries the incomplete paths.
        """
        self._fence(now=now)
        moved = self._advance(IngestState.VERIFYING, operation="verify")
        if not files:
            raise ValueError("cannot verify a session with no planned files")
        incomplete = [file.path for file in files if file.state is not FileState.COMPLETE]
        if incomplete:
            raise ManifestMismatch(
                "not every planned file is complete", context={"incomplete": incomplete}
            )
        return moved

    def begin_commit(self, *, manifest_sha256: str, now: datetime) -> IngestSession:
        """Move to COMMITTING when the caller names the manifest the session declared.

        Accepts COMMITTING itself as a source, not only VERIFYING: a
        ``/commit`` retry after a crash between the envelope's rename and
        the transaction that records it must be able to re-enter and
        re-fence by etag. The lease is not consulted for that re-entry -
        once already COMMITTING, storage leads, and a lapsed lease must
        not strand a published envelope or hold its dataset lock forever.
        Refuses with :class:`IngestSessionExpired` when the lease has
        lapsed and the session is not already COMMITTING, and with
        :class:`IllegalIngestTransition` when the session is neither
        VERIFYING nor COMMITTING.

        Args:
            manifest_sha256: The manifest identity the caller is
                committing; checked against the one the session declared.
            now: The instant to judge the lease against, unless the
                session is already COMMITTING.

        Returns:
            A copy in state COMMITTING with the etag incremented.

        Raises:
            ManifestMismatch: If ``manifest_sha256`` does not match the
                session's declared manifest.
        """
        if self.state is not IngestState.COMMITTING:
            self._fence(now=now)
        moved = self._advance(IngestState.COMMITTING, operation="begin_commit")
        if manifest_sha256 != self.manifest_sha256:
            raise ManifestMismatch(
                "manifest does not match the session's declared identity",
                context={
                    "expected_sha256": self.manifest_sha256,
                    "observed_sha256": manifest_sha256,
                },
            )
        return moved

    def recover(self) -> IngestSession:
        """Fence the commit driver before recovery claims its storage.

        Returns:
            The session in RECOVERING with an advanced etag.
        """
        return self._advance(IngestState.RECOVERING, operation="recover")

    def commit(self) -> IngestSession:
        """Finish COMMITTING or RECOVERING once the envelope's rename is durable.

        Storage leads at this point, so the lease plays no part: a lease
        lapsing during a long ``fsync_tree`` must not strand a published
        envelope short of its terminal state. Refuses with
        :class:`IllegalIngestTransition` when the session is neither
        COMMITTING nor RECOVERING.

        Returns:
            A copy in state COMMITTED with the etag incremented.
        """
        return self._advance(IngestState.COMMITTED, operation="commit")

    def fail(self) -> IngestSession:
        """Move any non-terminal session to FAILED when the service cannot finish.

        The lease plays no part, matching :meth:`commit` and :meth:`abort`:
        a session that cannot finish must always be able to record that.
        Refuses with :class:`IllegalIngestTransition` when the session is
        already terminal.

        Returns:
            A copy in state FAILED with the etag incremented.
        """
        return self._advance(IngestState.FAILED, operation="fail")

    def abort(self) -> IngestSession:
        """Move PREPARING, UPLOADING or VERIFYING to ABORTED.

        Never from COMMITTING or RECOVERING: once a commit has begun the envelope may
        already be published, and aborting would record a revision as
        never having happened - true for the client's own abort, an
        admin's force-abort and the expiry sweep alike. Refuses with
        :class:`IllegalIngestTransition` when the session is COMMITTING,
        RECOVERING or already terminal.

        Returns:
            A copy in state ABORTED with the etag incremented.
        """
        return self._advance(IngestState.ABORTED, operation="abort")

    def expire(self, *, now: datetime) -> IngestSession:
        """Abort the session on the sweep's behalf, once its lease has actually lapsed.

        Refuses with :class:`IllegalIngestTransition` when the session is
        COMMITTING, RECOVERING or already terminal, even though its lease has lapsed:
        the terminal state, not the clock, names the true reason a
        finished session cannot be swept again.

        Args:
            now: The instant to judge the lease against.

        Returns:
            A copy in state ABORTED with the etag incremented.

        Raises:
            ValueError: If the lease has not lapsed; the sweep should
                never select a live session, so this is a caller bug.
        """
        if now < self.lease.expires_at:
            raise ValueError(f"ingest session {self.lease.ingest_id} has not lapsed")
        return self._advance(IngestState.ABORTED, operation="expire")


def compute_upload_plan(
    manifest: Manifest, *, part_bytes: int = PART_BYTES
) -> tuple[UploadPlanEntry, ...]:
    """Plan a complete independent upload of every declared file.

    Args:
        manifest: The validated collection being submitted.
        part_bytes: Maximum bytes in a part; must be positive.

    Returns:
        One upload entry per file, including one part for empty files.

    Raises:
        ValueError: If the part size is not positive.
    """
    if part_bytes <= 0:
        raise ValueError("part_bytes must be positive")
    return tuple(
        UploadPlanEntry(
            file=entry,
            action=UploadAction.UPLOAD,
            part_count=max(1, ceil(entry.size / part_bytes)),
        )
        for entry in manifest.files
    )


def revision_record(
    session: IngestSession,
    manifest: Manifest,
    *,
    metadata_sha256: str,
    revision_path: str,
    committed_by: str,
    committed_at: datetime,
) -> RevisionRecord:
    """Build the revision row published by a committing or recovering session.

    Args:
        session: The session driving the commit; must be COMMITTING or RECOVERING
            and must have declared ``manifest``.
        manifest: The manifest being committed, supplying its identity,
            file count and total size.
        metadata_sha256: The content identity of the committed
            ``metadata.json`` document.
        revision_path: The revision's directory in the raw store.
        committed_by: The principal driving the commit.
        committed_at: The instant the commit became durable.

    Returns:
        The row to insert alongside the session's terminal COMMITTED flip.

    Raises:
        ValueError: If ``manifest``'s identity does not match the
            session's declared manifest, or the session is neither COMMITTING
            nor RECOVERING.
    """
    if session.state not in {IngestState.COMMITTING, IngestState.RECOVERING}:
        raise ValueError("a revision record requires a committing or recovering session")
    if manifest.sha256 != session.manifest_sha256:
        raise ValueError("the manifest does not match the session's declared identity")
    return RevisionRecord(
        id=session.lease.revision_id,
        dataset_id=session.lease.dataset_id,
        number=session.lease.revision_number,
        manifest_sha256=manifest.sha256,
        metadata_sha256=metadata_sha256,
        revision_path=revision_path,
        committed_by=committed_by,
        committed_at=committed_at,
        file_count=len(manifest.files),
        total_bytes=manifest.total_bytes,
    )


def revision_committed(
    record: RevisionRecord, *, event_id: UUID, created_at: datetime
) -> OutboxEvent:
    """Build the ``revision.committed`` outbox event announcing a published revision.

    Args:
        record: The committed revision the event announces.
        event_id: The event's identifier, minted at the raise site.
        created_at: The instant the event was recorded, the same instant
            as the revision's commit.

    Returns:
        The event, subject to the revision, its payload carrying the
        revision's identity and storage location.
    """
    return OutboxEvent(
        id=event_id,
        kind="revision.committed",
        subject_id=record.id,
        payload={
            "revision_id": str(record.id),
            "dataset_id": str(record.dataset_id),
            "revision_number": record.number,
            "manifest_sha256": record.manifest_sha256,
            "revision_path": record.revision_path,
        },
        created_at=created_at,
    )
