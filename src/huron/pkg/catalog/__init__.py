"""Framework-free catalog rules and public values.

The catalog package holds the manifest, the raw ingest mechanics, the
Raw/Bronze/Silver/Gold layer workflow and the storage layout, all as pure
functions and immutable values with no framework or I/O import. Every
outside capability it needs is a :class:`typing.Protocol` in :mod:`.ports`,
implemented structurally by another package and injected by a service.

This module re-exports the surface most callers need: the manifest
(:class:`Manifest`, :class:`ManifestEntry`, :func:`validate_manifest`,
:func:`canonical_bytes`, :func:`content_identity`), the ingest session and
per-file ledger (:class:`IngestSession`, :class:`IngestLease`,
:class:`IngestState`, :class:`FileState`, :class:`IngestFile`,
:class:`UploadAction`, :class:`UploadPlanEntry`, :data:`TRANSITIONS`,
:func:`compute_upload_plan`, :func:`revision_record`,
:func:`revision_committed`, :data:`LEASE_TTL`, :data:`PART_BYTES`),
metadata amendments (:class:`Amendment`, :func:`validate_amendment`,
:func:`fold_amendments`), identifiers (:func:`uuid7`, :func:`id_for_path`),
the shared record values (:class:`EntityRef`, :class:`RevisionRef`,
:class:`RevisionRecord`, :class:`OutboxEvent`), the four documents a commit
publishes (:func:`manifest_bytes`, :func:`decode_manifest`,
:class:`MetadataDocument`, :class:`CommitRecord`, :class:`IndexEntry`,
:class:`RevisionIndex`, :func:`revision_from_storage`) and the two errors
every adapter handles (:class:`DomainError`, :class:`PathRuleViolation`).
The layer workflow (:mod:`.layers`), the storage layout (:mod:`.paths`),
the lifecycle vocabulary (:mod:`.lifecycle`), the full error table
(:mod:`.errors`) and the ports (:mod:`.ports`) are imported by module.
"""

from .amendments import Amendment, fold_amendments, validate_amendment
from .documents import (
    CommitRecord,
    IndexEntry,
    MetadataDocument,
    RevisionIndex,
    decode_manifest,
    manifest_bytes,
    revision_from_storage,
)
from .errors import DomainError, PathRuleViolation
from .ids import id_for_path, uuid7
from .ingest import (
    LEASE_TTL,
    PART_BYTES,
    TRANSITIONS,
    FileState,
    IngestFile,
    IngestLease,
    IngestSession,
    IngestState,
    UploadAction,
    UploadPlanEntry,
    compute_upload_plan,
    revision_committed,
    revision_record,
)
from .manifest import Manifest, ManifestEntry, canonical_bytes, content_identity, validate_manifest
from .models import EntityRef, OutboxEvent, RevisionRecord, RevisionRef

__all__ = [
    "LEASE_TTL",
    "PART_BYTES",
    "TRANSITIONS",
    "Amendment",
    "CommitRecord",
    "DomainError",
    "EntityRef",
    "FileState",
    "IndexEntry",
    "IngestFile",
    "IngestLease",
    "IngestSession",
    "IngestState",
    "Manifest",
    "ManifestEntry",
    "MetadataDocument",
    "OutboxEvent",
    "PathRuleViolation",
    "RevisionIndex",
    "RevisionRecord",
    "RevisionRef",
    "UploadAction",
    "UploadPlanEntry",
    "canonical_bytes",
    "compute_upload_plan",
    "content_identity",
    "decode_manifest",
    "fold_amendments",
    "id_for_path",
    "manifest_bytes",
    "revision_committed",
    "revision_from_storage",
    "revision_record",
    "uuid7",
    "validate_amendment",
    "validate_manifest",
]
