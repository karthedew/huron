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

import logging
from dataclasses import dataclass, replace
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, cast
from uuid import UUID

from asyncer import asyncify

from huron.pkg.catalog import (
    CommitRecord,
    FileState,
    IngestFile,
    IngestSession,
    IngestState,
    Manifest,
    ManifestEntry,
    MetadataDocument,
    RevisionIndex,
    RevisionRecord,
    UploadAction,
    UploadPlanEntry,
    compute_upload_plan,
    decode_manifest,
    ingest,
    manifest_bytes,
    revision_committed,
    revision_from_storage,
    revision_record,
    uuid7,
    validate_manifest,
)
from huron.pkg.catalog.errors import (
    IllegalIngestTransition,
    ManifestMismatch,
    PreconditionFailed,
    ResourceNotFound,
)
from huron.pkg.catalog.layers import Layer, LayerWorkflowError
from huron.pkg.catalog.manifest import JsonValue
from huron.pkg.catalog.paths import revision_dir, staging_dir
from huron.pkg.rawstore import PartLengthMismatchError
from huron.pkg.rbac import Visibility

from .records import AuditEvent, jsonable
from .stores import Replay

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from datetime import datetime

    from huron.pkg.catalog.ports import Clock, RawStore

    from .records import Dataset
    from .stores import HierarchyStore, IdempotencyClaim, LedgerEntry

__all__ = ["IngestService", "SessionLedger"]

logger = logging.getLogger(__name__)


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

    async def receive_part(
        self,
        ledger: SessionLedger,
        file: IngestFile,
        part: int,
        chunks: Iterable[bytes],
        *,
        content_length: int,
    ) -> IngestFile:
        """Stream one part's bytes into its range of the payload file.

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
                the file is a hardlink or already COMPLETE.
            ResourceNotFound: If ``part`` is outside the file's plan.
            ManifestMismatch: If ``content_length`` disagrees with the
                part's planned length.
        """
        ledger.session.require(IngestState.UPLOADING, now=now)
        if file.action is UploadAction.HARDLINK or file.state is FileState.COMPLETE:
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
        """Write one part's range into the payload file, on a worker thread.

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
        payload = staging_dir(self._root, ledger.id) / "payload"
        measured = _MeasuredChunks(chunks)
        try:
            return await asyncify(self._raw_store.write_part)(
                payload, file.path, measured, offset=offset, length=length
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

        Raises:
            ManifestMismatch: If this is a single-part file and the
                whole-file observation does not match the manifest; the
                payload is discarded and the ledger is left exactly as it
                was, so the same part can be re-sent immediately.
        """
        payload = staging_dir(self._root, ledger.id) / "payload"
        current = file
        while True:
            updated = current.part_received(part)
            if updated.part_count == 1:
                try:
                    updated = updated.completed(observed_size=length, observed_sha256=digest)
                except ManifestMismatch:
                    await asyncify(self._raw_store.discard_file)(payload, file.path)
                    raise
            try:
                async with self._hierarchy.transaction() as writer:
                    await writer.update_ingest_file(
                        ledger.id, updated, expected_parts=current.completed_parts
                    )
            except PreconditionFailed:
                entry = await self._hierarchy.ingest_file(file.file_id)
                current = entry.file
                continue
            return updated

    async def complete_file(self, ledger: SessionLedger, file: IngestFile) -> IngestFile:
        """Assemble and verify one file's uploaded parts.

        Args:
            ledger: The file's session, as last read by the caller.
            file: The file to complete, as last read; every part it plans
                for must already be recorded.

        Returns:
            The file as persisted, in state COMPLETE.

        Raises:
            IllegalIngestTransition: If the file is not fully received, is
                a hardlink, or is already COMPLETE.
        """
        now = self._clock.now()
        ledger.session.require(IngestState.UPLOADING, now=now)
        if file.state is FileState.COMPLETE or not file.received:
            raise IllegalIngestTransition(
                f"{file.path} is not ready to be completed",
                context={"state": file.state, "operation": "complete_file"},
            )
        payload = staging_dir(self._root, ledger.id) / "payload"
        size, digest = await asyncify(self._raw_store.finish_file)(payload, file.path)
        updated = await self._finish_file(ledger, file, payload, size=size, digest=digest)
        renewed = ledger.session.renew(now=now)
        async with self._hierarchy.transaction() as writer:
            await writer.renew_ingest_session(renewed)
        return updated

    async def _finish_file(
        self,
        ledger: SessionLedger,
        file: IngestFile,
        payload: PurePosixPath,
        *,
        size: int,
        digest: str,
    ) -> IngestFile:
        """Prove a file's assembled bytes against the manifest, retrying past a race.

        Args:
            ledger: The file's session, as last read by the caller.
            file: The file as last read, before this call proves it.
            payload: The envelope's ``payload`` directory.
            size: The whole-file size the store measured.
            digest: The whole-file SHA-256 the store measured.

        Returns:
            The file as persisted, in state COMPLETE.

        Raises:
            ManifestMismatch: If the observation does not match the
                manifest; the payload is discarded and the ledger is
                persisted with no parts recorded, so every part must be
                re-sent.
        """
        current = file
        while True:
            try:
                updated = current.completed(observed_size=size, observed_sha256=digest)
            except ManifestMismatch:
                await asyncify(self._raw_store.discard_file)(payload, file.path)
                async with self._hierarchy.transaction() as writer:
                    await writer.update_ingest_file(
                        ledger.id,
                        replace(current, completed_parts=frozenset()),
                        expected_parts=current.completed_parts,
                    )
                raise
            try:
                async with self._hierarchy.transaction() as writer:
                    await writer.update_ingest_file(
                        ledger.id, updated, expected_parts=current.completed_parts
                    )
            except PreconditionFailed:
                entry = await self._hierarchy.ingest_file(file.file_id)
                current = entry.file
                continue
            return updated

    async def verify(self, ledger: SessionLedger) -> SessionLedger:
        """Link every unchanged file from the parent and move to VERIFYING.

        Every planned file must already be COMPLETE except a hardlink one
        still PENDING, which this links from the parent revision before the
        session-wide check runs. Linking is idempotent per file, so a retry
        after a partial run - one file linked, the next raising - only ever
        touches the files still PENDING.

        Args:
            ledger: The session's ledger, as last read by the caller.

        Returns:
            The session's ledger, freshly read after the transition.
        """
        now = self._clock.now()
        ledger.session.require(IngestState.UPLOADING, now=now)
        pending_links = [
            file
            for file in ledger.files
            if file.action is UploadAction.HARDLINK and file.state is FileState.PENDING
        ]
        linked_by_id: dict[UUID, IngestFile] = {}
        if pending_links and ledger.parent_revision_id is not None:
            parent = await self._hierarchy.revision(ledger.parent_revision_id)
            parent_payload = PurePosixPath(parent.revision_path) / "payload"
            staging_payload = staging_dir(self._root, ledger.id) / "payload"
            for file in pending_links:
                await asyncify(self._raw_store.hardlink_from_parent)(
                    parent_payload, staging_payload, file.path
                )
                linked = file.linked()
                async with self._hierarchy.transaction() as writer:
                    await writer.update_ingest_file(
                        ledger.id, linked, expected_parts=file.completed_parts
                    )
                linked_by_id[file.file_id] = linked
        files = tuple(linked_by_id.get(file.file_id, file) for file in ledger.files)
        verified = ledger.session.verify(files, now=now)
        async with self._hierarchy.transaction() as writer:
            await writer.update_ingest_session(verified, expected_etag=ledger.session.etag)
        return await self.ledger(ledger.id)

    async def _read_declared_manifest(self, ledger: SessionLedger, final: PurePosixPath) -> bytes:
        """Read the session's declared manifest from wherever it currently sits.

        Ordinarily that is the staging envelope; a retry landing after the
        rename finds no staging left at all, only the envelope already
        published at ``final``, so the read falls back there.

        Args:
            ledger: The session's ledger, as last read by the caller.
            final: The revision directory the envelope publishes as.

        Returns:
            The manifest's bytes, exactly as stored.
        """
        try:
            return await asyncify(self._raw_store.read_document)(
                staging_dir(self._root, ledger.id) / "manifest.json"
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
        dataset = await self._hierarchy.dataset(ledger.dataset_id, Visibility.ALL)
        project = await self._hierarchy.project(dataset.project_id, Visibility.ALL)
        organization = await self._hierarchy.organization(project.organization_id, Visibility.ALL)
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

    async def _fence_commit(
        self, session: IngestSession, manifest_sha256: str, now: datetime
    ) -> IngestSession:
        """Move the session into COMMITTING, in its own transaction.

        Args:
            session: The session as last read by the caller; must be
                VERIFYING, or already COMMITTING for a retry re-entering
                past the rename.
            manifest_sha256: The manifest identity the caller is
                committing.
            now: The instant to judge the session's lease against, unless
                it is already COMMITTING.

        Returns:
            The session in COMMITTING, its etag advanced.
        """
        committing = session.begin_commit(manifest_sha256=manifest_sha256, now=now)
        async with self._hierarchy.transaction() as writer:
            await writer.update_ingest_session(committing, expected_etag=session.etag)
        return committing

    async def _published_marker(self, final: PurePosixPath) -> bytes | None:
        """Return the ``COMMITTED`` marker's bytes if the envelope is already published.

        Args:
            final: The revision directory the envelope publishes as.

        Returns:
            The marker's bytes, or None if nothing is published there yet.
        """
        try:
            return await asyncify(self._raw_store.read_document)(final / "COMMITTED")
        except FileNotFoundError:
            return None

    async def _publish_envelope(
        self,
        committing: IngestSession,
        manifest: Manifest,
        doc: MetadataDocument,
        final: PurePosixPath,
        *,
        committed_by: str,
        now: datetime,
    ) -> RevisionRecord:
        """Publish the envelope's documents and seal, or reseal one already published.

        The record is built before any disk write in the publishing
        branch, because the ``COMMITTED`` marker's own bytes are its
        canonical form: the marker cannot be written until the record it
        describes exists. A failure of any of the six steps that leaves no
        marker behind fails the session outright, since nothing was
        published; one that leaves a marker behind - a crash after the
        rename - is left exactly as it is for the client's retry to read
        back, because storage, not this failed attempt, now leads. A
        retry that finds the marker already there still runs
        ``commit_envelope`` once more before reading anything back: a
        crash between the rename and the root's own seal leaves the
        published root writable, and this is the only call left to close
        that gap. That reseal (or its silent no-op once the root is
        already sealed) is never wrapped in the failure mapping below,
        because publication has already happened by the time the marker
        is visible - a fault here must leave the session COMMITTING for
        the client to retry again, never fail it outright.

        Args:
            committing: The session driving the commit, already fenced
                into COMMITTING.
            manifest: The manifest being committed.
            doc: The composed metadata document.
            final: The revision directory the envelope publishes as.
            committed_by: The principal driving the commit.
            now: The instant the commit began.

        Returns:
            The published revision record, freshly built or rebuilt from
            an envelope a previous attempt already published.

        Raises:
            OSError: If the reseal of an already-published envelope
                fails, re-raised unchanged with the session left
                COMMITTING; or if one of the publishing steps fails, once
                the session has been failed if no marker was left behind,
                re-raised unchanged either way since a marker left behind
                means the client must retry rather than see this
                attempt's failure.
            ValueError: If ``commit_envelope`` found the staged envelope
                unmarked; handled the same way as an ``OSError`` here.
        """
        staging = staging_dir(self._root, committing.lease.ingest_id)
        published = await self._published_marker(final)
        if published is not None:
            await asyncify(self._raw_store.commit_envelope)(staging, final)
            metadata_bytes = await asyncify(self._raw_store.read_document)(final / "metadata.json")
            return revision_from_storage(
                published, metadata_bytes, session=committing, revision_path=str(final)
            )
        record = revision_record(
            committing,
            manifest,
            metadata_sha256=doc.sha256,
            revision_path=str(final),
            committed_by=committed_by,
            committed_at=now,
        )
        try:
            await asyncify(self._raw_store.write_document)(
                staging, "manifest.json", manifest_bytes(manifest)
            )
            await asyncify(self._raw_store.write_document)(staging, "metadata.json", doc.canonical)
            await asyncify(self._raw_store.seal)(staging)
            await asyncify(self._raw_store.write_document)(
                staging, "COMMITTED", CommitRecord.of(record).canonical
            )
            await asyncify(self._raw_store.commit_envelope)(staging, final)
        except (OSError, ValueError):
            if await self._published_marker(final) is None:
                await self._fail(committing, actor=committed_by)
            raise
        return record

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
        """
        async with self._hierarchy.transaction() as writer:
            replay = await writer.claim(claim)
            if replay is not None:
                return await self._hierarchy.revision(replay.resource_id)
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

        A session already COMMITTED returns its revision unchanged, ahead
        of the etag check and the idempotency claim, so a retry whose key
        has lapsed and whose etag has gone stale still recovers the same
        result. Otherwise the etag must match before anything else runs:
        the commit's documents are composed and validated, the session is
        fenced into COMMITTING (accepting a retry already there), the
        envelope is published - or, for a retry past the rename, read back
        from what is already published - and the result recorded in one
        short transaction. The index update that follows is best-effort
        and never affects what is returned.

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
            PreconditionFailed: If the session is not already COMMITTED
                and ``expected_etag`` does not match its current etag.
        """
        if ledger.state is IngestState.COMMITTED:
            return await self._hierarchy.revision(ledger.revision_id)
        if expected_etag != ledger.etag:
            raise PreconditionFailed(f"ingest session version conflict: {ledger.id}")
        now = self._clock.now()
        manifest, doc, final = await self._compose_commit(ledger, metadata, committed_by, now)
        committing = await self._fence_commit(ledger.session, manifest_sha256, now)
        record = await self._publish_envelope(
            committing, manifest, doc, final, committed_by=committed_by, now=now
        )
        published = await self._record_revision(committing, record, claim, now)
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
