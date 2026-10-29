"""Drift: compare what the service records with what the share holds."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from huron.core.storage.aclplan import AclPlan, diff
from huron.core.storage.errors import StorageError
from huron.core.storage.layout import is_reserved_entry, resolve
from huron.pkg.fs.acl import AclError
from huron.schema.naming import PART_SUFFIX, rel_path_key

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from pathlib import Path

    from huron.core.storage.ports import Storage

__all__ = [
    "STALE_DRAFT_AGE",
    "STALE_PART_AGE",
    "ExpectedCollection",
    "ExpectedDirectory",
    "Finding",
    "Severity",
    "check",
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
    """A namespace (or catalog) directory the service knows about, with its plan."""

    identifier: str
    disk_path: str
    plan: AclPlan | None = None


@dataclass(frozen=True, slots=True)
class ExpectedCollection:
    """A collection the service knows about."""

    identifier: str
    state: str
    created_at: datetime
    disk_path: str | None = None
    plan: AclPlan | None = None
    files: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    sidecar: bytes | None = None


def check(
    storage: Storage,
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
            namespace.plan,
            "namespace_dir_missing",
            known,
        )
    for collection in collections:
        findings += _collection(storage, prefix, collection, now, hash_files)
    return sorted(findings, key=lambda f: (_RANK[f.severity], f.identifier, f.path, f.code))


def _directory(
    storage: Storage,
    prefix: Path,
    identifier: str,
    disk_path: str,
    plan: AclPlan | None,
    missing_code: str,
    known: set[str],
) -> list[Finding]:
    path = resolve(prefix, disk_path)
    if not storage.is_directory(path):
        return [Finding(missing_code, Severity.ERROR, identifier, str(path))]
    findings = [] if plan is None else _acl(storage, identifier, path, plan)
    for entry in storage.walk(path):
        if "/" in entry.rel_path or entry.kind != "dir":
            continue
        if f"{disk_path}/{entry.rel_path}" not in known:
            findings.append(
                Finding("dir_unrecorded", Severity.WARNING, identifier, str(path / entry.rel_path))
            )
    return findings


def _collection(
    storage: Storage, prefix: Path, collection: ExpectedCollection, now: datetime, hash_files: bool
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
    if collection.plan is not None:
        findings += _acl(storage, identifier, path, collection.plan)
    findings += _files(storage, path, collection, now, hash_files)
    if storage.read_bytes(path / "metadata.json") != collection.sidecar:
        findings.append(
            Finding("sidecar_stale", Severity.WARNING, identifier, str(path / "metadata.json"))
        )
    return findings


def _files(
    storage: Storage, path: Path, collection: ExpectedCollection, now: datetime, hash_files: bool
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
    storage: Storage,
    path: Path,
    rel_path: str,
    size: int,
    recorded: Mapping[str, Any],
    identifier: str,
    hash_files: bool,
) -> list[Finding]:
    target = path.joinpath(*rel_path.split("/"))
    if size != recorded["size"]:
        detail = f"size {size}, recorded {recorded['size']}"
        return [Finding("file_changed", Severity.WARNING, identifier, str(target), detail)]
    if hash_files and storage.hash(target).sha256 != recorded["sha256"]:
        return [
            Finding("file_changed", Severity.WARNING, identifier, str(target), "sha256 differs")
        ]
    return []


def _acl(storage: Storage, identifier: str, path: Path, plan: AclPlan) -> list[Finding]:
    try:
        problems = diff(plan, storage.read_acl(path))
    except (AclError, StorageError):
        return []
    if not problems:
        return []
    return [Finding("acl_drift", Severity.WARNING, identifier, str(path), "; ".join(problems))]


_RANK = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}
