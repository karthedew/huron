"""Actor-bound Raw ingestion operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from huron.pkg.catalog.layers import Layer

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from uuid import UUID

    from huron.pkg.catalog import (
        IngestFile,
        ManifestEntry,
        RevisionRecord,
    )
    from huron.pkg.catalog.persistence import IdempotencyClaim

    from ._ingest import IngestService, SessionLedger
    from .access import AccessPolicy
    from .catalog import CatalogService

from huron.pkg.catalog import validate_manifest
from huron.pkg.catalog.failures import Forbidden
from huron.pkg.catalog.layers import ensure_layer_writable
from huron.pkg.catalog.metadata import MetadataSubmission
from huron.pkg.catalog.persistence import IdempotencyClaim
from huron.pkg.rbac import ScopeType

from .idempotency import request_sha256, session_claim


class RawIngestionService:
    """Authorize every upload step before the internal ingestion workflow executes it."""

    def __init__(
        self, operations: IngestService, access: AccessPolicy, catalog: CatalogService
    ) -> None:
        """Bind upload operations to one authenticated actor.

        Args:
            operations: The ingestion implementation.
            access: The actor's current authorization policy.
            catalog: Dataset operations bound to the same actor.
        """
        self._operations = operations
        self._access = access
        self._catalog = catalog

    async def _owned(self, session_id: UUID) -> SessionLedger:
        """Resolve an owned session and require current Raw write permission.

        Args:
            session_id: The session to drive.

        Returns:
            Its freshly read ledger.

        Raises:
            Forbidden: If the actor does not own the session.
        """
        ledger = await self._operations.ledger(session_id)
        await self._access.scope(ScopeType.DATASET, ledger.dataset_id)
        if ledger.created_by != self._access.actor.subject:
            raise Forbidden("only the session owner may drive an upload")
        ensure_layer_writable(Layer.RAW, self._access.actor.kind)
        await self._access.require("data.write", ScopeType.DATASET, ledger.dataset_id, layer="raw")
        return ledger

    async def _owned_file(
        self, session_id: UUID, file_id: UUID
    ) -> tuple[SessionLedger, IngestFile]:
        """Resolve a file only after the actor may drive its stated upload.

        Args:
            session_id: The upload whose ownership and write permission are checked.
            file_id: The file that must belong to that upload.

        Returns:
            The authorized upload ledger and its addressed file.

        Raises:
            Forbidden: If the addressed file belongs to a different upload.
        """
        ledger = await self._owned(session_id)
        entry, file = await self._operations.entry(file_id)
        if entry.id != ledger.id:
            raise Forbidden("file does not belong to this upload")
        return ledger, file

    async def create(
        self,
        dataset_id: UUID,
        *,
        files: Sequence[ManifestEntry],
        claim: IdempotencyClaim,
    ) -> SessionLedger:
        """Authorize and execute create.

        A claim belonging to another actor raises ``Forbidden``.

        Args:
            dataset_id: The authoritative dataset identifier.
            files: Complete submitted manifest.
            claim: Retry identity and request fingerprint.

        Returns:
            The verified operation result.
        """
        ensure_layer_writable(Layer.RAW, self._access.actor.kind)
        await self._access.require("data.write", ScopeType.DATASET, dataset_id, layer="raw")
        dataset = await self._access.dataset(dataset_id)
        created_by = self._access.actor.subject
        self._access.require_claim(claim)
        return await self._operations.create(
            dataset, files=files, created_by=created_by, claim=claim
        )

    async def heartbeat(self, session_id: UUID) -> SessionLedger:
        """Authorize and execute heartbeat.

        Args:
            session_id: The upload identifier.

        Returns:
            The verified operation result.
        """
        ledger = await self._owned(session_id)
        session = ledger.session
        return await self._operations.heartbeat(session)

    async def abort(self, session_id: UUID) -> SessionLedger:
        """Authorize and execute abort.

        Args:
            session_id: The upload identifier.

        Returns:
            The verified operation result.
        """
        ledger = await self._operations.ledger(session_id)
        await self._access.scope(ScopeType.DATASET, ledger.dataset_id)
        forced = ledger.created_by != self._access.actor.subject
        if forced:
            await self._access.require("project.update", ScopeType.DATASET, ledger.dataset_id)
        actor = self._access.actor.subject
        return await self._operations.abort(ledger, actor=actor, forced=forced)

    async def receive_part(
        self,
        session_id: UUID,
        file_id: UUID,
        part: int,
        chunks: Iterable[bytes],
        *,
        content_length: int,
    ) -> IngestFile:
        """Authorize and execute receive part.

        A foreign owner or a file from another upload raises ``Forbidden``.

        Args:
            session_id: The upload identifier.
            file_id: The file identifier within the upload.
            part: 1-based upload part number.
            chunks: Streamed bytes for this part.
            content_length: Declared byte count.

        Returns:
            The verified operation result.
        """
        ledger, file = await self._owned_file(session_id, file_id)
        return await self._operations.receive_part(
            ledger, file, part, chunks, content_length=content_length
        )

    async def complete_file(self, session_id: UUID, file_id: UUID) -> IngestFile:
        """Authorize and execute complete file.

        A foreign owner or a file from another upload raises ``Forbidden``.

        Args:
            session_id: The upload identifier.
            file_id: The file identifier within the upload.

        Returns:
            The verified operation result.
        """
        ledger, file = await self._owned_file(session_id, file_id)
        return await self._operations.complete_file(ledger, file)

    async def verify(self, session_id: UUID) -> SessionLedger:
        """Authorize and execute verify.

        Args:
            session_id: The upload identifier.

        Returns:
            The verified operation result.
        """
        ledger = await self._owned(session_id)
        return await self._operations.verify(ledger)

    async def commit(
        self,
        session_id: UUID,
        *,
        expected_etag: int,
        manifest_sha256: str,
        metadata: Mapping[str, object],
        claim: IdempotencyClaim,
    ) -> RevisionRecord:
        """Authorize and execute commit.

        A claim belonging to another actor raises ``Forbidden``.

        Args:
            session_id: The upload identifier.
            expected_etag: Last observed session version.
            manifest_sha256: Declared manifest digest.
            metadata: Required descriptive revision metadata.
            claim: Retry identity and request fingerprint.

        Returns:
            The verified operation result.
        """
        ledger = await self._owned(session_id)
        committed_by = self._access.actor.subject
        self._access.require_claim(claim)
        return await self._operations.commit(
            ledger,
            expected_etag=expected_etag,
            manifest_sha256=manifest_sha256,
            metadata=MetadataSubmission.model_validate(metadata).model_dump(exclude_none=True),
            committed_by=committed_by,
            claim=claim,
        )

    async def create_in_project(
        self,
        project_id: UUID,
        *,
        slug: str,
        title: str,
        description: str,
        profile_name: str,
        profile_version: str,
        files: Sequence[ManifestEntry],
        idempotency_key: str,
    ) -> SessionLedger:
        """Create a Raw dataset and open its first upload as a recoverable operation.

        Args:
            project_id: The authoritative project identifier.
            slug: The new dataset's stable slug.
            title: Its descriptive title.
            description: Its description.
            profile_name: The science profile name.
            profile_version: The science profile version.
            files: The complete first revision's manifest entries.
            idempotency_key: The identity shared by retries of this intake.

        Returns:
            The new or resumed upload ledger.
        """
        ensure_layer_writable(Layer.RAW, self._access.actor.kind)
        await self._access.require("data.write", ScopeType.PROJECT, project_id, layer="raw")
        manifest = validate_manifest(files)
        actor = self._access.actor.subject
        dataset = await self._catalog.create_dataset(
            project_id,
            slug=slug,
            title=title,
            description=description,
            profile_name=profile_name,
            profile_version=profile_version,
            entry_layer="raw",
            claim=IdempotencyClaim(
                principal=actor,
                key=f"{idempotency_key}/dataset",
                request_sha256=request_sha256(
                    "intake",
                    str(project_id),
                    slug,
                    title,
                    description,
                    profile_name,
                    profile_version,
                    manifest.sha256,
                ),
            ),
        )
        return await self.create(
            dataset.id,
            files=files,
            claim=session_claim(actor, idempotency_key, dataset.id, tuple(files)),
        )

    async def ledger(self, session_id: UUID) -> SessionLedger:
        """Read a session as its owner or an authorized project administrator.

        Args:
            session_id: The upload identifier.

        Returns:
            The current ledger after discovery and administration checks.
        """
        ledger = await self._operations.ledger(session_id)
        await self._access.scope(ScopeType.DATASET, ledger.dataset_id)
        if ledger.created_by != self._access.actor.subject:
            await self._access.require("project.update", ScopeType.DATASET, ledger.dataset_id)
        return ledger
