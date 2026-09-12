"""Legacy verification distinguishes corrupt content from ambiguous publication identity."""

import hashlib
import os
import shutil
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from uuid import UUID

import pytest

from huron.core.catalog_documents import GenerationDocuments
from huron.core.integrity.verification import RevisionVerifier
from huron.pkg.catalog.documents import CommitRecord, MetadataDocument, manifest_bytes
from huron.pkg.catalog.manifest import ManifestEntry, canonical_bytes, validate_manifest
from huron.pkg.catalog.models import EntityRef, RevisionRecord
from huron.pkg.catalog.paths import dataset_dir, organization_dir, project_dir, revision_dir
from huron.pkg.catalog.records import Dataset, Organization, Project
from huron.pkg.rawstore import PosixRawStore
from huron.pkg.rawstore.maintenance import MaintenanceStore

pytestmark = pytest.mark.unit


def legacy_records() -> tuple[Organization, Project, Dataset]:
    """Provide the exact acknowledged parent hierarchy used by the legacy envelope fixture."""
    instant = datetime(2026, 1, 1, tzinfo=UTC)
    organization = Organization(UUID(int=11), "organization", "Organization", "", 1, 1, instant)
    project = Project(
        UUID(int=12), organization.id, "project", "Project", "", "internal", 1, 1, instant
    )
    dataset = Dataset(
        UUID(int=13),
        project.id,
        "dataset",
        "Dataset",
        "",
        "generic",
        "1",
        "raw",
        "ACTIVE",
        1,
        1,
        instant,
    )
    return organization, project, dataset


@pytest.fixture
def legacy(tmp_path: Path) -> tuple[RevisionVerifier, str, RevisionRecord]:
    """Materialize a genuine legacy envelope using the catalog's document contracts."""
    organization = EntityRef(UUID(int=11), "organization")
    project = EntityRef(UUID(int=12), "project")
    dataset = EntityRef(UUID(int=13), "dataset")
    writer = GenerationDocuments(PosixRawStore(tmp_path))
    parents = legacy_records()
    for path, parent in zip(
        (
            organization_dir(PurePosixPath(tmp_path), organization),
            project_dir(PurePosixPath(tmp_path), organization, project),
            dataset_dir(PurePosixPath(tmp_path), organization, project, dataset),
        ),
        parents,
        strict=True,
    ):
        writer.write(path, parent)
    payload = b"measurement"
    manifest = validate_manifest(
        [
            ManifestEntry(
                "payload/file", len(payload), hashlib.sha256(payload).hexdigest(), "text/plain"
            )
        ]
    )
    instant = datetime(2026, 1, 1, tzinfo=UTC)
    metadata = MetadataDocument.compose(
        {"title": "Measurement", "creators": ["scientist"]},
        manifest=manifest,
        organization=organization,
        project=project,
        dataset=dataset,
        revision_number=1,
        committed_by="scientist",
        committed_at=instant,
        data_classification="internal",
    )
    logical = revision_dir(PurePosixPath("/data"), organization, project, dataset, 1, UUID(int=14))
    relative = str(logical.relative_to("/data"))
    record = RevisionRecord(
        UUID(int=14),
        dataset.id,
        1,
        manifest.sha256,
        metadata.sha256,
        str(logical),
        "scientist",
        instant,
        1,
        len(payload),
    )
    marker = replace(CommitRecord.of(record), protocol=1)
    target = tmp_path / relative
    (target / "payload").mkdir(parents=True)
    for name, data in {
        "COMMITTED": marker.canonical,
        "metadata.json": metadata.canonical,
        "manifest.json": manifest_bytes(manifest),
        "payload/file": payload,
    }.items():
        (target / name).write_bytes(data)
        (target / name).chmod(0o444)
    (target / "payload").chmod(0o555)
    target.chmod(0o555)
    return (
        RevisionVerifier(MaintenanceStore(tmp_path, os.geteuid()), PurePosixPath("/data")),
        relative,
        record,
    )


def overwrite(root: Path, relative: str, name: str, data: bytes | None) -> None:
    """Change a fixture before the verifier is called."""
    parent = root / relative
    parent.chmod(0o755)
    path = parent / name
    path.chmod(0o644)
    if data is None:
        path.unlink()
    else:
        path.write_bytes(data)
        path.chmod(0o444)
    parent.chmod(0o555)


def test_complete_legacy_revision_verifies_and_orphan_identity_is_preserved(
    legacy: tuple[RevisionVerifier, str, RevisionRecord],
) -> None:
    """A complete v1 envelope yields the same exact record with or without a database row."""
    verifier, path, record = legacy
    entry, recovered = verifier.verify(path, None)
    assert entry.outcome == "VERIFIED"
    assert entry.findings == ()
    assert recovered == record
    assert verifier.verify(path, record) == (entry, recovered)


@pytest.mark.parametrize("name", ["COMMITTED", "manifest.json", "metadata.json"])
def test_corrupt_or_absent_documents_remain_explicitly_degraded(
    tmp_path: Path, legacy: tuple[RevisionVerifier, str, RevisionRecord], name: str
) -> None:
    """Trusted catalog identity survives corruption without fabricated document digests."""
    verifier, path, record = legacy
    overwrite(tmp_path, path, name, b"corrupt")
    entry, _ = verifier.verify(path, record)
    assert entry.outcome == "DEGRADED"
    overwrite(tmp_path, path, name, None)
    entry, _ = verifier.verify(path, record)
    assert "DOCUMENT_ABSENT" in entry.findings
    evidence = {
        "COMMITTED": entry.committed,
        "manifest.json": entry.manifest,
        "metadata.json": entry.metadata,
    }[name]
    assert evidence.state == "ABSENT"
    assert evidence.sha256_digest is None


def test_orphan_without_a_trustworthy_marker_blocks_inventory(
    tmp_path: Path, legacy: tuple[RevisionVerifier, str, RevisionRecord]
) -> None:
    """No commit identity or audit provenance is invented from a directory name."""
    verifier, path, _ = legacy
    overwrite(tmp_path, path, "COMMITTED", b"broken")
    with pytest.raises(ValueError, match="no trustworthy commit identity"):
        verifier.verify(path, None)


def test_nonlegacy_markers_and_conflicting_records_are_refused(
    tmp_path: Path, legacy: tuple[RevisionVerifier, str, RevisionRecord]
) -> None:
    """A new marker or conflicting catalog identity cannot be imported as legacy."""
    verifier, path, record = legacy
    with pytest.raises(ValueError, match="catalog and storage paths"):
        verifier.verify(path, replace(record, revision_path="/elsewhere"))
    with pytest.raises(ValueError, match="conflicts with catalog"):
        verifier.verify(path, replace(record, id=UUID(int=100)))
    overwrite(tmp_path, path, "COMMITTED", CommitRecord.of(record).canonical)
    with pytest.raises(ValueError, match="nonlegacy"):
        verifier.verify(path, None)


def test_metadata_ancestry_and_commit_instants_must_match(
    tmp_path: Path, legacy: tuple[RevisionVerifier, str, RevisionRecord]
) -> None:
    """Canonical metadata with a different ancestry or instant is an identity conflict."""
    verifier, path, record = legacy
    metadata = MetadataDocument.decode((tmp_path / path / "metadata.json").read_bytes()).as_dict()
    metadata["revision_number"] = 2
    overwrite(tmp_path, path, "metadata.json", canonical_bytes(metadata))
    with pytest.raises(ValueError, match="metadata and revision identity"):
        verifier.verify(path, record)
    metadata["revision_number"] = 1
    metadata["committed_at"] = (record.committed_at + timedelta(seconds=1)).isoformat()
    overwrite(tmp_path, path, "metadata.json", canonical_bytes(metadata))
    with pytest.raises(ValueError, match="commit instants"):
        verifier.verify(path, record)


def test_document_digest_and_manifest_count_disagreements_are_degraded(
    tmp_path: Path, legacy: tuple[RevisionVerifier, str, RevisionRecord]
) -> None:
    """Canonical yet altered content is retained as damaged evidence."""
    verifier, path, record = legacy
    marker = replace(CommitRecord.of(record), protocol=1, total_bytes=99, metadata_sha256="a" * 64)
    overwrite(tmp_path, path, "COMMITTED", marker.canonical)
    entry, _ = verifier.verify(path, None)
    assert "DOCUMENT_DIGEST_MISMATCH" in entry.findings
    assert "MANIFEST_COUNTS_MISMATCH" in entry.findings


def test_wrong_marker_identity_blocks_even_without_database_row(
    tmp_path: Path, legacy: tuple[RevisionVerifier, str, RevisionRecord]
) -> None:
    """A well-formed marker cannot claim a different path identity."""
    verifier, path, record = legacy
    marker = replace(CommitRecord.of(record), protocol=1, revision_id=UUID(int=100))
    overwrite(tmp_path, path, "COMMITTED", marker.canonical)
    with pytest.raises(ValueError, match="path and identity"):
        verifier.verify(path, None)


def test_missing_envelope_keeps_its_known_catalog_identity(
    tmp_path: Path, legacy: tuple[RevisionVerifier, str, RevisionRecord]
) -> None:
    """An absent whole revision remains degraded inventory rather than disappearing."""
    verifier, path, record = legacy
    target = tmp_path / path
    for entry in (target, target / "payload"):
        entry.chmod(0o755)
    shutil.rmtree(target)
    result, trusted = verifier.verify(path, record)
    assert trusted == record
    assert "ENVELOPE_ABSENT" in result.findings
    assert result.committed.state == "ABSENT"


@pytest.mark.parametrize("kind", ["file", "symlink"])
def test_unsafe_known_envelope_remains_degraded_without_following_it(
    tmp_path: Path,
    legacy: tuple[RevisionVerifier, str, RevisionRecord],
    kind: str,
) -> None:
    """A corrupt final entry retains trusted identity but cannot supply orphan certification."""
    verifier, path, record = legacy
    target = tmp_path / path
    for entry in (target, target / "payload"):
        entry.chmod(0o755)
    shutil.rmtree(target)
    if kind == "file":
        target.write_bytes(b"corrupt envelope")
    else:
        target.symlink_to(tmp_path)
    try:
        store = MaintenanceStore(tmp_path, os.geteuid())
        assert list(store.revision_paths()) == [path]
        result, trusted = verifier.verify(path, record)
        assert trusted == record
        assert result.outcome == "DEGRADED"
        assert result.committed.state == "ERROR"
        assert "ENVELOPE_UNREADABLE" in result.findings
        with pytest.raises(ValueError, match="no trustworthy"):
            verifier.verify(path, None)
    finally:
        target.unlink()


def test_unreadable_marker_and_catalog_content_disagreement_are_explicit_findings(
    tmp_path: Path, legacy: tuple[RevisionVerifier, str, RevisionRecord]
) -> None:
    """An unsafe document name and altered marker accounting do not invent healthy evidence."""
    verifier, path, record = legacy
    result, _ = verifier.verify(path, replace(record, total_bytes=100))
    assert "COMMITTED_CATALOG_MISMATCH" in result.findings
    overwrite(tmp_path, path, "COMMITTED", None)
    target = tmp_path / path
    target.chmod(0o755)
    (target / "COMMITTED").symlink_to(tmp_path)
    target.chmod(0o555)
    result, _ = verifier.verify(path, record)
    assert result.committed.state == "ERROR"
    assert "DOCUMENT_UNREADABLE" in result.findings
    target.chmod(0o755)
    (target / "COMMITTED").unlink()
