"""Cutover evidence binds exact canonical observations rather than historic times."""

from datetime import UTC, datetime
from pathlib import PurePosixPath
from uuid import UUID

import pytest
from jsonschema import ValidationError

from huron.core.integrity.models import (
    DocumentObservation,
    FenceEvidence,
    GenerationObservation,
    LegacyRevision,
    ProtocolInventory,
    ProtocolTransition,
)
from huron.pkg.catalog.models import EntityRef
from huron.pkg.catalog.paths import revision_dir
from huron.schema import load_schema, validate

pytestmark = pytest.mark.unit


def inventory() -> ProtocolInventory:
    """Construct a complete, deterministic healthy inventory."""
    root = UUID(int=1)
    observed = DocumentObservation(state="PRESENT", sha256_digest="a" * 64)
    return ProtocolInventory(
        run_id=UUID(int=2),
        root_id=root,
        fence=FenceEvidence(
            controller_id=UUID(int=3),
            generation=1,
            root_id=root,
            operator="local:1000",
            terminated_writers=("container-identity",),
            old_roles=("legacy_writer",),
            new_role="verified_writer",
            database="7367538914089103371/16384/huron",
        ),
        revisions=(
            LegacyRevision(
                revision_id=UUID(int=4),
                dataset_id=UUID(int=5),
                number=1,
                path=str(
                    revision_dir(
                        PurePosixPath("/"),
                        EntityRef(UUID(int=1), "organization"),
                        EntityRef(UUID(int=2), "project"),
                        EntityRef(UUID(int=5), "dataset"),
                        1,
                        UUID(int=4),
                    ).relative_to("/")
                ),
                committed=observed,
                manifest=observed,
                metadata=observed,
                outcome="VERIFIED",
                findings=(),
                total_bytes=42,
            ),
        ),
    )


def test_canonical_inventory_and_transition_round_trip() -> None:
    """Packaged schemas and runtime values agree on canonical report bindings."""
    report = inventory()
    record = ProtocolTransition.bind(
        report, sequence=1, instant=datetime(2026, 1, 1, tzinfo=UTC), code_digest="b" * 64
    )
    validate("protocol-inventory-v1.json", report.model_dump(mode="json", by_alias=True))
    validate("protocol-transition-v1.json", record.model_dump(mode="json", by_alias=True))
    assert ProtocolInventory.decode(report.canonical) == report
    assert ProtocolTransition.decode(record.canonical) == record
    record.validate_inventory(report)
    assert record.report_digest == report.sha256
    assert record.verified_count == 1
    assert record.verified_bytes == 42
    assert report.certifies(report.revisions[0])


@pytest.mark.parametrize("state", ["ABSENT", "ERROR"])
def test_missing_and_unreadable_documents_have_no_fabricated_digest(state: str) -> None:
    """Only successfully observed bytes can carry a digest."""
    assert DocumentObservation.model_validate({"state": state}).sha256_digest is None
    with pytest.raises(ValueError, match="digest disagree"):
        DocumentObservation.model_validate({"state": state, "sha256_digest": "a" * 64})
    with pytest.raises(ValueError, match="digest disagree"):
        DocumentObservation(state="PRESENT")


def test_degraded_population_is_retained_without_certification() -> None:
    """Corruption remains in inventory and transition counts exclude it."""
    report = inventory()
    revision = report.revisions[0].model_copy(
        update={"outcome": "DEGRADED", "findings": ("PAYLOAD_DIGEST",)}
    )
    damaged = report.model_copy(update={"revisions": (revision,)})
    record = ProtocolTransition.bind(
        damaged, sequence=1, instant=datetime(2026, 1, 1, tzinfo=UTC), code_digest="b" * 64
    )
    assert record.verified_count == 0
    assert record.verified_bytes == 0
    assert record.degraded_revision_ids == (revision.revision_id,)
    assert not damaged.certifies(revision)
    assert not damaged.certifies(report.revisions[0])


@pytest.mark.parametrize(
    "changes",
    [
        {"findings": ["CORRUPT"]},
        {"outcome": "DEGRADED"},
        {"manifest": {"state": "ABSENT"}},
    ],
)
def test_verified_outcome_requires_complete_clean_evidence(changes: dict[str, object]) -> None:
    """Callers cannot claim health while retaining findings or absent documents."""
    document = inventory().revisions[0].model_dump()
    document.update(changes)
    with pytest.raises(ValueError):
        LegacyRevision.model_validate(document)


def test_report_refuses_duplicate_identities_and_mixed_roots() -> None:
    """Identity collisions and a fence from another root block the whole report."""
    report = inventory()
    document = report.model_dump(by_alias=True)
    document["root_id"] = UUID(int=99)
    with pytest.raises(ValueError, match="roots disagree"):
        ProtocolInventory.model_validate(document)
    document = report.model_dump(by_alias=True)
    document["revisions"] = [report.revisions[0], report.revisions[0]]
    with pytest.raises(ValueError, match="ambiguous identities"):
        ProtocolInventory.model_validate(document)


def test_record_detects_changed_report_and_noncanonical_encoding() -> None:
    """Neither changed reports nor alternate JSON spelling preserve certification."""
    report = inventory()
    record = ProtocolTransition.bind(
        report, sequence=1, instant=datetime(2026, 1, 1, tzinfo=UTC), code_digest="b" * 64
    )
    with pytest.raises(ValueError, match="disagrees with its inventory"):
        record.validate_inventory(report.model_copy(update={"revisions": ()}))
    with pytest.raises(ValueError, match="not canonical"):
        ProtocolInventory.decode(report.canonical + b"\n")
    with pytest.raises(ValueError):
        ProtocolInventory.decode(b"{}")


def test_empty_legacy_inventory_is_unambiguous() -> None:
    """An empty population still binds its root and authenticated fence."""
    document = inventory().model_dump(by_alias=True)
    document["revisions"] = []
    assert ProtocolInventory.model_validate(document).revisions == ()


@pytest.mark.parametrize(
    "change",
    ["missing_digest", "invented_digest", "verified_finding", "absent_verified", "empty_degraded"],
)
def test_packaged_schema_rejects_inconsistent_observation_and_outcome(change: str) -> None:
    """Portable document validation enforces the same local digest and outcome conditions."""
    document = inventory().model_dump(mode="json", by_alias=True)
    revision = document["revisions"][0]
    if change == "missing_digest":
        revision["manifest"]["sha256_digest"] = None
    elif change == "invented_digest":
        revision["manifest"]["state"] = "ERROR"
    elif change == "verified_finding":
        revision["findings"] = ["CORRUPT"]
    elif change == "absent_verified":
        revision["manifest"] = {"state": "ABSENT", "sha256_digest": None}
    else:
        revision["outcome"] = "DEGRADED"
    with pytest.raises(ValueError):
        ProtocolInventory.model_validate(document)
    with pytest.raises(ValidationError):
        validate("protocol-inventory-v1.json", document)


def test_runtime_binding_refuses_changed_path_identity_and_duplicate_generations() -> None:
    """Cross-field identity bindings are checked in addition to portable JSON shape validation."""
    report = inventory()
    document = report.revisions[0].model_dump()
    document["revision_id"] = UUID(int=99)
    with pytest.raises(ValueError, match="path and revision identity"):
        LegacyRevision.model_validate(document)
    generation = GenerationObservation(path="organization/CURRENT", sha256_digest="a" * 64)
    document = report.model_dump(by_alias=True)
    document["generations"] = [generation, generation]
    with pytest.raises(ValueError, match="ambiguous generation paths"):
        ProtocolInventory.model_validate(document)


@pytest.mark.parametrize("database", ["", "abc/1/huron", "1/2", "1/2/", "1/2/hur/on"])
def test_fence_binds_one_bounded_database_identity(database: str) -> None:
    """A malformed database identity is refused by both the runtime model and the schema."""
    report = inventory()
    record = ProtocolTransition.bind(
        report, sequence=1, instant=datetime(2026, 1, 1, tzinfo=UTC), code_digest="b" * 64
    )
    document = record.model_dump(mode="json", by_alias=True)
    document["fence"]["database"] = database
    with pytest.raises(ValueError):
        FenceEvidence.model_validate(document["fence"])
    with pytest.raises(ValidationError):
        validate("protocol-transition-v1.json", document)
    del document["fence"]["database"]
    with pytest.raises(ValueError):
        FenceEvidence.model_validate(document["fence"])
    with pytest.raises(ValidationError):
        validate("protocol-transition-v1.json", document)


@pytest.mark.parametrize(
    "name,identifier,model",
    [
        ("protocol-inventory-v1.json", "urn:huron:protocol-inventory:1", ProtocolInventory),
        ("protocol-transition-v1.json", "urn:huron:protocol-transition:1", ProtocolTransition),
    ],
)
def test_protocol_schema_loading_map_stays_in_sync_with_runtime_contracts(
    name: str,
    identifier: str,
    model: type[ProtocolInventory] | type[ProtocolTransition],
) -> None:
    """Packaged names resolve versioned contracts and cannot drift from runtime fields."""
    expected = model.model_json_schema(by_alias=True)
    expected["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    expected["$id"] = identifier
    assert load_schema(name) == expected
