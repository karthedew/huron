"""Raw-owned persistence and storage capabilities with atomic publication groups."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from huron.core.catalog.ports import CatalogReaders, CollectionReader
from huron.core.foundation.retry import RetryTransaction

if TYPE_CHECKING:
    import os
    from collections.abc import Iterable, Mapping, Sequence
    from contextlib import AbstractAsyncContextManager
    from datetime import datetime
    from pathlib import Path, PurePosixPath
    from uuid import UUID

    from huron.core.catalog.types import Dataset, Window
    from huron.core.security.rules import Visibility

    from .documents import CommitIntent
    from .ingest import IngestFile, IngestSession
    from .types import AuditEvent, LedgerEntry, OutboxEvent, Release, RevisionRecord, RevisionRef


class ReleaseTransaction(RetryTransaction, Protocol):
    """An immutable tag insert and receipt sharing one transaction."""

    async def insert_release(self, item: Release) -> None:
        """Insert a release with dataset/tag uniqueness and registered target validation.

        Args:
            item: Complete release record.
        """
        ...


class ReleaseStore(CatalogReaders, Protocol):
    """Release lookup and tag publication with committed hierarchy ancestry."""

    def transaction(self) -> AbstractAsyncContextManager[ReleaseTransaction]:
        """Open one atomic tag and retry transaction.

        Returns:
            The writer, committing only on clean exit.
        """
        ...

    async def release(self, dataset_id: UUID, tag: str, visibility: Visibility) -> Release:
        """Resolve a tag after checking its dataset's discoverability.

        Args:
            dataset_id: Owning dataset.
            tag: Immutable tag name.
            visibility: Dataset discovery projection.

        Returns:
            The stored release.
        """
        ...

    async def revision_ref(self, dataset_id: UUID, revision_number: int) -> RevisionRef:
        """Resolve a registered release target without imposing a state or read predicate.

        Args:
            dataset_id: Authorized target dataset.
            revision_number: Registered revision number.

        Returns:
            The target identity and manifest digest.
        """
        ...

    async def releases(
        self, dataset_id: UUID, visibility: Visibility, *, limit: int, after: tuple[str] | None
    ) -> Window[Release]:
        """Page tags in byte order after checking dataset discovery.

        Args:
            dataset_id: Owning dataset.
            visibility: Discovery projection.
            limit: Maximum returned records.
            after: Exclusive tag cursor or None.

        Returns:
            The visible tag window.
        """
        ...


class HierarchyWriter(RetryTransaction, Protocol):
    """Raw reservation, freeze and final-record writes on one transaction connection.

    Reservation groups session/number, files, claim, audit and receipt. Freeze groups
    the first COMMITTING edge, immutable CommitIntent and unfinished receipt. Final
    recording groups the session lock, revision, COMMITTED edge, audit, outbox and
    completed receipt. No write becomes visible before the context commits.
    """

    async def insert_revision(self, record: RevisionRecord) -> None:
        """Record a storage-published revision.

        Args:
            record: Complete immutable revision record.
        """
        ...

    async def insert_audit_event(self, event: AuditEvent) -> None:
        """Append an audit row within the mutation transaction.

        Args:
            event: Complete audit record.
        """
        ...

    async def insert_outbox_event(self, event: OutboxEvent) -> None:
        """Append an unprocessed publication event within the mutation transaction.

        Args:
            event: Complete outbox record.
        """
        ...

    async def lock_ingest_session(self, session_id: UUID) -> IngestSession:
        """Hold the session mutation lock through the enclosing transaction.

        Args:
            session_id: Session to fence.

        Returns:
            Its current locked state.
        """
        ...

    async def freeze_commit(
        self, session: IngestSession, intent: CommitIntent, *, expected_etag: int
    ) -> tuple[IngestSession, CommitIntent]:
        """Freeze immutable evidence atomically with the first COMMITTING transition.

        Args:
            session: Proposed COMMITTING state.
            intent: Proposed canonical command and documents.
            expected_etag: Version observed before the transition.

        Returns:
            The persisted state and evidence shared by concurrent retries.
        """
        ...

    async def begin_ingest(
        self,
        dataset_id: UUID,
        manifest_sha256: str,
        *,
        created_by: str,
        files: Sequence[IngestFile],
    ) -> IngestSession:
        """Reserve PREPARING state, files and the next number under the dataset lock.

        One nonterminal session is permitted. Aborted reservations may reuse their
        uncommitted number; the failed attempt remains recorded.

        Args:
            dataset_id: Owning dataset.
            manifest_sha256: Complete submission identity.
            created_by: Authenticated session owner.
            files: Complete independent upload ledger.

        Returns:
            The reserved session and lease.
        """
        ...

    async def update_ingest_session(self, session: IngestSession, *, expected_etag: int) -> None:
        """Persist a validated state edge only at the expected version.

        Args:
            session: Successor with its advanced etag.
            expected_etag: Required current etag; mismatch raises PreconditionFailed.
        """
        ...

    async def renew_ingest_session(self, session: IngestSession) -> None:
        """Extend a renewable lease monotonically without changing state or etag.

        Args:
            session: Candidate lease deadline; terminal and recovering states refuse renewal.
        """
        ...

    async def expire_ingest_session(
        self, session: IngestSession, *, expected_etag: int, now: datetime
    ) -> None:
        """Fence expiry against version, renewable state and the still-lapsed lease.

        Args:
            session: Proposed ABORTED successor.
            expected_etag: Required current etag.
            now: Sweep instant rechecked against the persisted lease.
        """
        ...

    async def update_ingest_file(
        self, ingest_id: UUID, file: IngestFile, *, expected_parts: frozenset[int]
    ) -> None:
        """Persist a ledger step under the current part-set and writable-session fences.

        Args:
            ingest_id: Owning session.
            file: Validated file successor.
            expected_parts: Required persisted part set on a PENDING file.
        """
        ...


class RevisionStore(Protocol):
    """Registered revision reads and authoritative dataset discovery."""

    @property
    def datasets(self) -> CollectionReader[Dataset, UUID]:
        """Return the dataset-discovery reader used to admit revision reads."""
        ...

    async def revision(self, revision_id: UUID) -> RevisionRecord:
        """Read a registered revision in any state for an authorized operation.

        Args:
            revision_id: Revision identity.

        Returns:
            Its persisted record.
        """
        ...


class HierarchyStore(RevisionStore, CatalogReaders, Protocol):
    """Raw upload persistence; no Catalog creation, description or release writes."""

    def transaction(self) -> AbstractAsyncContextManager[HierarchyWriter]:
        """Open one atomic Raw mutation transaction.

        Returns:
            A writer sharing one connection, rolling back all writes on failure.
        """
        ...

    async def latest_committed_revision(self, dataset_id: UUID) -> RevisionRecord | None:
        """Read the highest-numbered committed revision.

        Args:
            dataset_id: Owning dataset.

        Returns:
            Its latest committed record or None.
        """
        ...

    async def ingest_session(self, session_id: UUID) -> IngestSession:
        """Read a session in its current state.

        Args:
            session_id: Session identity.

        Returns:
            The persisted state or raises ResourceNotFound.
        """
        ...

    async def ingest_files(self, session_id: UUID) -> tuple[IngestFile, ...]:
        """Read the complete ledger in manifest path order.

        Args:
            session_id: Session identity.

        Returns:
            The ordered files, empty for an unknown or empty session.
        """
        ...

    async def ingest_file(self, file_id: UUID) -> LedgerEntry:
        """Read a file and its owning session identity.

        Args:
            file_id: File identity.

        Returns:
            The current ledger entry or raises ResourceNotFound.
        """
        ...

    async def lapsed_ingest_sessions(
        self, now: datetime, *, limit: int
    ) -> tuple[IngestSession, ...]:
        """Read oldest lapsed PREPARING, UPLOADING or VERIFYING sessions only.

        Args:
            now: Sweep instant.
            limit: Maximum returned sessions.

        Returns:
            Renewable lapsed sessions; never COMMITTING sessions.
        """
        ...


class RawStore(Protocol):
    """Cohesive Raw storage capability with independent completion and storage-first publication."""

    @property
    def root(self) -> Path:
        """Return the common staging and publication data root."""
        ...

    def initialize(self) -> None:
        """Create the storage skeleton and verify same-filesystem publication."""
        ...

    def create_staging(self, staging: PurePosixPath) -> None:
        """Exclusively create durable private upload, candidate and envelope directories.

        Args:
            staging: The fresh session root beneath root/.staging.
        """
        ...

    def write_part(
        self,
        staging: PurePosixPath,
        rel_path: str,
        chunks: Iterable[bytes],
        *,
        offset: int,
        length: int,
    ) -> str:
        """Write exactly one range and make its file and ancestors durable before success.

        Args:
            staging: Existing session root.
            rel_path: Upload-relative input name.
            chunks: Bytes consumed once.
            offset: First byte position.
            length: Exact required byte count.

        Returns:
            The streamed bytes' SHA-256; length mismatch raises PartLengthMismatchError.
        """
        ...

    def finish_file(
        self,
        staging: PurePosixPath,
        file_id: str,
        rel_path: str,
        *,
        expected_size: int,
        expected_sha256: str,
    ) -> tuple[int, str]:
        """Install an independently copied and verified payload without replacing a winner.

        Args:
            staging: Existing session root, never recreated.
            file_id: Upload input name.
            rel_path: Manifest payload path.
            expected_size: Declared size.
            expected_sha256: Declared digest.

        Returns:
            Actual observation; mismatch installs nothing and removes only its candidate.
        """
        ...

    def verify_envelope(
        self,
        envelope: PurePosixPath,
        files: Sequence[tuple[str, int, str]],
        documents: Mapping[str, bytes],
        *,
        sealed: bool = False,
    ) -> None:
        """Verify exact inventory, independent inodes and frozen evidence.

        Args:
            envelope: Existing staged or published envelope.
            files: Declared paths, sizes and digests.
            documents: Frozen document bytes.
            sealed: Require sealed descendants while allowing an unfinished root seal.
        """
        ...

    def discard_file(self, staging: PurePosixPath, rel_path: str) -> None:
        """Remove a completed upload input; absence is success.

        Args:
            staging: Existing session root.
            rel_path: Upload-relative input name.
        """
        ...

    def read_document(self, path: PurePosixPath) -> bytes:
        """Read exact stored bytes.

        Args:
            path: Document location.

        Returns:
            Its bytes, or raises FileNotFoundError.
        """
        ...

    def stat_document(self, path: PurePosixPath) -> os.stat_result:
        """Inspect a stored file without reading its payload.

        Args:
            path: File location.

        Returns:
            Fresh filesystem metadata.
        """
        ...

    def write_document(self, staging: PurePosixPath, name: str, payload: bytes) -> None:
        """Install a closed sealed control document; equal bytes replay, different bytes refuse.

        Args:
            staging: Existing envelope directory, never recreated.
            name: Safe nonreserved single component.
            payload: Complete document bytes.
        """
        ...

    def atomic_replace(self, path: PurePosixPath, payload: bytes) -> None:
        """Durably replace a derived pointer or index in one visible step.

        Args:
            path: Destination, created if absent.
            payload: Complete new bytes.
        """
        ...

    def seal(self, revision_dir: PurePosixPath) -> None:
        """Seal descendant files and directories while leaving the root renameable.

        Args:
            revision_dir: Existing envelope directory.
        """
        ...

    def commit_envelope(self, staging: PurePosixPath, final: PurePosixPath) -> None:
        """Flush, atomically rename and seal a completed envelope on one filesystem.

        Args:
            staging: Completed envelope with COMMITTED marker.
            final: Revision destination; retries require validated frozen evidence.
        """
        ...

    def write_tag_once(self, tag_file: PurePosixPath, payload: bytes) -> None:
        """Exclusively create a durable tag without replacing existing content.

        Args:
            tag_file: Dataset-level tag path.
            payload: Complete canonical tag bytes.
        """
        ...
