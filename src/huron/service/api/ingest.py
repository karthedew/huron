"""The raw-ingest workflow: sessions, their ledgers, and the lifecycle around them.

:class:`IngestService` is the facade the ``/ingest-sessions`` routes drive.
It follows the opposite discipline from :class:`~huron.service.api.repository.HierarchyRepository`:
no store transaction is ever held across file I/O or hashing, because a
revision's envelope on disk *is* the revision - storage leads, and the
catalog records what is already there. Every blocking call therefore runs
through :func:`asyncer.asyncify` on its own, outside any ``async with
self._hierarchy.transaction()`` block, so a slow filesystem never pins a
pool connection or the per-dataset lock a transaction would otherwise hold.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING
from uuid import UUID

from asyncer import asyncify

from huron.pkg.catalog import (
    IngestFile,
    IngestSession,
    IngestState,
    Manifest,
    ManifestEntry,
    RevisionRecord,
    UploadPlanEntry,
    compute_upload_plan,
    decode_manifest,
    ingest,
    manifest_bytes,
    uuid7,
    validate_manifest,
)
from huron.pkg.catalog.layers import Layer, LayerWorkflowError
from huron.pkg.catalog.paths import staging_dir

from .records import AuditEvent, jsonable
from .stores import Replay

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import datetime

    from huron.pkg.catalog.ports import Clock, RawStore

    from .records import Dataset
    from .stores import HierarchyStore, IdempotencyClaim, LedgerEntry

__all__ = ["IngestService", "SessionLedger"]


@dataclass(frozen=True, slots=True)
class SessionLedger:
    """One session as last read, with its files in manifest order.

    Attributes:
        session: The session's durable state.
        files: The session's planned files, in manifest order.
    """

    session: IngestSession
    files: tuple[IngestFile, ...]

    @property
    def id(self) -> UUID:
        """Return the session's identifier.

        Returns:
            The session's identifier, from its lease.
        """
        return self.session.lease.ingest_id

    @property
    def dataset_id(self) -> UUID:
        """Return the dataset the session's revision belongs to.

        Returns:
            The owning dataset's identifier, from the session's lease.
        """
        return self.session.lease.dataset_id

    @property
    def revision_id(self) -> UUID:
        """Return the revision identifier the session reserved.

        Returns:
            The reserved revision's identifier, from the session's lease.
        """
        return self.session.lease.revision_id

    @property
    def revision_number(self) -> int:
        """Return the revision number the session reserved.

        Returns:
            The reserved revision's number, from the session's lease.
        """
        return self.session.lease.revision_number

    @property
    def state(self) -> IngestState:
        """Return the session's current state.

        Returns:
            The session's position in the ingest state machine.
        """
        return self.session.state

    @property
    def etag(self) -> int:
        """Return the session's version.

        Returns:
            The value ``If-Match`` must carry back on ``/commit``.
        """
        return self.session.etag

    @property
    def expires_at(self) -> datetime:
        """Return the instant the session's lease lapses unless renewed.

        Returns:
            The lease's expiry instant, from the session's lease.
        """
        return self.session.lease.expires_at

    @property
    def created_by(self) -> str:
        """Return the principal who opened the session.

        Returns:
            The subject of the only principal, besides a project admin
            driving a force-abort, allowed to advance the session.
        """
        return self.session.created_by

    @property
    def parent_revision_id(self) -> UUID | None:
        """Return the committed revision the upload plan was computed against.

        Returns:
            The parent revision's identifier, or None for a dataset's
            first revision.
        """
        return self.session.parent_revision_id

    @property
    def manifest_sha256(self) -> str:
        """Return the content identity of the manifest the client declared.

        Returns:
            The manifest digest a commit must reproduce.
        """
        return self.session.manifest_sha256

    @property
    def part_bytes(self) -> int:
        """Return the size of one upload part, read live from the domain.

        Returns:
            The current value of :data:`huron.pkg.catalog.ingest.PART_BYTES`,
            read at call time so a test that patches it sees the change
            reflected here.
        """
        return ingest.PART_BYTES


class IngestService:
    """The raw-ingest workflow: sessions, verification and the commit that publishes a revision.

    The opposite discipline from ``HierarchyRepository``: no store
    transaction is ever held across file I/O or hashing; storage leads and
    the catalog records what is already on disk.
    """

    def __init__(self, raw_store: RawStore, hierarchy: HierarchyStore, *, clock: Clock) -> None:
        """Wire the service over the raw store and hierarchy store it drives.

        Args:
            raw_store: The store holding every session's staging envelope
                and every published revision's documents.
            hierarchy: Durable storage for ingest sessions, their ledgers,
                revisions, audit rows and outbox events.
            clock: The source of the current time; the domain never reads
                the wall clock itself.
        """
        self._raw_store = raw_store
        self._hierarchy = hierarchy
        self._clock = clock
        self._root = PurePosixPath(raw_store.root)

    async def _plan(
        self, dataset: Dataset, files: Sequence[ManifestEntry]
    ) -> tuple[Manifest, RevisionRecord | None, tuple[UploadPlanEntry, ...]]:
        """Validate the declared files and plan each one against the dataset's parent.

        Args:
            dataset: The dataset the revision is being added to; must
                declare ``raw`` as its entry layer.
            files: The files the client declared, in any order.

        Returns:
            The validated manifest, the dataset's latest committed
            revision (or None for a dataset's first revision), and the
            upload plan computed against it.

        Raises:
            LayerWorkflowError: If ``dataset``'s entry layer is not raw.
        """
        manifest = validate_manifest(files)
        if dataset.entry_layer != Layer.RAW.value:
            raise LayerWorkflowError(
                f"dataset entry layer is {dataset.entry_layer}, not raw; "
                "raw ingest sessions cannot open on it"
            )
        parent = await self._hierarchy.latest_committed_revision(dataset.id)
        parent_manifest = None
        if parent is not None:
            payload = await asyncify(self._raw_store.read_document)(
                PurePosixPath(parent.revision_path) / "manifest.json"
            )
            parent_manifest = decode_manifest(payload)
        plan = compute_upload_plan(manifest, parent_manifest, part_bytes=ingest.PART_BYTES)
        return manifest, parent, plan

    async def _reserve(
        self,
        dataset: Dataset,
        manifest: Manifest,
        parent: RevisionRecord | None,
        plan: tuple[UploadPlanEntry, ...],
        *,
        created_by: str,
        claim: IdempotencyClaim,
    ) -> IngestSession:
        """Stake the session's idempotency claim and reserve its revision number.

        Args:
            dataset: The dataset the revision is being added to.
            manifest: The validated manifest the session declares.
            parent: The revision the plan was computed against, or None.
            plan: The upload plan, one entry per manifest file.
            created_by: The principal opening the session.
            claim: The caller's idempotency claim for this request.

        Returns:
            The session an identical earlier claim already opened, read
            back in whatever state it currently holds; or the freshly
            reserved session in ``PREPARING``.
        """
        files = tuple(
            IngestFile(
                file_id=uuid7(),
                path=entry.file.path,
                size=entry.file.size,
                expected_sha256=entry.file.sha256,
                action=entry.action,
                part_count=entry.part_count,
            )
            for entry in plan
        )
        async with self._hierarchy.transaction() as writer:
            replay = await writer.claim(claim)
            if replay is not None:
                return await self._hierarchy.ingest_session(replay.resource_id)
            session = await writer.begin_ingest(
                dataset.id,
                manifest.sha256,
                created_by=created_by,
                parent_revision_id=parent.id if parent is not None else None,
                files=files,
            )
            await writer.insert_audit_event(
                self._audit(
                    "ingest.started",
                    actor=created_by,
                    subject_kind="ingest_session",
                    subject_id=session.lease.ingest_id,
                    payload=jsonable(session.lease),
                )
            )
            await writer.remember(
                claim, Replay(kind="ingest_session", resource_id=session.lease.ingest_id)
            )
            return session

    async def _open_envelope(self, session: IngestSession, manifest: Manifest) -> SessionLedger:
        """Claim the session's staging envelope and move it from PREPARING to UPLOADING.

        A session already past PREPARING - an earlier attempt's claim
        replayed back to it - is returned as its current ledger without
        touching storage again; opening an envelope is only ever done
        once per session.

        Args:
            session: The session to open; ``manifest`` is what it
                declared.
            manifest: The manifest to carry into the envelope so a later
                commit needs no separate record of what was declared.

        Returns:
            The session's ledger once the envelope is open, or as last
            read if it was already past PREPARING.

        Raises:
            Exception: Whatever staging the envelope or opening the edge
                raised, re-raised unchanged once the session has been
                failed and its dataset lock released.
        """
        if session.state is not IngestState.PREPARING:
            return await self.ledger(session.lease.ingest_id)
        ingest_id = session.lease.ingest_id
        staging = staging_dir(self._root, ingest_id)
        try:
            await asyncify(self._raw_store.create_staging)(staging)
            await asyncify(self._raw_store.write_document)(
                staging, "manifest.json", manifest_bytes(manifest)
            )
            opened = session.open(now=self._clock.now())
            async with self._hierarchy.transaction() as writer:
                await writer.update_ingest_session(opened, expected_etag=1)
        except Exception:
            await self._fail(session, actor=session.created_by)
            raise
        return await self.ledger(ingest_id)

    async def create(
        self,
        dataset: Dataset,
        *,
        files: Sequence[ManifestEntry],
        created_by: str,
        claim: IdempotencyClaim,
    ) -> SessionLedger:
        """Open a raw ingest session: plan the upload, reserve it, and stage its envelope.

        Args:
            dataset: The dataset the revision is being added to; must
                declare ``raw`` as its entry layer.
            files: The files the client declared, in any order.
            created_by: The principal opening the session.
            claim: The caller's idempotency claim for this request.

        Returns:
            The new session's ledger, in state UPLOADING.
        """
        manifest, parent, plan = await self._plan(dataset, files)
        session = await self._reserve(
            dataset, manifest, parent, plan, created_by=created_by, claim=claim
        )
        return await self._open_envelope(session, manifest)

    async def ledger(self, session_id: UUID) -> SessionLedger:
        """Read one session and its ledger, freshly, from the store.

        Args:
            session_id: The session to read.

        Returns:
            The session's current state paired with its files.
        """
        session = await self._hierarchy.ingest_session(session_id)
        files = await self._hierarchy.ingest_files(session_id)
        return SessionLedger(session=session, files=files)

    async def entry(self, file_id: UUID) -> tuple[SessionLedger, IngestFile]:
        """Read one planned file together with its session's ledger.

        Args:
            file_id: The file to read.

        Returns:
            The file's session ledger and the file's own current state.
        """
        found: LedgerEntry = await self._hierarchy.ingest_file(file_id)
        session_ledger = await self.ledger(found.ingest_id)
        return session_ledger, found.file

    async def heartbeat(self, session: IngestSession) -> SessionLedger:
        """Renew a session's lease.

        Args:
            session: The session to renew, as last read by the caller.

        Returns:
            The session's ledger, freshly read after the renewal.
        """
        renewed = session.renew(now=self._clock.now())
        async with self._hierarchy.transaction() as writer:
            await writer.renew_ingest_session(renewed)
        return await self.ledger(session.lease.ingest_id)

    async def abort(self, ledger: SessionLedger, *, actor: str, forced: bool) -> SessionLedger:
        """Abort a session, releasing the dataset lock it holds.

        Args:
            ledger: The session's ledger, as last read by the caller.
            actor: The principal driving the abort: the owner, or a
                project admin forcing it.
            forced: Whether this is a project admin's force-abort rather
                than the owner's own.

        Returns:
            The session's ledger, freshly read after the abort.
        """
        aborted = ledger.session.abort()
        kind = "ingest.force_aborted" if forced else "ingest.aborted"
        async with self._hierarchy.transaction() as writer:
            await writer.update_ingest_session(aborted, expected_etag=ledger.session.etag)
            await writer.insert_audit_event(
                self._audit(
                    kind,
                    actor=actor,
                    subject_kind="ingest_session",
                    subject_id=ledger.session.lease.ingest_id,
                    payload={},
                )
            )
        return await self.ledger(ledger.session.lease.ingest_id)

    def _audit(
        self,
        kind: str,
        *,
        actor: str,
        subject_kind: str,
        subject_id: UUID,
        payload: Mapping[str, object],
    ) -> AuditEvent:
        """Build one audit row, stamped with this service's clock.

        Args:
            kind: The audit kind, such as ``"ingest.started"``.
            actor: The principal subject that caused the event, or
                ``"system:sweep"`` for the expiry sweep.
            subject_kind: What ``subject_id`` names, such as
                ``"ingest_session"`` or ``"revision"``.
            subject_id: The session or revision the event is about.
            payload: The event's JSON-safe payload.

        Returns:
            The audit row, ready to insert inside the same transaction as
            the write it records.
        """
        return AuditEvent(
            id=uuid7(),
            kind=kind,
            actor=actor,
            subject_kind=subject_kind,
            subject_id=subject_id,
            payload=dict(payload),
            created_at=self._clock.now(),
        )

    async def _fail(self, session: IngestSession, *, actor: str) -> None:
        """Persist a session's failure and its audit row in one transaction.

        Called when a step outside any transaction - staging the
        envelope, or, later, publishing a commit's documents - raises
        before the session could advance; freeing the session's dataset
        lock and recording who was driving it when it happened.

        Args:
            session: The session that could not finish; must not already
                be terminal.
            actor: The principal recorded as having caused the failure.
        """
        failed = session.fail()
        async with self._hierarchy.transaction() as writer:
            await writer.update_ingest_session(failed, expected_etag=session.etag)
            await writer.insert_audit_event(
                self._audit(
                    "ingest.failed",
                    actor=actor,
                    subject_kind="ingest_session",
                    subject_id=session.lease.ingest_id,
                    payload={},
                )
            )
