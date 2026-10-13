"""Delegated web uploads using the existing immutable Raw publication workflow."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from huron.core.foundation.canonical import content_identity
from huron.core.foundation.retry import IdempotencyClaim, request_sha256
from huron.core.raw.ingest import IngestFile, IngestState
from huron.core.raw.manifest import validate_manifest
from huron.core.raw.retry import session_claim
from huron.core.raw.web_ports import RawRegistration
from huron.core.security.errors import Forbidden

if TYPE_CHECKING:
    import os
    from collections.abc import Callable, Iterable, Mapping, Sequence
    from pathlib import Path
    from uuid import UUID

    from huron.core.catalog.external import ExternalCatalog
    from huron.core.raw import RawIngestionService, RevisionReadService
    from huron.core.raw.manifest import ManifestEntry
    from huron.core.raw.ports import HierarchyStore
    from huron.core.raw.types import PayloadFile, RevisionRecord, SessionLedger
    from huron.core.raw.web_ports import RawPublicationStore
    from huron.core.security.raw_delegation import RawDelegation


class RawWebOperations:
    """Check target and actor ownership before invoking existing authorized Raw operations."""

    def __init__(
        self,
        delegation: RawDelegation,
        catalog: ExternalCatalog,
        persistence: HierarchyStore,
        publications: RawPublicationStore,
        ingestion: Callable[[UUID], RawIngestionService],
        revisions: Callable[[UUID], RevisionReadService],
    ) -> None:
        """Bind one verified request to durable identities and actor-bound operations.

        Args:
            delegation: Verified request identity and upstream authority.
            catalog: Durable upstream-to-backend mapping workflow.
            persistence: Authoritative session and revision ancestry.
            publications: Registration receipts and bounded revision discovery.
            ingestion: Factory binding Raw operations to the exact dataset and actor.
            revisions: Factory binding revision reads to the same dataset and actor.
        """
        self._delegation = delegation
        self._catalog = catalog
        self._persistence = persistence
        self._publications = publications
        self._ingestion = ingestion
        self._revisions = revisions

    async def _dataset(self, dataset_id: UUID, permission: str) -> None:
        """Require the capability and exact persisted target.

        Args:
            dataset_id: Authoritative dataset identity.
            permission: Required delegated operation.
        """
        self._delegation.require(permission)
        await self._catalog.resolve(self._delegation, dataset_id)

    async def _owned(self, session_id: UUID, permission: str) -> RawIngestionService:
        """Resolve persisted session ancestry and ownership before reading its ledger.

        Args:
            session_id: Requested upload identity.
            permission: Required delegated capability.

        Returns:
            The actor-bound ingestion service for its exact dataset.

        """
        session = await self._persistence.ingest_session(session_id)
        await self._dataset(session.lease.dataset_id, permission)
        self._delegation.require_scope(owner=session.created_by)
        return self._ingestion(session.lease.dataset_id)

    async def create(self, files: Sequence[ManifestEntry], key: str) -> SessionLedger:
        """Create or retry an independent upload on the exact delegated target.

        Args:
            files: Complete submitted manifest.
            key: Stable upload identity reused for retries.

        Returns:
            The new or resumed session ledger.
        """
        validate_manifest(files)
        mapping = await self._catalog.ensure(self._delegation)
        claim = session_claim(self._delegation.actor.subject, key, mapping.dataset_id, tuple(files))
        return await self._ingestion(mapping.dataset_id).create(
            mapping.dataset_id, files=files, claim=claim
        )

    async def ledger(self, session_id: UUID) -> SessionLedger:
        """Read an owned upload after current read or write authority is established.

        Args:
            session_id: Upload identity.

        Returns:
            Its authorized session ledger.
        """
        permission = "write" if "write" in self._delegation.permissions else "read"
        return await (await self._owned(session_id, permission)).ledger(session_id)

    async def advance(
        self, session_id: UUID, action: Literal["heartbeat", "verify", "abort"]
    ) -> SessionLedger:
        """Execute a bounded upload state transition through Raw's public workflow.

        Args:
            session_id: Owned upload identity.
            action: The requested transition.

        Returns:
            The resulting ledger.
        """
        ingest = await self._owned(session_id, "write")
        operations = {"heartbeat": ingest.heartbeat, "verify": ingest.verify, "abort": ingest.abort}
        return await operations[action](session_id)

    async def receive_part(
        self,
        session_id: UUID,
        file_id: UUID,
        part: int,
        chunks: Iterable[bytes],
        *,
        content_length: int,
    ) -> IngestFile:
        """Stream a signed part into the existing verified transfer workflow.

        Args:
            session_id: Owned upload identity.
            file_id: File within that upload.
            part: One-based part number.
            chunks: Exact incoming bytes, consumed without whole-part buffering.
            content_length: Actual declared transfer length.

        Returns:
            The persisted file ledger after content verification.
        """
        ingest = await self._owned(session_id, "write")
        return await ingest.receive_part(
            session_id,
            file_id,
            part,
            self._delegation.verified_chunks(chunks),
            content_length=content_length,
        )

    async def complete_file(self, session_id: UUID, file_id: UUID) -> IngestFile:
        """Verify a complete multipart file using Raw's storage checks.

        Args:
            session_id: Owned upload identity.
            file_id: File within that upload.

        Returns:
            The complete file ledger.
        """
        return await (await self._owned(session_id, "write")).complete_file(session_id, file_id)

    async def commit(
        self,
        session_id: UUID,
        *,
        expected_etag: int,
        manifest_sha256: str,
        metadata: Mapping[str, object],
        key: str,
    ) -> RevisionRecord:
        """Publish once using Raw's storage-first transaction and immutable retry receipt.

        Args:
            session_id: Owned verified upload.
            expected_etag: Last observed session version.
            manifest_sha256: Server-issued manifest digest.
            metadata: Required descriptive metadata.
            key: Stable commit retry identity.

        Returns:
            The original immutable revision, including on replay.
        """
        ingest = await self._owned(session_id, "write")
        claim = IdempotencyClaim(
            principal=self._delegation.actor.subject,
            key=key,
            request_sha256=request_sha256(
                "revision", str(session_id), manifest_sha256, content_identity(metadata)
            ),
        )
        return await ingest.commit(
            session_id,
            expected_etag=expected_etag,
            manifest_sha256=manifest_sha256,
            metadata=metadata,
            claim=claim,
        )

    async def registration(
        self, session_id: UUID, *, acknowledge: UUID | None = None
    ) -> RawRegistration | None:
        """Read or acknowledge catalog publication only for the owned committed revision.

        Pending is derived from the durable revision and absence of an acknowledgement;
        a crash after commit therefore cannot lose the work that still needs registration.

        Args:
            session_id: Owned upload identity.
            acknowledge: Exact revision whose Polaris registration the BFF verified.

        Returns:
            Durable publication state, or None before commit.

        Raises:
            Forbidden: If acknowledgement names an uncommitted or different revision.
        """
        if acknowledge is not None:
            self._delegation.require("write")
        ledger = await self.ledger(session_id)
        committed = ledger.state is IngestState.COMMITTED
        if acknowledge is not None and (not committed or ledger.revision_id != acknowledge):
            raise Forbidden("registration must name this upload's committed revision")
        if not committed:
            return None
        if acknowledge is not None:
            await self._publications.acknowledge(acknowledge)
        registered = await self._publications.registered(ledger.revision_id)
        return RawRegistration(
            state="registered" if registered else "pending",
            dataset_id=ledger.dataset_id,
            revision_id=ledger.revision_id,
        )

    async def revisions(
        self, dataset_id: UUID, *, before: int | None = None
    ) -> tuple[RevisionRecord, ...]:
        """Read at most 101 revisions to expose a bounded 100-row page and cursor.

        Args:
            dataset_id: Exact mapped dataset identity.
            before: Exclusive revision-number cursor.

        Returns:
            Authorized immutable revisions, newest first.
        """
        await self._dataset(dataset_id, "read")
        ids = await self._publications.revision_ids(dataset_id, before=before, limit=101)
        reader = self._revisions(dataset_id)
        return tuple([await reader.revision(item) for item in ids])

    async def revision(self, revision_id: UUID) -> RevisionRecord:
        """Resolve a revision's actual dataset before granting read access.

        Args:
            revision_id: Requested revision.

        Returns:
            Its authorized immutable record.
        """
        record = await self._persistence.revision(revision_id)
        await self._dataset(record.dataset_id, "read")
        return await self._revisions(record.dataset_id).revision(revision_id)

    async def manifest(self, revision_id: UUID) -> tuple[Path, os.stat_result]:
        """Read the authoritative stored manifest through the existing Raw reader.

        Args:
            revision_id: Requested revision.

        Returns:
            Its authorized document path and stat.
        """
        record = await self.revision(revision_id)
        return await self._revisions(record.dataset_id).manifest_file(record)

    async def payload(self, revision_id: UUID, path: str) -> PayloadFile:
        """Resolve a manifest-listed file without accepting arbitrary storage paths.

        Args:
            revision_id: Requested revision.
            path: Manifest-relative payload path.

        Returns:
            The authorized payload descriptor.
        """
        record = await self.revision(revision_id)
        return await self._revisions(record.dataset_id).payload_file(record, path)
