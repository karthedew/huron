"""The raw-ingest workflow: sessions, their ledgers, and the lifecycle around them.

:class:`IngestService` is private machinery driven by authorized Raw operations
and trusted deployment expiry. Applications construct it through ``RawRuntime``.
It follows the opposite discipline from the catalog's own workflows: no
store transaction is ever held across file I/O or hashing, because a
revision's envelope on disk *is* the revision - storage leads, and the
catalog records what is already there. Every blocking call therefore runs
through :func:`asyncer.asyncify` on its own, outside any ``async with
self._hierarchy.transaction()`` block, so a slow filesystem never pins a
pool connection or the per-dataset lock a transaction would otherwise hold.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, cast

from asyncer import asyncify

from huron.core.catalog.layers import Layer, LayerWorkflowError
from huron.core.foundation.canonical import canonical_bytes, jsonable, jsonable_value
from huron.core.foundation.errors import IdempotencyKeyReused, PreconditionFailed, ResourceNotFound
from huron.core.foundation.identifiers import uuid7
from huron.core.foundation.retry import Replay
from huron.core.raw import ingest
from huron.core.raw.documents import (
    CommitIntent,
    CommitRecord,
    MetadataDocument,
    RevisionIndex,
    decode_manifest,
    manifest_bytes,
    revision_from_storage,
)
from huron.core.raw.errors import IllegalIngestTransition, ManifestMismatch
from huron.core.raw.ingest import (
    FileState,
    IngestFile,
    IngestSession,
    IngestState,
    UploadPlanEntry,
    compute_upload_plan,
    revision_committed,
)
from huron.core.raw.manifest import Manifest, ManifestEntry, validate_manifest
from huron.core.raw.paths import revision_dir, staging_dir, staging_paths
from huron.core.raw.types import AuditEvent, ExpiryReport, RevisionRecord, SessionLedger
from huron.core.security.rules import Visibility
from huron.schema.storage import PartLengthMismatchError

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from datetime import datetime
    from uuid import UUID

    from huron.core.catalog.types import Dataset
    from huron.core.foundation.canonical import JsonValue
    from huron.core.foundation.clock import Clock
    from huron.core.raw.ports import HierarchyStore, RawStore
from huron.core.foundation.retry import IdempotencyClaim
from huron.core.raw.types import LedgerEntry

__all__ = ["SWEEP_ACTOR", "ExpiryReport", "IngestService", "SessionLedger"]

logger = logging.getLogger(__name__)

#: The actor recorded on every ``ingest.expired`` audit row; no ingest
#: session is ever opened, driven or aborted by a human under this name.
SWEEP_ACTOR = "system:sweep"


class _MeasuredChunks:
    """An iterator over a byte stream that records the total length it has yielded.

    Wraps the generator bridging a request body into :meth:`RawStore.write_part`
    so a stream that ends short or long can report exactly how many bytes it
    delivered, without the store's own exception needing to carry that count.
    """

    __slots__ = ("_source", "total")

    def __init__(self, source: Iterable[bytes]) -> None:
        """Wrap ``source``, tracking the total length of every chunk it yields.

        Args:
            source: The byte stream to measure while passing it through.
        """
        self._source = iter(source)
        self.total = 0

    def __iter__(self) -> _MeasuredChunks:
        """Return this object, since it is already an iterator.

        Returns:
            This same object.
        """
        return self

    def __next__(self) -> bytes:
        """Return the next chunk, adding its length to ``total``.

        Returns:
            The next chunk from the wrapped source; the wrapped source's
            own ``StopIteration`` ends this iterator in turn.
        """
        chunk = next(self._source)
        self.total += len(chunk)
        return chunk


class IngestService:
    """The raw-ingest workflow: sessions, verification and the commit that publishes a revision.

    The opposite discipline from the catalog's own workflows: no store
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

    def _plan(
        self, dataset: Dataset, files: Sequence[ManifestEntry]
    ) -> tuple[Manifest, tuple[UploadPlanEntry, ...]]:
        """Validate an independent collection and plan every file for upload.

        Args:
            dataset: The target dataset, whose entry layer must be raw.
            files: Every file in the submitted revision.

        Returns:
            The validated manifest and complete upload plan.

        Raises:
            LayerWorkflowError: If the dataset does not accept Raw ingestion.
        """
        manifest = validate_manifest(files)
        if dataset.entry_layer != Layer.RAW.value:
            raise LayerWorkflowError(
                f"dataset entry layer is {dataset.entry_layer}, not raw; "
                "raw ingest sessions cannot open on it"
            )
        return manifest, compute_upload_plan(manifest, part_bytes=ingest.PART_BYTES)

    async def _reserve(
        self,
        dataset: Dataset,
        manifest: Manifest,
        plan: tuple[UploadPlanEntry, ...],
        *,
        created_by: str,
        claim: IdempotencyClaim,
    ) -> IngestSession:
        """Stake the session's idempotency claim and reserve its revision number.

        Args:
            dataset: The dataset the revision is being added to.
            manifest: The validated manifest the session declares.
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
                staging / "envelope", "manifest.json", manifest_bytes(manifest)
            )
            opened = session.open(now=self._clock.now())
            async with self._hierarchy.transaction() as writer:
                await writer.update_ingest_session(opened, expected_etag=session.etag)
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
        manifest, plan = self._plan(dataset, files)
        session = await self._reserve(dataset, manifest, plan, created_by=created_by, claim=claim)
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

    async def expire_lapsed(self, *, limit: int) -> ExpiryReport:
        """Flip up to ``limit`` lapsed sessions to ABORTED, oldest lease first.

        The current instant is read once for the whole pass, so the
        listing, each flip's fence, ``session.expire``'s own guard and the
        audit row's timestamp all judge the same moment. A session lapsed
        at that instant but renewed, or flipped by another writer, before
        its own transaction here lands is left exactly as the winner left
        it: its transaction's fence refuses the write, and the row is
        counted as skipped rather than expired.

        Args:
            limit: The maximum number of sessions to flip in this pass.

        Returns:
            How many sessions were read, how many were flipped, and how
            many lost their race to another writer.
        """
        now = self._clock.now()
        lapsed = await self._hierarchy.lapsed_ingest_sessions(now, limit=limit)
        expired = skipped = 0
        for session in lapsed:
            aborted = session.expire(now=now)
            try:
                async with self._hierarchy.transaction() as writer:
                    await writer.expire_ingest_session(aborted, expected_etag=session.etag, now=now)
                    await writer.insert_audit_event(
                        self._audit(
                            "ingest.expired",
                            actor=SWEEP_ACTOR,
                            subject_kind="ingest_session",
                            subject_id=session.lease.ingest_id,
                            payload={
                                "state": session.state.value,
                                "expires_at": jsonable_value(session.lease.expires_at),
                                "dataset_id": jsonable_value(session.lease.dataset_id),
                            },
                            now=now,
                        )
                    )
            except PreconditionFailed:
                skipped += 1
            else:
                expired += 1
        return ExpiryReport(listed=len(lapsed), expired=expired, skipped=skipped)

    async def receive_part(
        self,
        ledger: SessionLedger,
        file: IngestFile,
        part: int,
        chunks: Iterable[bytes],
        *,
        content_length: int,
    ) -> IngestFile:
        """Stream one part's bytes into its range of the upload input.

        Every refusal but a stream that ends short or long, or a client
        disconnect, is raised before ``chunks`` is ever pulled from. The
        ledger records the part only once its bytes are durable, and is
        never touched at all when a single-part file's whole-file
        observation turns out not to match the manifest.

        Args:
            ledger: The file's session, as last read by the caller.
            file: The planned file the part belongs to, as last read.
            part: The 1-based part number the client is sending.
            chunks: The part's bytes, pulled from the request body.
            content_length: The request's declared ``Content-Length``.

        Returns:
            The file as persisted: the part recorded, and completed if
            this was its only part and the observation matched the
            manifest.
        """
        now = self._clock.now()
        offset, length = self._authorize_part(
            ledger, file, part, content_length=content_length, now=now
        )
        digest = await self._observe_part(ledger, file, part, chunks, offset=offset, length=length)
        updated = await self._record_part(ledger, file, part, length=length, digest=digest)
        renewed = ledger.session.renew(now=now)
        async with self._hierarchy.transaction() as writer:
            await writer.renew_ingest_session(renewed)
        return updated

    def _authorize_part(
        self,
        ledger: SessionLedger,
        file: IngestFile,
        part: int,
        *,
        content_length: int,
        now: datetime,
    ) -> tuple[int, int]:
        """Refuse everything a part upload can reject before its first byte is read.

        Args:
            ledger: The file's session, as last read by the caller.
            file: The planned file the part belongs to, as last read.
            part: The 1-based part number the client is sending.
            content_length: The request's declared ``Content-Length``.
            now: The instant to judge the session's lease against.

        Returns:
            The byte range, ``(offset, length)``, this part must occupy.

        Raises:
            IllegalIngestTransition: If the session is not UPLOADING, or
                the file is already COMPLETE.
            ResourceNotFound: If ``part`` is outside the file's plan.
            ManifestMismatch: If ``content_length`` disagrees with the
                part's planned length.
        """
        ledger.session.require(IngestState.UPLOADING, now=now)
        if file.state is FileState.COMPLETE:
            raise IllegalIngestTransition(
                f"{file.path} cannot receive a part in its current state",
                context={"state": file.state, "operation": "receive_part"},
            )
        if part < 1 or part > file.part_count:
            raise ResourceNotFound(f"part {part} is outside the plan for {file.path}")
        part_bytes = ingest.PART_BYTES
        offset = (part - 1) * part_bytes
        length = part_bytes if part < file.part_count else file.size - offset
        if content_length != length:
            raise ManifestMismatch(
                f"{file.path} part {part}'s Content-Length disagrees with the plan",
                context={
                    "path": file.path,
                    "part": part,
                    "expected_length": length,
                    "content_length": content_length,
                },
            )
        return offset, length

    async def _observe_part(
        self,
        ledger: SessionLedger,
        file: IngestFile,
        part: int,
        chunks: Iterable[bytes],
        *,
        offset: int,
        length: int,
    ) -> str:
        """Write one part's range into the upload input, on a worker thread.

        Args:
            ledger: The file's session, as last read by the caller.
            file: The planned file the part belongs to.
            part: The 1-based part number being written.
            chunks: The part's bytes, pulled from the request body.
            offset: The first byte position the range writes to.
            length: The exact number of bytes the range must contain.

        Returns:
            The hex SHA-256 of the bytes written.

        Raises:
            ManifestMismatch: If the stream delivered a different number
                of bytes than ``length``.
        """
        payload = staging_dir(self._root, ledger.id)
        measured = _MeasuredChunks(chunks)
        try:
            return await asyncify(self._raw_store.write_part)(
                payload, str(file.file_id), measured, offset=offset, length=length
            )
        except PartLengthMismatchError as exc:
            raise ManifestMismatch(
                f"{file.path} part {part} delivered a different number of bytes than planned",
                context={
                    "path": file.path,
                    "part": part,
                    "expected_length": length,
                    "observed_length": measured.total,
                },
            ) from exc

    async def _record_part(
        self, ledger: SessionLedger, file: IngestFile, part: int, *, length: int, digest: str
    ) -> IngestFile:
        """Apply one part's arrival to the ledger, retrying past a write that raced it.

        A single-part observation that disagrees with the manifest propagates
        ``ManifestMismatch`` without recording the part, allowing an immediate retry.

        Args:
            ledger: The file's session, as last read by the caller.
            file: The file as last read, before this part arrived.
            part: The 1-based part number that was durably written.
            length: The observed length of the bytes just written.
            digest: The observed SHA-256 of the bytes just written.

        Returns:
            The file as persisted: the part recorded, and completed if
            this was its only part and the observation matched the
            manifest.
        """
        current = file
        while True:
            if current.state is FileState.COMPLETE:
                return current
            updated = current.part_received(part)
            if updated.part_count == 1:
                updated.completed(observed_size=length, observed_sha256=digest)
                return await self._materialize_file(ledger, updated)
            try:
                async with self._hierarchy.transaction() as writer:
                    await writer.update_ingest_file(
                        ledger.id, updated, expected_parts=current.completed_parts
                    )
            except PreconditionFailed:
                current = await self._current_upload_file(file.file_id)
                continue
            return updated

    async def complete_file(self, ledger: SessionLedger, file: IngestFile) -> IngestFile:
        """Durably install a fully received file before recording COMPLETE.

        Args:
            ledger: The owning session ledger.
            file: The submitted file's current ledger entry.

        Returns:
            The idempotent COMPLETE result.

        Raises:
            IllegalIngestTransition: If not all upload parts are recorded.
        """
        ledger.session.require(IngestState.UPLOADING, now=self._clock.now())
        if not file.received:
            raise IllegalIngestTransition(
                f"{file.path} is not ready to be completed",
                context={"state": file.state, "operation": "complete_file"},
            )
        return await self._materialize_file(ledger, file)

    async def _current_upload_file(self, file_id: UUID) -> IngestFile:
        entry = await self._hierarchy.ingest_file(file_id)
        if entry.file.state is not FileState.COMPLETE:
            session = await self._hierarchy.ingest_session(entry.ingest_id)
            session.require(IngestState.UPLOADING, now=self._clock.now())
        return entry.file

    async def _materialize_file(self, ledger: SessionLedger, file: IngestFile) -> IngestFile:
        size, digest = await asyncify(self._raw_store.finish_file)(
            staging_dir(self._root, ledger.id),
            str(file.file_id),
            file.path,
            expected_size=file.size,
            expected_sha256=file.expected_sha256,
        )
        current = await self._current_upload_file(file.file_id)
        while True:
            if current.state is FileState.COMPLETE:
                return current
            try:
                updated = replace(current, completed_parts=file.completed_parts).completed(
                    observed_size=size, observed_sha256=digest
                )
            except ManifestMismatch:
                try:
                    async with self._hierarchy.transaction() as writer:
                        await writer.update_ingest_file(
                            ledger.id,
                            replace(current, completed_parts=frozenset()),
                            expected_parts=current.completed_parts,
                        )
                except PreconditionFailed:
                    current = await self._current_upload_file(file.file_id)
                    continue
                raise
            try:
                async with self._hierarchy.transaction() as writer:
                    await writer.update_ingest_file(
                        ledger.id, updated, expected_parts=current.completed_parts
                    )
            except PreconditionFailed:
                current = await self._current_upload_file(file.file_id)
                continue
            await asyncify(self._raw_store.discard_file)(
                staging_dir(self._root, ledger.id), str(file.file_id)
            )
            return updated

    async def verify(self, ledger: SessionLedger) -> SessionLedger:
        """Verify that every submitted file is complete before publication.

        Args:
            ledger: The session and its current file ledger.

        Returns:
            The freshly read ledger after its transition to VERIFYING.
        """
        verified = ledger.session.verify(ledger.files, now=self._clock.now())
        async with self._hierarchy.transaction() as writer:
            await writer.update_ingest_session(verified, expected_etag=ledger.session.etag)
        return await self.ledger(ledger.id)

    async def _read_declared_manifest(self, ledger: SessionLedger, final: PurePosixPath) -> bytes:
        """Read the session's declared manifest from wherever it currently sits.

        Ordinarily that is the staging envelope; a retry landing after the
        rename finds the staged envelope absent and falls back to the envelope
        published at ``final``. The session root, upload inputs and completion
        candidates may still remain in staging.

        Args:
            ledger: The session's ledger, as last read by the caller.
            final: The revision directory the envelope publishes as.

        Returns:
            The manifest's bytes, exactly as stored.
        """
        try:
            return await asyncify(self._raw_store.read_document)(
                staging_paths(self._root, ledger.id).envelope / "manifest.json"
            )
        except FileNotFoundError:
            return await asyncify(self._raw_store.read_document)(final / "manifest.json")

    async def _compose_commit(
        self,
        ledger: SessionLedger,
        metadata: Mapping[str, object],
        committed_by: str,
        now: datetime,
    ) -> tuple[Manifest, MetadataDocument, PurePosixPath]:
        """Read back the declared manifest and compose the commit's metadata document.

        Args:
            ledger: The session's ledger, as last read by the caller.
            metadata: The committer's descriptive metadata submission.
            committed_by: The principal driving the commit.
            now: The instant the commit began.

        Returns:
            The manifest, read back from wherever it currently is and
            revalidated against its own bytes; the composed metadata
            document; and the revision directory the envelope publishes
            as, built once from the dataset's real hierarchy records.

        Raises:
            RuntimeError: If the manifest's identity does not match what
                the session declared - storage and the catalog disagree.
        """
        dataset = await self._hierarchy.datasets.get(ledger.dataset_id, Visibility.ALL)
        project = await self._hierarchy.projects.get(dataset.project_id, Visibility.ALL)
        organization = await self._hierarchy.organizations.get(
            project.organization_id, Visibility.ALL
        )
        final = revision_dir(
            self._root, organization, project, dataset, ledger.revision_number, ledger.revision_id
        )
        payload = await self._read_declared_manifest(ledger, final)
        manifest = decode_manifest(payload)
        if manifest.sha256 != ledger.manifest_sha256:
            raise RuntimeError(
                f"staged manifest {manifest.sha256} does not match the session's declared "
                f"identity {ledger.manifest_sha256}"
            )
        doc = MetadataDocument.compose(
            cast("Mapping[str, JsonValue]", metadata),
            manifest=manifest,
            organization=organization,
            project=project,
            dataset=dataset,
            revision_number=ledger.revision_number,
            committed_by=committed_by,
            committed_at=now,
            data_classification=project.data_classification,
        )
        return manifest, doc, final

    async def _publish_envelope(
        self,
        session: IngestSession,
        intent: CommitIntent,
        final: PurePosixPath,
    ) -> RevisionRecord:
        """Publish only the verified envelope using its frozen evidence.

        Args:
            session: The fenced session.
            intent: Immutable canonical command and documents.
            final: Authoritative publication path.

        Returns:
            The fully validated published revision.
        """
        staging = staging_paths(self._root, session.lease.ingest_id).envelope
        manifest = decode_manifest(intent.manifest)
        files = tuple((file.path, file.size, file.sha256) for file in manifest.files)
        try:
            await asyncify(self._raw_store.stat_document)(final)
        except FileNotFoundError:
            try:
                for name, payload in intent.documents.items():
                    await asyncify(self._raw_store.write_document)(staging, name, payload)
                await asyncify(self._raw_store.verify_envelope)(staging, files, intent.documents)
                await asyncify(self._raw_store.seal)(staging)
                await asyncify(self._raw_store.commit_envelope)(staging, final)
            except (OSError, ValueError):
                await asyncify(self._raw_store.verify_envelope)(
                    final, files, intent.documents, sealed=True
                )
        await asyncify(self._raw_store.verify_envelope)(final, files, intent.documents, sealed=True)
        await asyncify(self._raw_store.commit_envelope)(staging, final)
        return revision_from_storage(
            intent.committed, intent.metadata, session=session, revision_path=str(final)
        )

    async def _record_revision(
        self,
        committing: IngestSession,
        record: RevisionRecord,
        claim: IdempotencyClaim,
        now: datetime,
    ) -> RevisionRecord:
        """Record the published revision and its events in one short transaction.

        Runs only after the envelope's rename is durable, so nothing here
        touches a file or holds a lock across I/O; the transaction is the
        catalog catching up with what storage already made true.

        Args:
            committing: The session driving the commit, in COMMITTING.
            record: The revision the envelope already publishes.
            claim: The caller's idempotency claim for this request.
            now: The instant the commit's outbox event is stamped with.

        Returns:
            The revision an identical earlier claim already recorded, or
            ``record`` itself once freshly recorded.

        Raises:
            PreconditionFailed: If the commit driver no longer owns the session.
        """
        async with self._hierarchy.transaction() as writer:
            replay = await writer.claim(claim)
            if replay is not None and replay.kind == "revision":
                return await self._hierarchy.revision(replay.resource_id)
            current = await writer.lock_ingest_session(committing.lease.ingest_id)
            if current.state is IngestState.COMMITTED:
                await writer.remember(claim, Replay(kind="revision", resource_id=record.id))
                return await self._hierarchy.revision(record.id)
            if current.etag != committing.etag or current.state is not IngestState.COMMITTING:
                raise PreconditionFailed("commit driver no longer owns the session")
            await writer.insert_revision(record)
            committed = committing.commit()
            await writer.update_ingest_session(committed, expected_etag=committing.etag)
            await writer.insert_audit_event(
                self._audit(
                    "revision.committed",
                    actor=record.committed_by,
                    subject_kind="revision",
                    subject_id=record.id,
                    payload=jsonable(record),
                )
            )
            await writer.insert_outbox_event(
                revision_committed(record, event_id=uuid7(), created_at=now)
            )
            await writer.remember(claim, Replay(kind="revision", resource_id=record.id))
        return record

    async def _write_index(self, record: RevisionRecord) -> None:
        """Extend the dataset's revision index with the freshly published revision.

        Best-effort: a reader can always rebuild ``INDEX.json`` from the
        revision directories themselves, so a failure here must never turn
        an already-successful commit into a failed response.

        Args:
            record: The revision the index gains an entry for.
        """
        index_path = PurePosixPath(record.revision_path).parent / "INDEX.json"
        try:
            try:
                existing = await asyncify(self._raw_store.read_document)(index_path)
                index = RevisionIndex.decode(existing)
            except FileNotFoundError:
                index = RevisionIndex.empty(record.dataset_id)
            await asyncify(self._raw_store.atomic_replace)(
                index_path, index.including(record).canonical
            )
        except Exception:
            logger.exception(
                "failed to update the revision index for dataset %s", record.dataset_id
            )

    async def commit(
        self,
        ledger: SessionLedger,
        *,
        expected_etag: int,
        manifest_sha256: str,
        metadata: Mapping[str, object],
        committed_by: str,
        claim: IdempotencyClaim,
    ) -> RevisionRecord:
        """Publish a verified session's envelope as a committed revision.

        The first COMMITTING transition freezes canonical evidence atomically.
        Every retry checks the same command and validates the exact stored
        documents and payload, even after COMMITTED. A stale etag may recover
        an existing intent but cannot start a different commit. Publication and
        its revision/events transaction are idempotent; the derived index update
        remains best-effort.

        Args:
            ledger: The session's ledger, as last read by the caller.
            expected_etag: The version the caller's ``If-Match`` names.
            manifest_sha256: The manifest identity the caller is
                committing.
            metadata: The committer's descriptive metadata submission.
            committed_by: The principal driving the commit.
            claim: The caller's idempotency claim for this request.

        Returns:
            The committed revision: freshly published, recovered from a
            replayed claim, or rebuilt from a retry past the rename.

        Raises:
            ManifestMismatch: If the requested manifest differs from the session's identity.
            PreconditionFailed: If a VERIFYING session's etag does not match ``expected_etag``.
            IdempotencyKeyReused: If the key is bound to another operation or session.
        """
        if ledger.state is IngestState.VERIFYING and expected_etag != ledger.etag:
            raise PreconditionFailed(f"ingest session version conflict: {ledger.id}")
        now = self._clock.now()
        manifest, doc, final = await self._compose_commit(ledger, metadata, committed_by, now)
        if manifest_sha256 != ledger.manifest_sha256:
            raise ManifestMismatch("manifest does not match the session's declared identity")
        proposed = ledger.session
        if ledger.state is not IngestState.COMMITTED:
            proposed = proposed.begin_commit(manifest_sha256=manifest_sha256, now=now)
        marker = CommitRecord(
            revision_id=ledger.revision_id,
            dataset_id=ledger.dataset_id,
            revision_number=ledger.revision_number,
            manifest_sha256=manifest.sha256,
            metadata_sha256=doc.sha256,
            file_count=len(manifest.files),
            total_bytes=manifest.total_bytes,
            committed_by=committed_by,
            committed_at=now,
        )
        intent = CommitIntent(
            canonical_bytes(metadata), manifest_bytes(manifest), doc.canonical, marker.canonical
        )
        async with self._hierarchy.transaction() as writer:
            replay = await writer.claim(claim)
            if replay is not None and replay not in (
                Replay(kind="ingest_commit", resource_id=ledger.id),
                Replay(kind="revision", resource_id=ledger.revision_id),
            ):
                raise IdempotencyKeyReused("idempotency key belongs to another operation")
            committing, frozen = await writer.freeze_commit(
                proposed, intent, expected_etag=ledger.etag
            )
            if replay is None:
                await writer.remember(claim, Replay(kind="ingest_commit", resource_id=ledger.id))
        record = await self._publish_envelope(committing, frozen, final)
        published = await self._record_revision(committing, record, claim, record.committed_at)
        await self._write_index(published)
        return published

    def _audit(
        self,
        kind: str,
        *,
        actor: str,
        subject_kind: str,
        subject_id: UUID,
        payload: Mapping[str, object],
        now: datetime | None = None,
    ) -> AuditEvent:
        """Build one audit row, stamped with ``now`` or a fresh read of this service's clock.

        Args:
            kind: The audit kind, such as ``"ingest.started"``.
            actor: The principal subject that caused the event, or
                ``"system:sweep"`` for the expiry sweep.
            subject_kind: What ``subject_id`` names, such as
                ``"ingest_session"`` or ``"revision"``.
            subject_id: The session or revision the event is about.
            payload: The event's JSON-safe payload.
            now: The instant to stamp the row with. Defaults to a fresh
                clock read; the expiry sweep passes the instant its own
                pass already read, so the row's timestamp matches the
                fence it was written under exactly.

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
            created_at=now if now is not None else self._clock.now(),
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
