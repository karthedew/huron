"""Drift: compare what the service records with what the lake holds.

The storage is rooted at the organization's root, so the API paths of the rows are lake paths
below it. Every finding names its place as a lake path in the API form.
"""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from huron.core.storage.lakepath import LakePath
from huron.core.storage.layout import MARKER_FILE, is_reserved_entry
from huron.core.storage.marker import MarkerState, marker_state
from huron.schema.naming import METADATA_FILE, PART_SUFFIX, rel_path_key

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from huron.core.storage.ports import Entry, ShareReader

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
    directory: LakePath
    instance_id: str
    own_marker: bool


def check_organization(storage: ShareReader, expected: ExpectedOrganization) -> list[Finding]:
    """The organization-level findings: a missing directory, or a missing or wrong marker.

    The marker is only checked for an organization that carries its own; the share root's
    marker is checked before any disk operation instead.
    """
    name, directory = expected.name, expected.directory
    if not _is_directory(storage, directory):
        return [Finding("org_dir_missing", Severity.ERROR, name, str(directory))]
    findings: list[Finding] = []
    if expected.own_marker:
        state = marker_state(storage, directory, expected.instance_id, name)
        marker = str(directory.joinpath(MARKER_FILE))
        if state is MarkerState.NO_MARKER:
            findings.append(Finding("org_marker_missing", Severity.ERROR, name, marker))
        elif state is not MarkerState.OK:
            findings.append(
                Finding("org_marker_mismatch", Severity.ERROR, name, marker, str(state))
            )
    return findings


def check(
    storage: ShareReader,
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
        findings += _directory(storage, namespace, known)
    for collection in collections:
        findings += _collection(storage, collection, now, hash_files)
    return sorted(findings, key=lambda f: (_RANK[f.severity], f.identifier, f.path, f.code))


def _directory(
    storage: ShareReader, namespace: ExpectedDirectory, known: set[str]
) -> list[Finding]:
    identifier, location = namespace.identifier, LakePath.parse(namespace.disk_path)
    if not _is_directory(storage, location):
        return [Finding("namespace_dir_missing", Severity.ERROR, identifier, str(location))]
    return [
        Finding("dir_unrecorded", Severity.WARNING, identifier, f"{location}/{entry.names[0]}")
        for entry in storage.walk(location)
        if len(entry.names) == 1
        and entry.kind == "dir"
        and f"{namespace.disk_path}/{entry.names[0]}" not in known
    ]


def _collection(
    storage: ShareReader,
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
    location = LakePath.parse(collection.disk_path)
    if not _is_directory(storage, location):
        return [
            *findings,
            Finding("collection_dir_missing", Severity.ERROR, identifier, str(location)),
        ]
    findings += _files(storage, location, collection, now, hash_files)
    sidecar = location.joinpath(METADATA_FILE)
    if storage.read_bytes(sidecar) != collection.sidecar:
        findings.append(Finding("sidecar_stale", Severity.WARNING, identifier, str(sidecar)))
    return findings


def _files(
    storage: ShareReader,
    location: LakePath,
    collection: ExpectedCollection,
    now: datetime,
    hash_files: bool,
) -> list[Finding]:
    identifier = collection.identifier
    findings: list[Finding] = []
    seen: set[str] = set()
    for entry in storage.walk(location):
        if entry.kind != "file":
            continue
        rel_path = "/".join(entry.names)
        shown = f"{location}/{rel_path}"
        if rel_path.endswith(PART_SUFFIX):
            if now.timestamp() - entry.mtime_ns / 1e9 > STALE_PART_AGE.total_seconds():
                findings.append(Finding("stale_part", Severity.INFO, identifier, shown))
            continue
        if is_reserved_entry(rel_path):
            continue
        key = rel_path_key(rel_path)
        recorded = collection.files.get(key)
        if recorded is None:
            findings.append(Finding("file_unrecorded", Severity.WARNING, identifier, shown))
            continue
        seen.add(key)
        findings += _changed(storage, location, entry, recorded, identifier, hash_files)
    findings += [
        Finding("file_missing", Severity.ERROR, identifier, f"{location}/{recorded['rel_path']}")
        for key, recorded in collection.files.items()
        if key not in seen
    ]
    return findings


def _changed(
    storage: ShareReader,
    location: LakePath,
    entry: Entry,
    recorded: Mapping[str, Any],
    identifier: str,
    hash_files: bool,
) -> list[Finding]:
    target = location.joinpath(*entry.names)
    if entry.size != recorded["size"]:
        detail = f"size {entry.size}, but the recorded size is {recorded['size']}"
        return [Finding("file_changed", Severity.WARNING, identifier, str(target), detail)]
    if hash_files and _sha256(storage, target) != recorded["sha256"]:
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


def _sha256(storage: ShareReader, location: LakePath) -> str | None:
    opened = storage.open_file(location)
    if opened is None:
        return None
    with closing(opened):
        return opened.sha256()


def _is_directory(storage: ShareReader, location: LakePath) -> bool:
    found = storage.stat(location)
    return found is not None and found.kind == "dir"


_RANK = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}
