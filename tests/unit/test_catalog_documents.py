"""The four documents a commit publishes: their canonical form and the value objects over them.

Every assertion here is about identity and agreement: a document's bytes
hash to what its own fields say they should, decoding refuses anything
that is not that exact canonical form, and the objects that reconstruct a
revision from storage alone trust nothing that does not agree with itself
and with the session that wrote it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from typing import Any
from unicodedata import normalize
from uuid import uuid4

import pytest

from huron.core.raw.documents import (
    INDEX_SCHEMA,
    METADATA_SCHEMA,
    CommitIntent,
    CommitRecord,
    MetadataDocument,
    RevisionIndex,
    decode_manifest,
    manifest_bytes,
    revision_from_storage,
)
from huron.core.catalog.errors import ContractMismatch
from huron.core.foundation.errors import PathRuleViolation, PreconditionFailed
from huron.core.raw.ingest import IngestLease, IngestSession, IngestState
from huron.core.raw.manifest import Manifest, ManifestEntry, validate_manifest
from huron.core.foundation.canonical import canonical_bytes
from huron.core.catalog.types import EntityRef
from huron.core.raw.types import RevisionRecord
from huron.core.metastore import InMemoryHierarchyStore

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 30, 19, 2, 41, tzinfo=UTC)
ORG = EntityRef(id=uuid4(), slug="acme")
PROJECT = EntityRef(id=uuid4(), slug="neutron-study")
DATASET = EntityRef(id=uuid4(), slug="run-0042")
NFC = normalize("NFC", "payload/é/café.txt")
DEEP = "payload/" + "/".join(f"d{i}" for i in range(1, 9)) + "/leaf.bin"


def _entry(
    path: str = "payload/a.bin",
    *,
    size: int = 10,
    sha256: str = "a" * 64,
    media_type: str = "application/octet-stream",
) -> ManifestEntry:
    """Build a manifest entry, defaulting to a small octet-stream file."""
    return ManifestEntry(path=path, size=size, sha256=sha256, media_type=media_type)


def _manifest(*entries: ManifestEntry) -> Manifest:
    """Build a validated manifest from the given entries, or one default entry."""
    return validate_manifest(entries or (_entry(),))


def _record(**overrides: Any) -> RevisionRecord:
    """Build a plausible revision record, with any overrides merged in."""
    fields: dict[str, Any] = {
        "id": uuid4(),
        "dataset_id": DATASET.id,
        "number": 1,
        "manifest_sha256": "a" * 64,
        "metadata_sha256": "b" * 64,
        "revision_path": f"organization/acme--{ORG.id.hex}/dataset/run--{DATASET.id.hex}"
        f"/raw/revision/000001--{uuid4().hex}",
        "committed_by": "user:karl",
        "committed_at": NOW,
        "file_count": 1,
        "total_bytes": 10,
    }
    fields.update(overrides)
    return RevisionRecord(**fields)


def _submission(**overrides: Any) -> dict[str, Any]:
    """Build a minimal, valid metadata submission, with any overrides merged in."""
    submission: dict[str, Any] = {"title": "Run 42", "creators": ["user:karl"]}
    submission.update(overrides)
    return submission


def _compose(submission: dict[str, Any] | None = None, **overrides: Any) -> MetadataDocument:
    """Compose a metadata document with sensible defaults, any of them overridable."""
    manifest = overrides.pop("manifest", None) or _manifest()
    kwargs: dict[str, Any] = {
        "organization": ORG,
        "project": PROJECT,
        "dataset": DATASET,
        "revision_number": 1,
        "committed_by": "user:karl",
        "committed_at": NOW,
        "data_classification": "restricted",
    }
    kwargs.update(overrides)
    return MetadataDocument.compose(
        _submission() if submission is None else submission, manifest=manifest, **kwargs
    )


def test_manifest_bytes_are_canonical_and_hash_to_the_manifest_identity() -> None:
    """manifest_bytes renders exactly the manifest's canonical form, hashing to its identity."""
    manifest = _manifest(_entry(path=NFC))
    rendered = manifest_bytes(manifest)
    assert rendered == canonical_bytes(manifest.as_dict())
    assert hashlib.sha256(rendered).hexdigest() == manifest.sha256
    assert "é".encode() in rendered


def test_decode_manifest_round_trips_nfc_zero_byte_and_deep_paths_with_the_same_identity() -> None:
    """decode_manifest rebuilds a manifest with the same entries and identity it was given."""
    manifest = _manifest(
        _entry(path=NFC),
        _entry(path="payload/empty.bin", size=0, sha256=hashlib.sha256(b"").hexdigest()),
        _entry(path=DEEP),
    )
    decoded = decode_manifest(manifest_bytes(manifest))
    assert decoded == manifest
    assert decoded.sha256 == manifest.sha256
    assert decoded.files == manifest.files


def test_decode_manifest_refuses_an_nfd_path_a_pretty_printed_document_and_a_foreign_schema() -> (
    None
):
    """decode_manifest refuses an NFD path, non-canonical bytes and an unrecognised schema."""
    nfd_document = {
        "schema": "urn:huron:manifest:1",
        "hash_algorithm": "sha256",
        "files": [
            {
                "path": normalize("NFD", "payload/café.txt"),
                "size": 5,
                "sha256": "a" * 64,
                "media_type": "application/octet-stream",
            }
        ],
    }
    with pytest.raises(PathRuleViolation):
        decode_manifest(canonical_bytes(nfd_document))

    pretty = json.dumps(_manifest().as_dict(), indent=2).encode()
    with pytest.raises(ValueError, match="canonical"):
        decode_manifest(pretty)

    foreign = {**_manifest().as_dict(), "schema": "x"}
    with pytest.raises(ValueError):
        decode_manifest(canonical_bytes(foreign))


def test_metadata_compose_places_every_server_member_and_keeps_the_submission_s() -> None:
    """Compose places every server-sourced member and keeps the submission's own, verbatim."""
    manifest = _manifest()
    doc = _compose(
        _submission(tags=["alpha", "beta"], extensions={"x": 1}),
        manifest=manifest,
        revision_number=3,
    )
    rendered = doc.as_dict()
    assert rendered["schema"] == METADATA_SCHEMA
    assert rendered["organization"] == {"id": str(ORG.id), "slug": ORG.slug}
    assert rendered["project"] == {"id": str(PROJECT.id), "slug": PROJECT.slug}
    assert rendered["dataset"] == {"id": str(DATASET.id), "slug": DATASET.slug}
    assert rendered["revision_number"] == 3
    assert rendered["title"] == "Run 42"
    assert rendered["creators"] == ["user:karl"]
    assert rendered["committed_by"] == "user:karl"
    assert rendered["committed_at"] == "2026-08-30T19:02:41Z"
    assert rendered["data_classification"] == "restricted"
    assert rendered["manifest_sha256"] == manifest.sha256
    assert rendered["tags"] == ["alpha", "beta"]
    assert rendered["extensions"] == {"x": 1}
    for optional in ("description", "source", "coverage"):
        assert optional not in rendered


def test_metadata_compose_refuses_a_submission_naming_a_server_member_or_a_naive_instant() -> None:
    """Compose refuses a submission naming a server member, and an instant with no timezone."""
    with pytest.raises(ValueError, match="server-owned"):
        _compose(_submission(committed_by="someone-else"))
    with pytest.raises(ValueError, match="timezone-aware"):
        _compose(committed_at=datetime(2026, 8, 30, 19, 2, 41))


@pytest.mark.parametrize(
    ("submission_overrides", "compose_overrides", "expected_path"),
    [
        ({"title": ""}, {}, "$.title"),
        ({"creators": []}, {}, "$.creators"),
        ({"tags": ["dup", "dup"]}, {}, "$.tags"),
        ({}, {"data_classification": ""}, "$.data_classification"),
        ({"unknown_field": True}, {}, "$"),
    ],
)
def test_metadata_compose_refuses_schema_violations_as_contract_mismatch_naming_the_path(
    submission_overrides: dict[str, Any], compose_overrides: dict[str, Any], expected_path: str
) -> None:
    """Compose reports a schema violation as ContractMismatch, naming the violating path."""
    with pytest.raises(ContractMismatch) as excinfo:
        _compose(_submission(**submission_overrides), **compose_overrides)
    assert excinfo.value.context["path"] == expected_path


def test_metadata_document_round_trips_and_renders_the_instant_with_a_z_suffix() -> None:
    """A composed document round-trips through decode and renders its instant with a Z suffix."""
    doc = _compose()
    decoded = MetadataDocument.decode(doc.canonical)
    assert decoded.sha256 == doc.sha256
    rendered = doc.canonical.decode()
    assert "Z" in rendered
    assert "+00:00" not in rendered
    assert decoded.committed_at == doc.committed_at
    assert decoded.committed_at.tzinfo is not None


def test_metadata_decode_refuses_non_canonical_or_non_conforming_bytes() -> None:
    """Decode refuses pretty-printed bytes and a document missing a required member."""
    doc = _compose()
    pretty = json.dumps(doc.as_dict(), indent=2).encode()
    with pytest.raises(ValueError):
        MetadataDocument.decode(pretty)

    incomplete = doc.as_dict()
    del incomplete["title"]
    with pytest.raises(ValueError):
        MetadataDocument.decode(canonical_bytes(incomplete))

    with pytest.raises(ValueError):
        MetadataDocument.decode(b"[]")


def test_commit_record_carries_every_record_field_but_the_path_and_rebuilds_the_record() -> None:
    """CommitRecord carries every field but the path, and rebuilds an identical record from it."""
    record = _record()
    marker = CommitRecord.of(record)
    assert set(marker.as_dict()) == {
        "schema",
        "revision_id",
        "dataset_id",
        "revision_number",
        "manifest_sha256",
        "metadata_sha256",
        "file_count",
        "total_bytes",
        "committed_by",
        "committed_at",
    }
    rebuilt = CommitRecord.decode(marker.canonical).revision_record(
        revision_path=record.revision_path
    )
    assert rebuilt == record


def test_commit_record_decode_refuses_an_extra_member_a_missing_member_and_pretty_bytes() -> None:
    """Decode refuses an unknown member, a missing member and non-canonical bytes."""
    document = CommitRecord.of(_record()).as_dict()

    with pytest.raises(ValueError):
        CommitRecord.decode(canonical_bytes({**document, "extra": "nope"}))

    missing = dict(document)
    del missing["file_count"]
    with pytest.raises(ValueError):
        CommitRecord.decode(canonical_bytes(missing))

    with pytest.raises(ValueError):
        CommitRecord.decode(json.dumps(document, indent=2).encode())


@pytest.mark.parametrize("protocol", [1, 2])
def test_commit_marker_decoding_preserves_its_explicit_protocol(protocol: int) -> None:
    """Decoding keeps a marker's explicit v1 or v2 protocol; newly composed markers use v2."""
    marker = CommitRecord.of(_record())
    assert marker.protocol == 2
    versioned = replace(marker, protocol=protocol)
    assert CommitRecord.decode(versioned.canonical) == versioned


def test_commit_marker_decoding_refuses_an_unknown_protocol() -> None:
    """An unknown schema is not silently interpreted as a legacy or verified marker."""
    marker = replace(CommitRecord.of(_record()), protocol=3)
    with pytest.raises(ValueError, match="unsupported"):
        CommitRecord.decode(marker.canonical)


@pytest.fixture
def commit_intent() -> CommitIntent:
    """A canonical command and consistent immutable publication document set."""
    manifest = _manifest()
    metadata = _compose(manifest=manifest)
    marker = CommitRecord.of(
        _record(manifest_sha256=manifest.sha256, metadata_sha256=metadata.sha256)
    )
    return CommitIntent(
        canonical_bytes(_submission()),
        manifest_bytes(manifest),
        metadata.canonical,
        marker.canonical,
    )


def test_commit_intent_retains_immutable_bytes_and_returns_an_independent_document_map(
    commit_intent: CommitIntent,
) -> None:
    """Callers cannot mutate frozen evidence through either fields or the returned mapping."""
    assert commit_intent.documents == {
        "manifest.json": commit_intent.manifest,
        "metadata.json": commit_intent.metadata,
        "COMMITTED": commit_intent.committed,
    }
    with pytest.raises(FrozenInstanceError):
        commit_intent.command = b"{}"
    documents = commit_intent.documents
    documents.clear()
    assert len(commit_intent.documents) == 3
    commit_intent.require_same_command(replace(commit_intent))


@pytest.mark.parametrize("field", ["command", "manifest", "metadata", "committed"])
@pytest.mark.parametrize("payload", [b"", b"[]", b"{}\n"])
def test_commit_intent_refuses_invalid_or_noncanonical_evidence(
    commit_intent: CommitIntent, field: str, payload: bytes
) -> None:
    """Every evidence member must be a canonical JSON object conforming to its contract."""
    with pytest.raises(ValueError):
        replace(commit_intent, **{field: payload})


@pytest.mark.parametrize(
    "field, value",
    [
        ("protocol", 1),
        ("manifest_sha256", "0" * 64),
        ("metadata_sha256", "0" * 64),
        ("file_count", 2),
        ("total_bytes", 11),
        ("committed_at", NOW + timedelta(seconds=1)),
        ("committed_by", "user:other"),
    ],
)
def test_commit_intent_refuses_disagreement_between_valid_documents(
    commit_intent: CommitIntent, field: str, value: int | str | datetime
) -> None:
    """Individually valid markers cannot disagree with the frozen manifest or metadata."""
    marker = replace(CommitRecord.decode(commit_intent.committed), **{field: value})
    with pytest.raises(ValueError, match="documents disagree"):
        replace(commit_intent, committed=marker.canonical)


def test_commit_intent_refuses_a_different_retry_command(commit_intent: CommitIntent) -> None:
    """A distinct canonical client command conflicts without changing frozen evidence."""
    metadata = MetadataDocument.decode(commit_intent.metadata).as_dict()
    metadata["title"] = "Different"
    encoded = canonical_bytes(metadata)
    marker = replace(
        CommitRecord.decode(commit_intent.committed),
        metadata_sha256=hashlib.sha256(encoded).hexdigest(),
    )
    changed = replace(
        commit_intent,
        command=canonical_bytes(_submission(title="Different")),
        metadata=encoded,
        committed=marker.canonical,
    )
    with pytest.raises(ContractMismatch):
        commit_intent.require_same_command(changed)


def test_revision_from_storage_rebuilds_only_when_marker_metadata_and_session_agree() -> None:
    """revision_from_storage rebuilds the record only when everything it reads agrees."""
    manifest = _manifest()
    lease = IngestLease(
        ingest_id=uuid4(),
        dataset_id=DATASET.id,
        revision_id=uuid4(),
        revision_number=2,
        expires_at=NOW,
    )
    session = IngestSession(
        lease=lease,
        state=IngestState.COMMITTING,
        manifest_sha256=manifest.sha256,
        created_by="user:karl",
    )
    record = _record(
        id=lease.revision_id,
        dataset_id=lease.dataset_id,
        number=lease.revision_number,
        manifest_sha256=manifest.sha256,
        committed_by="user:karl",
        committed_at=NOW,
    )
    doc = _compose(
        manifest=manifest,
        revision_number=record.number,
        committed_by=record.committed_by,
        committed_at=record.committed_at,
    )
    record = replace(record, metadata_sha256=doc.sha256)
    marker = CommitRecord.of(record)

    rebuilt = revision_from_storage(
        marker.canonical, doc.canonical, session=session, revision_path=record.revision_path
    )
    assert rebuilt == record

    disagreements = (
        replace(marker, metadata_sha256="0" * 64),
        replace(marker, manifest_sha256="0" * 64),
        replace(marker, revision_id=uuid4()),
        replace(marker, revision_number=record.number + 1),
        replace(marker, committed_by="someone-else"),
        replace(marker, committed_at=NOW + timedelta(seconds=1)),
    )
    for tampered in disagreements:
        with pytest.raises(ValueError):
            revision_from_storage(
                tampered.canonical,
                doc.canonical,
                session=session,
                revision_path=record.revision_path,
            )


def test_revision_index_includes_replaces_sorts_and_refuses_another_dataset() -> None:
    """Including replaces an existing number, keeps entries sorted, and refuses a foreign entry."""
    dataset_id = DATASET.id
    first = _record(dataset_id=dataset_id, number=1)
    replacement = _record(dataset_id=dataset_id, number=1)
    third = _record(dataset_id=dataset_id, number=3)

    index = RevisionIndex.empty(dataset_id).including(first).including(third).including(replacement)

    assert [entry.number for entry in index.entries] == [1, 3]
    assert index.entries[0].revision_id == replacement.id

    with pytest.raises(ValueError):
        RevisionIndex.empty(dataset_id).including(_record(dataset_id=uuid4(), number=5))


def test_revision_index_round_trips_and_the_same_set_gives_identical_bytes() -> None:
    """Decode round-trips an index, and the same set of revisions gives identical bytes."""
    dataset_id = DATASET.id
    first = _record(dataset_id=dataset_id, number=1)
    second = _record(dataset_id=dataset_id, number=2)

    built_forward = RevisionIndex.empty(dataset_id).including(first).including(second)
    built_backward = RevisionIndex.empty(dataset_id).including(second).including(first)
    assert built_forward.canonical == built_backward.canonical

    decoded = RevisionIndex.decode(built_forward.canonical)
    assert decoded == built_forward

    revisions = built_forward.as_dict()["revisions"]
    unsorted = {"schema": INDEX_SCHEMA, "dataset_id": str(dataset_id), "revisions": revisions[::-1]}
    with pytest.raises(ValueError):
        RevisionIndex.decode(canonical_bytes(unsorted))

    duplicated = {
        "schema": INDEX_SCHEMA,
        "dataset_id": str(dataset_id),
        "revisions": [revisions[0], revisions[0]],
    }
    with pytest.raises(ValueError):
        RevisionIndex.decode(canonical_bytes(duplicated))

    schemaless = {"schema": INDEX_SCHEMA, "dataset_id": str(dataset_id)}
    with pytest.raises(ValueError):
        RevisionIndex.decode(canonical_bytes(schemaless))


@pytest.mark.parametrize("field", ["dataset_id", "revision_number"])
def test_commit_intent_rejects_metadata_identity_disagreement(
    commit_intent: CommitIntent, field: str
) -> None:
    """A marker cannot change the dataset or revision number declared in metadata."""
    marker = CommitRecord.decode(commit_intent.committed)
    changed = replace(
        marker, **{field: uuid4() if field == "dataset_id" else marker.revision_number + 1}
    )
    with pytest.raises(ValueError, match="documents disagree"):
        replace(commit_intent, committed=changed.canonical)


def test_commit_intent_rejects_a_command_that_does_not_describe_its_metadata(
    commit_intent: CommitIntent,
) -> None:
    """Frozen metadata must preserve exactly the validated submitted command."""
    with pytest.raises(ValueError, match="documents disagree"):
        replace(commit_intent, command=canonical_bytes(_submission(title="Different")))


def test_commit_intent_is_bound_to_its_reserved_session(commit_intent: CommitIntent) -> None:
    """Revision, dataset, number, manifest and actor must all match the reservation."""
    marker = CommitRecord.decode(commit_intent.committed)
    lease = IngestLease(uuid4(), marker.dataset_id, marker.revision_id, marker.revision_number, NOW)
    session = IngestSession(
        lease, IngestState.COMMITTING, marker.manifest_sha256, marker.committed_by
    )
    commit_intent.require_session(session)
    for changed_lease in (
        replace(lease, revision_id=uuid4()),
        replace(lease, dataset_id=uuid4()),
        replace(lease, revision_number=lease.revision_number + 1),
    ):
        with pytest.raises(ValueError, match="does not belong"):
            commit_intent.require_session(replace(session, lease=changed_lease))
    for changed in (
        replace(session, manifest_sha256="0" * 64),
        replace(session, created_by="other"),
    ):
        with pytest.raises(ValueError, match="does not belong"):
            commit_intent.require_session(changed)


async def test_freezing_an_unknown_session_does_not_create_a_publication(
    commit_intent: CommitIntent,
) -> None:
    """Frozen evidence cannot manufacture a session that was never reserved."""
    marker = CommitRecord.decode(commit_intent.committed)
    lease = IngestLease(uuid4(), marker.dataset_id, marker.revision_id, marker.revision_number, NOW)
    session = IngestSession(
        lease, IngestState.COMMITTING, marker.manifest_sha256, marker.committed_by
    )
    store = InMemoryHierarchyStore()
    with pytest.raises(PreconditionFailed):
        async with store.transaction() as writer:
            await writer.freeze_commit(session, commit_intent, expected_etag=session.etag)
