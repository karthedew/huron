"""Drift: compare what the service records with what the share holds."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from huron.core.storage.layout import MARKER_FILE, is_reserved_entry, resolve
from huron.core.storage.marker import MarkerState, marker_state
from huron.schema.naming import PART_SUFFIX, rel_path_key

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from pathlib import Path

    from huron.core.storage.ports import ShareReader

__all__ = [
    "STALE_DRAFT_AGE",
    "STALE_PART_AGE",
    "ExpectedCollection",
    "ExpectedDirectory",
    "ExpectedOrganization",
    "Finding",
    "Severity",
    "check",
    "check_organization",
]

STALE_PART_AGE = timedelta(hours=1)
STALE_DRAFT_AGE = timedelta(days=30)


class Severity(StrEnum):
    """How much a finding matters."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True, slots=True)
class Finding:
    """One disagreement between the service and the share."""

    code: str
    severity: Severity
    identifier: str
    path: str
    detail: str = ""

    def as_dict(self) -> dict[str, str]:
        """Render for output."""
        return {
            "code": self.code,
            "severity": str(self.severity),
            "identifier": self.identifier,
            "path": self.path,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class ExpectedDirectory:
    """A namespace (or catalog) directory the service knows about."""

    identifier: str
    disk_path: str


@dataclass(frozen=True, slots=True)
class ExpectedCollection:
    """A collection the service knows about."""

    identifier: str
    state: str
    created_at: datetime
    disk_path: str | None = None
    files: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    sidecar: bytes | None = None


@dataclass(frozen=True, slots=True)
class ExpectedOrganization:
    """An organization directory and whether it carries its own marker."""

    name: str
    directory: Path
    instance_id: str
    own_marker: bool


def check_organization(storage: ShareReader, expected: ExpectedOrganization) -> list[Finding]:
    """The organization-level findings: a missing directory, or a missing or wrong marker.

    The marker is only checked for an organization that carries its own; the share root's
    marker is checked before any disk operation instead.
    """
    name, directory = expected.name, expected.directory
    if not storage.is_directory(directory):
        return [Finding("org_dir_missing", Severity.ERROR, name, str(directory))]
    findings: list[Finding] = []
    if expected.own_marker:
        state = marker_state(storage, directory, expected.instance_id, name)
        marker = str(directory / MARKER_FILE)
        if state is MarkerState.NO_MARKER:
            findings.append(Finding("org_marker_missing", Severity.ERROR, name, marker))
        elif state is not MarkerState.OK:
            findings.append(
                Finding("org_marker_mismatch", Severity.ERROR, name, marker, str(state))
            )
    return findings


def check(
    storage: ShareReader,
    prefix: Path,
    namespaces: Iterable[ExpectedDirectory],
    collections: Iterable[ExpectedCollection],
    now: datetime,
    *,
    hash_files: bool = False,
) -> list[Finding]:
    """Every finding of section 6.4 of the plan for one catalog's namespaces and collections."""
    namespaces, collections = list(namespaces), list(collections)
    known = {item.disk_path for item in namespaces} | {
        c.disk_path for c in collections if c.disk_path is not None
    }
    findings: list[Finding] = []
    for namespace in namespaces:
        findings += _directory(
            storage,
            prefix,
            namespace.identifier,
            namespace.disk_path,
            "namespace_dir_missing",
            known,
        )
    for collection in collections:
        findings += _collection(storage, prefix, collection, now, hash_files)
    return sorted(findings, key=lambda f: (_RANK[f.severity], f.identifier, f.path, f.code))


def _directory(
    storage: ShareReader,
    prefix: Path,
    identifier: str,
    disk_path: str,
    missing_code: str,
    known: set[str],
) -> list[Finding]:
    path = resolve(prefix, disk_path)
    if not storage.is_directory(path):
        return [Finding(missing_code, Severity.ERROR, identifier, str(path))]
    findings: list[Finding] = []
    for entry in storage.walk(path):
        if "/" in entry.rel_path or entry.kind != "dir":
            continue
        if f"{disk_path}/{entry.rel_path}" not in known:
            findings.append(
                Finding("dir_unrecorded", Severity.WARNING, identifier, str(path / entry.rel_path))
            )
    return findings


def _collection(
    storage: ShareReader,
    prefix: Path,
    collection: ExpectedCollection,
    now: datetime,
    hash_files: bool,
) -> list[Finding]:
    identifier = collection.identifier
    if collection.state == "draft":
        if now - collection.created_at > STALE_DRAFT_AGE:
            return [Finding("stale_draft", Severity.INFO, identifier, "", "older than 30 days")]
        return []
    findings: list[Finding] = []
    if collection.state == "incomplete":
        findings.append(
            Finding(
                "incomplete",
                Severity.INFO,
                identifier,
                "",
                "metadata does not satisfy the catalog schema",
            )
        )
    assert collection.disk_path is not None
    path = resolve(prefix, collection.disk_path)
    if not storage.is_directory(path):
        return [*findings, Finding("collection_dir_missing", Severity.ERROR, identifier, str(path))]
    findings += _files(storage, path, collection, now, hash_files)
    if storage.read_bytes(path / "metadata.json") != collection.sidecar:
        findings.append(
            Finding("sidecar_stale", Severity.WARNING, identifier, str(path / "metadata.json"))
        )
    return findings


def _files(
    storage: ShareReader,
    path: Path,
    collection: ExpectedCollection,
    now: datetime,
    hash_files: bool,
) -> list[Finding]:
    identifier = collection.identifier
    findings: list[Finding] = []
    seen: set[str] = set()
    for entry in storage.walk(path):
        if entry.kind != "file":
            continue
        if entry.rel_path.endswith(PART_SUFFIX):
            age = now.timestamp() - entry.mtime_ns / 1e9
            if age > STALE_PART_AGE.total_seconds():
                findings.append(
                    Finding("stale_part", Severity.INFO, identifier, str(path / entry.rel_path))
                )
            continue
        if is_reserved_entry(entry.rel_path):
            continue
        key = rel_path_key(entry.rel_path)
        recorded = collection.files.get(key)
        if recorded is None:
            findings.append(
                Finding("file_unrecorded", Severity.WARNING, identifier, str(path / entry.rel_path))
            )
            continue
        seen.add(key)
        findings += _changed(
            storage, path, entry.rel_path, entry.size, recorded, identifier, hash_files
        )
    for key, recorded in collection.files.items():
        if key not in seen:
            findings.append(
                Finding(
                    "file_missing",
                    Severity.ERROR,
                    identifier,
                    str(path / str(recorded["rel_path"])),
                )
            )
    return findings


def _changed(
    storage: ShareReader,
    path: Path,
    rel_path: str,
    size: int,
    recorded: Mapping[str, Any],
    identifier: str,
    hash_files: bool,
) -> list[Finding]:
    target = path.joinpath(*rel_path.split("/"))
    if size != recorded["size"]:
        detail = f"size {size}, but the recorded size is {recorded['size']}"
        return [Finding("file_changed", Severity.WARNING, identifier, str(target), detail)]
    if hash_files and storage.hash(target).sha256 != recorded["sha256"]:
        return [
            Finding(
                "file_changed",
                Severity.WARNING,
                identifier,
                str(target),
                "sha256 is not the recorded sha256",
            )
        ]
    return []


_RANK = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}
