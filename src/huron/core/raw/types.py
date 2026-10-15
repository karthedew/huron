"""Raw revision, ledger and download values shared with adapters.

These are the record shapes Raw's ports exchange with the services
that implement them: enough identity to build a storage path, enough about
a committed revision to record it, and the event that announces it. They
carry no behaviour and no framework import, so both sides of a port can use
them without either importing the other.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import os
    from datetime import datetime
    from pathlib import Path
    from uuid import UUID

    from .ingest import IngestFile, IngestSession, IngestState
    from .manifest import ManifestEntry


@dataclass(frozen=True, slots=True)
class RevisionRecord:
    """A committed raw revision as the catalog records it.

    Built once the envelope is published and never updated: a revision is
    immutable, so its record is too.

    Attributes:
        id: The revision's identifier.
        dataset_id: The dataset the revision belongs to.
        number: The revision's 1-based position within its dataset.
        manifest_sha256: The content identity of the committed manifest.
        metadata_sha256: The content identity of the committed
            ``metadata.json`` document.
        revision_path: The revision directory in the raw store, as
            :func:`huron.core.raw.paths.revision_dir` builds it.
        committed_by: The principal whose ingest session committed it.
        committed_at: When the commit became durable.
        file_count: How many files the manifest lists.
        total_bytes: The sum of the manifest's file sizes.
    """

    id: UUID
    dataset_id: UUID
    number: int
    manifest_sha256: str
    metadata_sha256: str
    revision_path: str
    committed_by: str
    committed_at: datetime
    file_count: int
    total_bytes: int


@dataclass(frozen=True, slots=True)
class OutboxEvent:
    """An event stored in the same transaction as the change it announces.

    Writing the event through a transactional outbox, rather than publishing
    it directly, means a consumer can never learn of a revision that was
    not durably recorded, and a recorded revision can never go unannounced.

    Attributes:
        id: The event's identifier, minted at the raise site.
        kind: The event type a consumer dispatches on.
        subject_id: The id of the entity the event is about.
        payload: The event body, as JSON-compatible values.
        created_at: When the event was recorded, alongside the change it
            announces.
    """

    id: UUID
    kind: str
    subject_id: UUID
    payload: dict[str, object]
    created_at: datetime


@dataclass(slots=True)
class AuditEvent:
    """An append-only publication audit record stored with the mutation."""

    id: UUID
    kind: str
    actor: str
    subject_kind: str
    subject_id: UUID | None
    payload: dict[str, object]
    created_at: datetime


@dataclass(slots=True)
class LedgerEntry:
    """A file's current ledger state and its owning upload identity."""

    ingest_id: UUID
    file: IngestFile


@dataclass(frozen=True, slots=True)
class ExpiryReport:
    """One expiry pass; listed always equals expired plus skipped."""

    listed: int
    expired: int
    skipped: int


@dataclass(frozen=True, slots=True)
class PayloadFile:
    """A manifest-listed payload, its resolved location and fresh filesystem metadata."""

    entry: ManifestEntry
    location: Path
    stat: os.stat_result


@dataclass(frozen=True, slots=True)
class SessionLedger:
    """A freshly read session and its complete files in manifest order."""

    session: IngestSession
    files: tuple[IngestFile, ...]

    @property
    def id(self) -> UUID:
        """Return the upload identity."""
        return self.session.lease.ingest_id

    @property
    def dataset_id(self) -> UUID:
        """Return the owning dataset identity."""
        return self.session.lease.dataset_id

    @property
    def revision_id(self) -> UUID:
        """Return the reserved revision identity."""
        return self.session.lease.revision_id

    @property
    def revision_number(self) -> int:
        """Return the reserved revision number."""
        return self.session.lease.revision_number

    @property
    def state(self) -> IngestState:
        """Return the current session state."""
        return self.session.state

    @property
    def etag(self) -> int:
        """Return the current optimistic-concurrency version."""
        return self.session.etag

    @property
    def expires_at(self) -> datetime:
        """Return the current lease deadline."""
        return self.session.lease.expires_at

    @property
    def created_by(self) -> str:
        """Return the authenticated session owner's subject."""
        return self.session.created_by

    @property
    def manifest_sha256(self) -> str:
        """Return the declared complete-manifest identity."""
        return self.session.manifest_sha256

    @property
    def part_bytes(self) -> int:
        """Return the live domain upload-part size."""
        from .ingest import PART_BYTES

        return PART_BYTES
