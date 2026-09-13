"""Complete structural generation verification against acknowledged catalog identity."""

from __future__ import annotations

import hashlib
import json
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from huron.pkg.catalog.manifest import canonical_bytes
from huron.pkg.catalog.paths import dataset_dir, organization_dir, project_dir
from huron.pkg.catalog.records import Dataset, Organization, Project, jsonable
from huron.schema import validate

from .models import GenerationObservation

if TYPE_CHECKING:
    from uuid import UUID

    from .ports import LegacyStorage


class GenerationVerifier:
    """Refuse missing, stale or ambiguous hierarchy evidence before verifying revisions."""

    def __init__(self, storage: LegacyStorage) -> None:
        """Bind no-follow inventory and sealed structural document reads.

        Args:
            storage: Filesystem capability under continuously enforced writer exclusion.
        """
        self._storage = storage

    def verify(
        self, records: tuple[Organization | Project | Dataset, ...]
    ) -> tuple[GenerationObservation, ...]:
        """Check every historical generation, exact CURRENT pointer and acknowledged record.

        Args:
            records: Complete authoritative hierarchy, including entities without revisions.

        Returns:
            Exact control-file digests for the report's structural evidence.

        Raises:
            ValueError: If inventory, canonical bytes, identity or acknowledged state disagrees.
        """
        expected = _documents(records)
        paths = tuple(self._storage.generation_paths())
        if len(paths) != len(set(paths)) or set(paths) != set(expected):
            raise ValueError("structural generation inventory is missing, stale or ambiguous")
        observations = []
        for path in sorted(paths):
            payload = self._storage.read_generation(path)
            document = json.loads(payload)
            if not isinstance(document, dict) or canonical_bytes(document) != payload:
                raise ValueError("structural document is not a canonical object")
            current, generation = expected[path]
            _validate_document(document, current, generation)
            observations.append(
                GenerationObservation(path=path, sha256_digest=hashlib.sha256(payload).hexdigest())
            )
        return tuple(observations)


def _documents(
    records: tuple[Organization | Project | Dataset, ...],
) -> dict[str, tuple[dict[str, object], int | None]]:
    organizations, projects = _parents(records)
    result: dict[str, tuple[dict[str, object], int | None]] = {}
    for record in records:
        if not 1 <= record.generation <= 999_999 or record.version != record.generation:
            raise ValueError("acknowledged structural generation counters are invalid")
        path = _entity_path(record, organizations, projects)
        current = jsonable(record)
        current["schema"] = "urn:huron:generation:1"
        result[str(path / "CURRENT.json")] = current, None
        for generation in range(1, record.generation + 1):
            result[str(path / "generations" / f"{generation:06d}.json")] = current, generation
    return result


def _parents(
    records: tuple[Organization | Project | Dataset, ...],
) -> tuple[dict[UUID, Organization], dict[UUID, Project]]:
    if len({record.id for record in records}) != len(records):
        raise ValueError("structural catalog identities collide")
    organizations = {record.id: record for record in records if isinstance(record, Organization)}
    projects = {record.id: record for record in records if isinstance(record, Project)}
    return organizations, projects


def _entity_path(
    record: Organization | Project | Dataset,
    organizations: dict[UUID, Organization],
    projects: dict[UUID, Project],
) -> PurePosixPath:
    root = PurePosixPath(".")
    try:
        if isinstance(record, Organization):
            return organization_dir(root, record)
        if isinstance(record, Project):
            return project_dir(root, organizations[record.organization_id], record)
        project = projects[record.project_id]
        return dataset_dir(root, organizations[project.organization_id], project, record)
    except KeyError as error:
        raise ValueError("structural catalog parent is missing") from error


def _validate_document(
    document: dict[str, object], current: dict[str, object], generation: int | None
) -> None:
    if generation is None:
        _validate_pointer(document, current)
        return
    validate("generation-v1.json", document)
    if (
        _generation_identity(current) != _generation_identity(document)
        or document["generation"] != generation
        or document["version"] != generation
    ):
        raise ValueError("structural generation identity or parent disagrees")
    if generation == current["generation"] and document != current:
        raise ValueError("acknowledged generation differs from the authoritative catalog")


def _generation_identity(document: dict[str, object]) -> dict[str, object]:
    mutable = {"title", "description", "generation", "version"}
    return {key: value for key, value in document.items() if key not in mutable}


def _validate_pointer(document: dict[str, object], current: dict[str, object]) -> None:
    expected = {
        "generation": current["generation"],
        "path": f"generations/{int(str(current['generation'])):06d}.json",
    }
    if document != expected:
        raise ValueError("CURRENT does not name the acknowledged generation")
