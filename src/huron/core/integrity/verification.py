"""Complete legacy verification from storage observations and trusted catalog identity."""

from __future__ import annotations

import hashlib
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from huron.pkg.catalog.documents import CommitRecord, MetadataDocument, decode_manifest
from huron.pkg.catalog.errors import DomainError
from huron.pkg.catalog.paths import parse_revision_dir

from .models import DocumentObservation, LegacyRevision

if TYPE_CHECKING:
    from huron.pkg.catalog.models import RevisionRecord
    from huron.pkg.catalog.paths import RevisionPath

    from .ports import LegacyStorage


class RevisionVerifier:
    """Verify every document and payload while preserving trustworthy damaged identities."""

    def __init__(self, storage: LegacyStorage, catalog_root: PurePosixPath) -> None:
        """Bind the read-only storage inspection capability.

        Args:
            storage: Storage rooted in the externally fenced deployment.
            catalog_root: Logical storage root recorded by the legacy catalog.
        """
        self._storage = storage
        self._catalog_root = catalog_root

    def verify(
        self, path: str, existing: RevisionRecord | None
    ) -> tuple[LegacyRevision, RevisionRecord]:
        """Inspect an entire legacy revision, refusing ambiguous identity.

        Args:
            path: Exact root-relative revision path.
            existing: Independently trusted database record, when present.

        Returns:
            Complete inventory evidence and the trustworthy record for persistence.

        Raises:
            ValueError: If no trustworthy record exists or immutable identity conflicts.
        """
        identity = parse_revision_dir(PurePosixPath("/"), PurePosixPath("/") / path)
        documents, observations, findings = self._documents(path)
        record_path = str(self._catalog_root / path)
        record = _identity_record(record_path, documents.get("COMMITTED"), existing, findings)
        if (record.id, record.dataset_id, record.number) != (
            identity.revision_id,
            identity.dataset_id,
            identity.revision_number,
        ):
            raise ValueError("legacy revision path and identity disagree")
        expected = _document_inventory(documents, record, identity, findings)
        try:
            findings.update(self._storage.inspect_revision(path, expected))
        except FileNotFoundError:
            findings.add("ENVELOPE_ABSENT")
        except OSError:
            findings.add("ENVELOPE_UNREADABLE")
        return LegacyRevision(
            revision_id=record.id,
            dataset_id=record.dataset_id,
            number=record.number,
            path=path,
            committed=observations["COMMITTED"],
            manifest=observations["manifest.json"],
            metadata=observations["metadata.json"],
            outcome="DEGRADED" if findings else "VERIFIED",
            findings=tuple(sorted(findings)),
            total_bytes=record.total_bytes,
        ), record

    def _documents(
        self, path: str
    ) -> tuple[dict[str, bytes], dict[str, DocumentObservation], set[str]]:
        documents: dict[str, bytes] = {}
        observations: dict[str, DocumentObservation] = {}
        findings: set[str] = set()
        for name in ("COMMITTED", "manifest.json", "metadata.json"):
            try:
                data = self._storage.read_control(path, name)
            except FileNotFoundError:
                observations[name] = DocumentObservation(state="ABSENT")
                findings.add("DOCUMENT_ABSENT")
            except (OSError, ValueError):
                observations[name] = DocumentObservation(state="ERROR")
                findings.add("DOCUMENT_UNREADABLE")
            else:
                documents[name] = data
                observations[name] = DocumentObservation(
                    state="PRESENT", sha256_digest=hashlib.sha256(data).hexdigest()
                )
        return documents, observations, findings


def _identity_record(
    path: str, marker: bytes | None, existing: RevisionRecord | None, findings: set[str]
) -> RevisionRecord:
    if existing is not None and existing.revision_path != path:
        raise ValueError("legacy catalog and storage paths disagree")
    decoded = _legacy_marker(marker, findings)
    if decoded is None:
        if existing is None:
            raise ValueError("legacy revision has no trustworthy commit identity")
        return existing
    record = decoded.revision_record(revision_path=path)
    if existing is not None:
        if (existing.id, existing.dataset_id, existing.number) != (
            record.id,
            record.dataset_id,
            record.number,
        ):
            raise ValueError("legacy marker conflicts with catalog identity")
        if existing != record:
            findings.add("COMMITTED_CATALOG_MISMATCH")
        return existing
    return record


def _legacy_marker(marker: bytes | None, findings: set[str]) -> CommitRecord | None:
    if marker is None:
        return None
    try:
        decoded = CommitRecord.decode(marker)
    except ValueError:
        findings.add("COMMITTED_INVALID")
        return None
    if decoded.protocol != 1:
        raise ValueError("legacy verification refuses a nonlegacy marker")
    return decoded


def _document_inventory(
    documents: dict[str, bytes], record: RevisionRecord, identity: RevisionPath, findings: set[str]
) -> dict[str, tuple[int, str]] | None:
    expected = {
        name: (len(data), hashlib.sha256(data).hexdigest()) for name, data in documents.items()
    }
    try:
        manifest = decode_manifest(documents["manifest.json"])
        metadata = MetadataDocument.decode(documents["metadata.json"])
    except (KeyError, ValueError, DomainError):
        findings.add("DOCUMENT_INVALID")
        return None
    _validate_metadata_identity(metadata, identity, record)
    if (manifest.sha256, metadata.sha256, metadata.manifest_sha256) != (
        record.manifest_sha256,
        record.metadata_sha256,
        record.manifest_sha256,
    ):
        findings.add("DOCUMENT_DIGEST_MISMATCH")
    if (len(manifest.files), manifest.total_bytes) != (record.file_count, record.total_bytes):
        findings.add("MANIFEST_COUNTS_MISMATCH")
    expected.update({entry.path: (entry.size, entry.sha256) for entry in manifest.files})
    return expected


def _validate_metadata_identity(
    metadata: MetadataDocument, identity: RevisionPath, record: RevisionRecord
) -> None:
    document = metadata.as_dict()
    required = {
        "organization": {"id": str(identity.org_id), "slug": identity.org_slug},
        "project": {"id": str(identity.project_id), "slug": identity.project_slug},
        "dataset": {"id": str(identity.dataset_id), "slug": identity.dataset_slug},
        "revision_number": identity.revision_number,
        "committed_by": record.committed_by,
    }
    if any(document[key] != value for key, value in required.items()):
        raise ValueError("legacy metadata and revision identity disagree")
    if metadata.committed_at != record.committed_at:
        raise ValueError("legacy commit instants disagree")
