"""Framework-free catalog rules and public values.

The catalog package holds the manifest, the raw ingest mechanics, the
Raw/Bronze/Silver/Gold layer workflow and the storage layout, all as pure
functions and immutable values with no framework or I/O import. Every
outside capability it needs is a :class:`typing.Protocol` in :mod:`.ports`,
implemented structurally by another package and injected by a service.

This module re-exports the surface most callers need: the manifest
(:class:`Manifest`, :class:`ManifestEntry`, :func:`validate_manifest`,
:func:`canonical_bytes`, :func:`content_identity`), the ingest session
(:class:`IngestSession`, :class:`IngestLease`, :class:`IngestState`,
:func:`compute_upload_plan`), metadata amendments (:class:`Amendment`,
:func:`validate_amendment`, :func:`fold_amendments`), identifiers
(:func:`uuid7`, :func:`id_for_path`), the shared record values
(:class:`EntityRef`, :class:`RevisionRef`, :class:`RevisionRecord`,
:class:`OutboxEvent`) and the two errors every adapter handles
(:class:`DomainError`, :class:`PathRuleViolation`). The layer workflow
(:mod:`.layers`), the storage layout (:mod:`.paths`), the lifecycle
vocabulary (:mod:`.lifecycle`), the full error table (:mod:`.errors`) and
the ports (:mod:`.ports`) are imported by module.
"""

from .amendments import Amendment, fold_amendments, validate_amendment
from .errors import DomainError, PathRuleViolation
from .ids import id_for_path, uuid7
from .ingest import IngestLease, IngestSession, IngestState, compute_upload_plan
from .manifest import Manifest, ManifestEntry, canonical_bytes, content_identity, validate_manifest
from .models import EntityRef, OutboxEvent, RevisionRecord, RevisionRef

__all__ = [
    "Amendment",
    "DomainError",
    "EntityRef",
    "IngestLease",
    "IngestSession",
    "IngestState",
    "Manifest",
    "ManifestEntry",
    "OutboxEvent",
    "PathRuleViolation",
    "RevisionRecord",
    "RevisionRef",
    "canonical_bytes",
    "compute_upload_plan",
    "content_identity",
    "fold_amendments",
    "id_for_path",
    "uuid7",
    "validate_amendment",
    "validate_manifest",
]
