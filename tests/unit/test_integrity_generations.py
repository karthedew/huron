"""Complete structural chains reject missing, stale and conflicting parent evidence."""

import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path, PurePosixPath

import pytest
from jsonschema import ValidationError

from huron.core.catalog._impl.documents import GenerationDocuments
from huron.core.integrity.generations import GenerationVerifier
from huron.core.foundation.canonical import canonical_bytes
from huron.core.catalog.paths import organization_dir
from huron.core.rawstore import PosixRawStore
from huron.core.rawstore.maintenance import MaintenanceStore
from tests.unit.test_legacy_verification import legacy as legacy
from tests.unit.test_legacy_verification import legacy_records

pytestmark = pytest.mark.unit


def _verifier(root: Path) -> GenerationVerifier:
    return GenerationVerifier(MaintenanceStore(root, root.stat().st_uid))


def _organization(root: Path) -> Path:
    return Path(organization_dir(PurePosixPath(root), legacy_records()[0]))


def _overwrite(path: Path, payload: bytes) -> None:
    path.chmod(0o644)
    path.write_bytes(payload)
    path.chmod(0o444)


def test_complete_and_empty_structural_populations_have_exact_evidence(
    tmp_path: Path, legacy: tuple[object, str, object]
) -> None:
    """Every acknowledged generation and CURRENT pointer is bound by its actual digest."""
    observations = _verifier(tmp_path).verify(legacy_records())
    assert len(observations) == 6
    for item in observations:
        assert item.sha256_digest == hashlib.sha256((tmp_path / item.path).read_bytes()).hexdigest()
    empty = tmp_path / "empty"
    empty.mkdir()
    assert _verifier(empty).verify(()) == ()


@pytest.mark.parametrize(
    "change", ["missing", "extra", "stale", "noncanonical", "identity", "version", "schema"]
)
def test_structural_mutations_block_certification(
    tmp_path: Path, legacy: tuple[object, str, object], change: str
) -> None:
    """Missing or unacknowledged documents and malformed parent identities are never blessed."""
    directory = _organization(tmp_path)
    generation = directory / "generations/000001.json"
    document = json.loads(generation.read_bytes())
    if change == "missing":
        generation.unlink()
    elif change == "extra":
        (directory / "generations/000002.json").write_bytes(generation.read_bytes())
    elif change == "stale":
        _overwrite(
            directory / "CURRENT.json",
            canonical_bytes({"generation": 2, "path": "generations/000002.json"}),
        )
    elif change == "noncanonical":
        _overwrite(generation, b" " + generation.read_bytes())
    else:
        key, value = {
            "identity": ("slug", "other"),
            "version": ("version", 2),
            "schema": ("title", ""),
        }[change]
        document[key] = value
        _overwrite(generation, canonical_bytes(document))
    with pytest.raises((ValueError, ValidationError)):
        _verifier(tmp_path).verify(legacy_records())


@pytest.mark.parametrize("change", ["missing_parent", "duplicate", "stale_state", "counter"])
def test_catalog_ambiguity_and_stale_acknowledged_state_block_certification(
    tmp_path: Path, legacy: tuple[object, str, object], change: str
) -> None:
    """Physical evidence cannot override missing ancestry or a different acknowledged record."""
    organization, project, dataset = legacy_records()
    records = {
        "missing_parent": (project, dataset),
        "duplicate": (organization, project, dataset, organization),
        "stale_state": (replace(organization, title="Changed"), project, dataset),
        "counter": (replace(organization, generation=0), project, dataset),
    }[change]
    with pytest.raises(ValueError):
        _verifier(tmp_path).verify(records)


async def test_historical_descriptions_may_change_without_changing_structural_identity(
    tmp_path: Path, legacy: tuple[object, str, object]
) -> None:
    """All historical generations remain checked while CURRENT names the acknowledged successor."""
    organization, project, dataset = legacy_records()
    successor = replace(organization, title="New title", generation=2, version=2)
    await GenerationDocuments(PosixRawStore(tmp_path)).write(
        PurePosixPath(_organization(tmp_path)), successor
    )
    assert len(_verifier(tmp_path).verify((successor, project, dataset))) == 7


def test_structural_documents_require_sealed_owned_independent_inodes(
    tmp_path: Path, legacy: tuple[object, str, object]
) -> None:
    """A valid JSON document cannot bypass filesystem ownership, seal or link-count checks."""
    path = _organization(tmp_path) / "generations/000001.json"
    with pytest.raises(ValueError, match="ownership"):
        GenerationVerifier(MaintenanceStore(tmp_path, os.geteuid() + 1)).verify(legacy_records())
    path.chmod(0o644)
    with pytest.raises(ValueError, match="seal"):
        _verifier(tmp_path).verify(legacy_records())
    path.chmod(0o444)
    os.link(path, tmp_path / "shared-generation")
    with pytest.raises(ValueError, match="independent"):
        _verifier(tmp_path).verify(legacy_records())
