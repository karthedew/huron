"""Drift: compare what the service records with what the lake holds.

The storage is rooted at the organization's root, so the API paths of the rows are lake paths
below it. Every finding names its place as a lake path in the API form. The check only reads:
it reports what it finds and removes or changes nothing. An entry that it cannot stat or list
is an ``unreadable`` finding, never an error that stops the check. The object area of an
organization is the one exception: only the service user can list it, so the check skips it for
any other account.
"""

from __future__ import annotations

import os
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from huron.core.storage.errors import (
    LakeUnavailable,
    PermissionDenied,
    StorageError,
    SymlinkInLake,
)
from huron.core.storage.lakepath import LakePath
from huron.core.storage.layout import (
    DIRECTORY_MODE,
    FILE_MODE,
    LINK_PROBE_PREFIX,
    MARKER_FILE,
    NFS_PREFIX,
    OBJECT_DIR,
    ORGANIZATION_MODE,
    SNAPSHOT_DIR,
    is_ignored_entry,
)
from huron.core.storage.marker import MarkerState, marker_state
from huron.schema.naming import METADATA_FILE, PART_SUFFIX, rel_path_key

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator, Mapping

    from huron.core.storage.ports import Entry, ShareReader, Stat

__all__ = [
    "STALE_DRAFT_AGE",
    "STALE_PART_AGE",
    "STALE_PROBE_AGE",
    "ExpectedCollection",
    "ExpectedDirectory",
    "ExpectedOrganization",
    "Finding",
    "Severity",
    "check",
    "check_organization",
    "unreadable_detail",
]

STALE_PART_AGE = timedelta(hours=1)
STALE_PROBE_AGE = timedelta(hours=1)
STALE_DRAFT_AGE = timedelta(days=30)

type Names = tuple[str, ...]
#: A group name or gid, as a row names it; ``None`` for the group of the catalog directory.
type Group = str | int | None


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
    """A catalog or namespace directory that the service knows about, and what it carries.

    ``mode`` is its mode with the setgid bit. ``group`` is a group name or gid. For a catalog
    directory it is the catalog's share group, or the service group by gid for a catalog
    without one. ``None`` is the group of the catalog directory, which a directory below it
    inherits. ``owner`` is the uid of the service user, ``None`` when the service does not
    report it.
    """

    identifier: str
    disk_path: str
    mode: int = DIRECTORY_MODE
    group: Group = None
    owner: int | None = None


@dataclass(frozen=True, slots=True)
class ExpectedCollection:
    """A collection that the service knows about.

    ``pending`` is the state of the commit request that holds the collection, ``None`` when no
    request holds it. ``mode``, ``group`` and ``owner`` are those of its directory, as for an
    :class:`ExpectedDirectory`. Its files have the mode ``0644`` and the same owner.
    """

    identifier: str
    state: str
    created_at: datetime
    disk_path: str | None = None
    files: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    sidecar: bytes | None = None
    pending: str | None = None
    mode: int = DIRECTORY_MODE
    group: Group = None
    owner: int | None = None


@dataclass(frozen=True, slots=True)
class ExpectedOrganization:
    """An organization directory, whether it carries its own marker, and what it carries.

    ``mode`` is its mode with the setgid bit. ``group`` is the gid of the service group and
    ``owner`` the uid of the service user, each ``None`` when the service does not report it.
    """

    name: str
    directory: LakePath
    instance_id: str
    own_marker: bool
    mode: int = ORGANIZATION_MODE
    group: int | None = None
    owner: int | None = None

    def untrusted(self, findings: Iterable[Finding]) -> bool:
        """Whether ``findings``, which :func:`check_organization` gave for this organization,
        show that its directory cannot be trusted. Then the check must not look at its catalogs.

        Only the directory of an organization with its own marker can be untrusted. It is
        untrusted when it is missing or is a symbolic link, when a name on the way to it is a
        symbolic link, or when its marker is missing, is a symbolic link, or names another
        service or organization. No other finding makes it untrusted. Examples are a marker that
        the check cannot read, and another link or entry that the check cannot read, in the
        directory or in its object area.
        """
        names = self.directory.names
        on_the_way = {"/".join(names[:size]) for size in range(1, len(names) + 1)}
        on_the_way.add(str(self.directory.joinpath(MARKER_FILE)))
        return self.own_marker and any(
            finding.code in _UNTRUSTED
            or (finding.code == "symbolic_link" and finding.path in on_the_way)
            for finding in findings
        )


def check_organization(
    storage: ShareReader, expected: ExpectedOrganization, now: datetime
) -> list[Finding]:
    """The findings of an organization directory: whether it exists, its mode, owner and
    group, its marker, the links and the entries that the check cannot stat or list, the
    probe files that a stopped readiness probe left, and the ``.nfs*`` files and the
    ``.snapshot`` directory in it.

    The marker is only checked for an organization that carries its own; the share root's
    marker is checked before any disk operation instead. The check lists the organization
    directory and its object area, and no directory below them. The object area is a reserved
    directory. In it, the check reports only probe files, links and entries that it cannot
    stat. Only the service user can list the object area, so for any other account the check
    skips it.
    """
    name, directory = expected.name, expected.directory
    found, findings = _read(name, directory, lambda: storage.stat(directory))
    if findings:
        return findings
    if found is None or found.kind != "dir":
        return [Finding("org_dir_missing", Severity.ERROR, name, str(directory))]
    wanted = _Wanted(expected.mode, expected.owner, expected.group, "the service group")
    findings += wanted.drift(name, directory, found)
    if expected.own_marker:
        findings += _marker(storage, expected)
    entries, failed = _listing(name, directory, lambda: _entries(storage, directory), now)
    findings += failed
    for entry in entries:
        made = _made_outside(name, directory.joinpath(*entry.names), entry)
        findings += [made] if made is not None else []
    if any(entry.names == (OBJECT_DIR,) and entry.kind == "dir" for entry in entries):
        area = directory.joinpath(OBJECT_DIR)
        findings += _listing(name, area, lambda: _object_entries(storage, area), now)[1]
    return findings


def check(
    storage: ShareReader,
    catalog: ExpectedDirectory,
    namespaces: Iterable[ExpectedDirectory],
    collections: Iterable[ExpectedCollection],
    now: datetime,
    *,
    groups: Callable[[str], int | None],
    hash_files: bool = False,
) -> list[Finding]:
    """Every finding of one catalog: its directory, its namespaces and its collections.

    The check walks the catalog directory one time. ``groups`` gives the gid of a group name
    on this machine, ``None`` for a name that the machine does not know.
    """
    namespaces, collections = list(namespaces), list(collections)
    top = LakePath.parse(catalog.disk_path)
    found, findings = _read(catalog.identifier, top, lambda: storage.stat(top))
    if not findings:
        survey = _survey(storage, catalog, namespaces, collections, found, groups)
        findings = _catalog_findings(survey, catalog, found) + list(survey.findings)
        findings += _tree_findings(survey, namespaces, collections, now, hash_files)
    return sorted(
        findings, key=lambda f: (_RANK[f.severity], f.identifier, f.path, f.code, f.detail)
    )


def unreadable_detail(number: int | None) -> str:
    """The detail of an ``unreadable`` finding about an entry with the error ``number``."""
    return f"{os.strerror(number or 0)} (errno {number})"


@dataclass(frozen=True, slots=True)
class _Wanted:
    """What a directory or file must carry: a mode, and the owner and group when known.

    ``whose`` names the group in the detail of a finding.
    """

    mode: int
    owner: int | None
    gid: int | None
    whose: str

    def drift(self, identifier: str, location: LakePath, found: Stat | Entry) -> list[Finding]:
        """One ``mode_drift`` finding for each of the mode, the owner and the group of
        ``found`` that is not the one wanted.
        """
        details = []
        if found.mode != self.mode:
            details.append(f"the mode is {found.mode:o}, not {self.mode:o}")
        if self.owner is not None and found.uid != self.owner:
            details.append(f"the owner is {found.uid}, not the service user {self.owner}")
        if self.gid is not None and found.gid != self.gid:
            details.append(f"the group is {found.gid}, not {self.gid} ({self.whose})")
        return [
            Finding("mode_drift", Severity.WARNING, identifier, str(location), detail)
            for detail in details
        ]


@dataclass(frozen=True, slots=True)
class _Row:
    """A row of the service with a directory below the catalog directory, and what the
    directory carries.
    """

    identifier: str
    mode: int
    group: Group
    owner: int | None


@dataclass(frozen=True, slots=True)
class _Survey:
    """One walk of a catalog directory, with the rows indexed by the names of their
    directories below it.

    ``gid`` is the group of the catalog directory, ``None`` when the directory is missing.
    ``opaque`` is set when the directory could not be listed: nothing below it is known.
    ``closed`` are the names of the directories below that the walk could not list, and
    ``findings`` what the walk itself found.
    """

    storage: ShareReader
    top: LakePath
    rows: Mapping[Names, _Row]
    groups: Callable[[str], int | None]
    gid: int | None = None
    entries: Mapping[Names, Entry] = field(default_factory=dict)
    opaque: bool = False
    closed: frozenset[Names] = frozenset()
    findings: tuple[Finding, ...] = ()

    def names(self, disk_path: str) -> Names:
        """The names of the directory ``disk_path`` below the catalog directory."""
        return _below(self.top, disk_path)

    def location(self, names: Names) -> LakePath:
        """The lake path of ``names`` below the catalog directory."""
        return self.top.joinpath(*names)

    def row_of(self, names: Names) -> _Row:
        """The deepest row whose directory is ``names`` or holds it."""
        return next(
            self.rows[names[:size]]
            for size in range(len(names), -1, -1)
            if names[:size] in self.rows
        )

    def wanted(self, row: _Row | None) -> _Wanted:
        """What the directory of ``row`` carries, or any other directory when it is ``None``."""
        catalog = self.rows[()]
        if row is None:
            row = _Row(catalog.identifier, DIRECTORY_MODE, None, catalog.owner)
        if row.group is None:
            return _Wanted(row.mode, row.owner, self.gid, "the group of the catalog directory")
        gid = row.group if isinstance(row.group, int) else self.groups(row.group)
        return _Wanted(row.mode, row.owner, gid, f"the group {row.group}")

    def hidden(self, names: Names) -> bool:
        """Whether ``names`` lies below a directory that the check could not list."""
        return self.opaque or any(names[:size] in self.closed for size in range(1, len(names)))

    def present(self, names: Names) -> bool:
        """Whether a directory is at ``names``, or what is there cannot be known."""
        entry = self.entries.get(names)
        if entry is None:
            return self.hidden(names)
        return entry.kind in {"dir", "unreadable"}

    def children(self, names: Names) -> Iterator[tuple[Names, Entry]]:
        """The entries directly in the directory ``names``."""
        size = len(names)
        return (
            (child, entry)
            for child, entry in self.entries.items()
            if len(child) == size + 1 and child[:size] == names
        )

    def below(self, names: Names) -> Iterator[tuple[Names, Entry]]:
        """The entries below the directory ``names``, with their names relative to it."""
        size = len(names)
        return (
            (child[size:], entry)
            for child, entry in self.entries.items()
            if len(child) > size and child[:size] == names
        )


def _survey(
    storage: ShareReader,
    catalog: ExpectedDirectory,
    namespaces: list[ExpectedDirectory],
    collections: list[ExpectedCollection],
    found: Stat | None,
    groups: Callable[[str], int | None],
) -> _Survey:
    """The walk of the catalog directory ``found``, with the rows below it."""
    top = LakePath.parse(catalog.disk_path)
    expected: list[ExpectedDirectory | ExpectedCollection] = [*namespaces, *collections]
    rows = {(): _row(catalog)} | {
        _below(top, row.disk_path): _row(row) for row in expected if row.disk_path is not None
    }
    if found is None or found.kind != "dir":
        return _Survey(storage, top, rows, groups)
    walked, findings = _read(catalog.identifier, top, lambda: list(storage.walk(top)))
    entries = {entry.names: entry for entry in walked or []}
    closed = frozenset(names for names, entry in entries.items() if entry.kind == "unreadable")
    return _Survey(
        storage, top, rows, groups, found.gid, entries, walked is None, closed, tuple(findings)
    )


def _catalog_findings(
    survey: _Survey, catalog: ExpectedDirectory, found: Stat | None
) -> list[Finding]:
    """The findings of the catalog directory itself."""
    identifier, top = catalog.identifier, survey.top
    if found is None or found.kind != "dir":
        return [Finding("namespace_dir_missing", Severity.ERROR, identifier, str(top))]
    findings = _Wanted(catalog.mode, catalog.owner, None, "").drift(identifier, top, found)
    group = catalog.group
    if group is None:
        return findings
    wanted = group if isinstance(group, int) else survey.groups(group)
    if wanted is None:
        detail = f"this machine does not know the share group {group}"
    elif found.gid != wanted:
        named = "the service group" if isinstance(group, int) else f"the share group {group}"
        detail = f"the group is {found.gid}, not {wanted} ({named})"
    else:
        return findings
    return [
        *findings,
        Finding("share_group_mismatch", Severity.WARNING, identifier, str(top), detail),
    ]


def _tree_findings(
    survey: _Survey,
    namespaces: list[ExpectedDirectory],
    collections: list[ExpectedCollection],
    now: datetime,
    hash_files: bool,
) -> list[Finding]:
    """The findings of every entry below the catalog directory and of each row."""
    findings = [f for names, entry in survey.entries.items() for f in _entry(survey, names, entry)]
    for namespace in namespaces:
        names = survey.names(namespace.disk_path)
        if not survey.present(names):
            location = str(survey.location(names))
            findings.append(
                Finding("namespace_dir_missing", Severity.ERROR, namespace.identifier, location)
            )
    findings += _unrecorded(survey, [((), survey.rows[()].identifier)], namespaces)
    for collection in collections:
        findings += _collection(survey, collection, now, hash_files)
    return findings


def _entry(survey: _Survey, names: Names, entry: Entry) -> list[Finding]:
    """The findings of one entry below the catalog directory, each found one time."""
    identifier = survey.row_of(names).identifier
    location = survey.location(names)
    if entry.kind == "symlink":
        return [_symbolic_link(identifier, str(location))]
    if entry.kind == "unreadable":
        detail = unreadable_detail(entry.errno)
        return [Finding("unreadable", Severity.WARNING, identifier, str(location), detail)]
    made = _made_outside(identifier, location, entry)
    if made is not None:
        return [made]
    if entry.kind == "dir":
        return survey.wanted(survey.rows.get(names)).drift(identifier, location, entry)
    if entry.kind == "file":
        wanted = _Wanted(FILE_MODE, survey.row_of(names).owner, None, "")
        return wanted.drift(identifier, location, entry)
    return []


def _unrecorded(
    survey: _Survey, top: list[tuple[Names, str]], namespaces: list[ExpectedDirectory]
) -> list[Finding]:
    """The entries directly in the catalog and namespace directories that no row names.

    A ``.snapshot`` directory and a ``.nfs*`` file are not in the result: each one has its own
    finding (:func:`_made_outside`). A ``.snapshot`` file and a ``.nfs*`` directory are in it.
    """
    directories = top + [(survey.names(n.disk_path), n.identifier) for n in namespaces]
    findings: list[Finding] = []
    for names, identifier in directories:
        for child, entry in survey.children(names):
            location = survey.location(child)
            if child in survey.rows or _made_outside(identifier, location, entry) is not None:
                continue
            if entry.kind in {"dir", "unreadable"}:
                code = "dir_unrecorded"
            elif entry.kind == "file":
                code = "file_unrecorded"
            else:
                continue
            findings.append(Finding(code, Severity.WARNING, identifier, str(location)))
    return findings


def _collection(
    survey: _Survey, collection: ExpectedCollection, now: datetime, hash_files: bool
) -> list[Finding]:
    identifier = collection.identifier
    if collection.state == "draft":
        if now - collection.created_at > STALE_DRAFT_AGE:
            return [Finding("stale_draft", Severity.INFO, identifier, "", "older than 30 days")]
        return []
    findings: list[Finding] = []
    if collection.state == "incomplete":
        detail = "metadata does not satisfy the catalog schema"
        findings.append(Finding("incomplete", Severity.INFO, identifier, "", detail))
    assert collection.disk_path is not None
    names = survey.names(collection.disk_path)
    location = survey.location(names)
    if collection.pending is not None:
        detail = (
            f"a commit request is {collection.pending}."
            " Until the request ends, the directory can hold old and new files"
        )
        findings.append(Finding("pending_commit", Severity.INFO, identifier, str(location), detail))
    if not survey.present(names):
        findings.append(
            Finding("collection_dir_missing", Severity.ERROR, identifier, str(location))
        )
        return findings
    entry = survey.entries.get(names)
    if entry is not None and entry.kind == "dir":
        findings += _files(survey, collection, names, now, hash_files)
        findings += _sidecar(survey.storage, identifier, location, collection.sidecar)
    return findings


def _files(
    survey: _Survey,
    collection: ExpectedCollection,
    names: Names,
    now: datetime,
    hash_files: bool,
) -> list[Finding]:
    """The files of a collection compared with its recorded files.

    During a pending commit the directory can hold old and new files, so then the check reports
    only stale part files.
    """
    identifier = collection.identifier
    findings: list[Finding] = []
    seen: set[str] = set()
    for below, entry in survey.below(names):
        if entry.kind != "file":
            continue
        rel_path = "/".join(below)
        location = survey.location((*names, *below))
        if rel_path.endswith(PART_SUFFIX):
            if _older(entry, now, STALE_PART_AGE):
                findings.append(Finding("stale_part", Severity.INFO, identifier, str(location)))
            continue
        if collection.pending is not None or is_ignored_entry(rel_path):
            continue
        key = rel_path_key(rel_path)
        recorded = collection.files.get(key)
        if recorded is None:
            findings.append(Finding("file_unrecorded", Severity.WARNING, identifier, str(location)))
            continue
        seen.add(key)
        findings += _changed(survey.storage, identifier, location, entry, recorded, hash_files)
    if collection.pending is None:
        findings += _missing(survey, collection, names, seen)
    return findings


def _missing(
    survey: _Survey, collection: ExpectedCollection, names: Names, seen: set[str]
) -> list[Finding]:
    """The recorded files that the walk did not find, below a directory that it listed."""
    findings: list[Finding] = []
    for key, recorded in collection.files.items():
        place = (*names, *str(recorded["rel_path"]).split("/"))
        if key not in seen and not survey.hidden(place):
            location = str(survey.location(place))
            findings.append(
                Finding("file_missing", Severity.ERROR, collection.identifier, location)
            )
    return findings


def _changed(
    storage: ShareReader,
    identifier: str,
    location: LakePath,
    entry: Entry,
    recorded: Mapping[str, Any],
    hash_files: bool,
) -> list[Finding]:
    if entry.size != recorded["size"]:
        detail = f"size {entry.size}, but the recorded size is {recorded['size']}"
        return [Finding("file_changed", Severity.WARNING, identifier, str(location), detail)]
    if not hash_files:
        return []
    digest, findings = _read(identifier, location, lambda: _sha256(storage, location))
    if findings or digest == recorded["sha256"]:
        return findings
    detail = "sha256 is not the recorded sha256"
    return [Finding("file_changed", Severity.WARNING, identifier, str(location), detail)]


def _sidecar(
    storage: ShareReader, identifier: str, location: LakePath, sidecar: bytes | None
) -> list[Finding]:
    metadata = location.joinpath(METADATA_FILE)
    found, findings = _read(identifier, metadata, lambda: storage.read_bytes(metadata))
    if findings or found == sidecar:
        return findings
    return [Finding("sidecar_stale", Severity.WARNING, identifier, str(metadata))]


def _marker(storage: ShareReader, expected: ExpectedOrganization) -> list[Finding]:
    name, directory = expected.name, expected.directory
    marker = directory.joinpath(MARKER_FILE)
    state, findings = _read(
        name, marker, lambda: marker_state(storage, directory, expected.instance_id, name)
    )
    if state is MarkerState.NO_MARKER:
        return [Finding("org_marker_missing", Severity.ERROR, name, str(marker))]
    if state is not None and state is not MarkerState.OK:
        return [Finding("org_marker_mismatch", Severity.ERROR, name, str(marker), str(state))]
    return findings


def _listing(
    name: str, place: LakePath, read: Callable[[], list[Entry]], now: datetime
) -> tuple[list[Entry], list[Finding]]:
    """The entries that ``read`` lists directly in ``place``, and their findings: links,
    entries that the check cannot stat, and probe files older than :data:`STALE_PROBE_AGE`.
    When ``place`` cannot be listed, the one finding is that of ``place``.
    """
    entries, findings = _read(name, place, read)
    for entry in entries or []:
        location = place.joinpath(*entry.names)
        if entry.kind == "symlink":
            findings.append(_symbolic_link(name, str(location)))
        elif entry.kind == "unreadable":
            detail = unreadable_detail(entry.errno)
            findings.append(Finding("unreadable", Severity.WARNING, name, str(location), detail))
        elif _stale_probe(entry, now):
            detail = "the file is older than 1 hour. A readiness probe that stopped left it"
            findings.append(Finding("stale_link_probe", Severity.INFO, name, str(location), detail))
    return entries or [], findings


def _entries(storage: ShareReader, place: LakePath) -> list[Entry]:
    """The entries directly in the directory ``place``."""
    return list(storage.walk(place, recursive=False))


def _object_entries(storage: ShareReader, area: LakePath) -> list[Entry]:
    """The entries directly in the object area ``area``, or none when the account may not list it.

    The object area has the mode ``0700``, so only the service user can list it. A refusal is
    no finding: the object area is a reserved directory, not drift.
    """
    try:
        return _entries(storage, area)
    except PermissionDenied:
        return []


def _read[T](
    identifier: str, location: LakePath, read: Callable[[], T]
) -> tuple[T | None, list[Finding]]:
    """The result of ``read``, or ``None`` and the finding of the entry that it could not read.

    A link on the way is a ``symbolic_link`` finding at the link, any other storage error an
    ``unreadable`` finding at ``location``. A lake that is not mounted stops the check.
    """
    try:
        return read(), []
    except LakeUnavailable:
        raise
    except SymlinkInLake as error:
        return None, [_symbolic_link(identifier, str(error.context["path"]))]
    except StorageError as error:
        return None, [
            Finding("unreadable", Severity.WARNING, identifier, str(location), error.message)
        ]


def _made_outside(identifier: str, location: LakePath, entry: Entry) -> Finding | None:
    """The ``snapshot_dir`` finding of a ``.snapshot`` directory, which the storage shows, or
    the ``nfs_file`` finding of a ``.nfs*`` file, which an NFS client keeps; else ``None``.
    """
    name = entry.names[-1]
    if entry.kind == "dir" and name == SNAPSHOT_DIR:
        detail = "the storage shows its snapshots here. The check does not read them"
        return Finding("snapshot_dir", Severity.INFO, identifier, str(location), detail)
    if entry.kind == "file" and name.startswith(NFS_PREFIX):
        detail = "an NFS client keeps this removed file while a process holds it open"
        return Finding("nfs_file", Severity.INFO, identifier, str(location), detail)
    return None


def _stale_probe(entry: Entry, now: datetime) -> bool:
    """Whether ``entry`` is a probe file older than :data:`STALE_PROBE_AGE`. A probe makes
    files only, so a directory or another entry with the name of a probe file is none.
    """
    return (
        entry.kind == "file"
        and entry.names[-1].startswith(LINK_PROBE_PREFIX)
        and _older(entry, now, STALE_PROBE_AGE)
    )


def _symbolic_link(identifier: str, path: str) -> Finding:
    detail = (
        "the lake must not contain symbolic links. The storage administrator must remove this link"
    )
    return Finding("symbolic_link", Severity.ERROR, identifier, path, detail)


def _sha256(storage: ShareReader, location: LakePath) -> str | None:
    opened = storage.open_file(location)
    if opened is None:
        return None
    with closing(opened):
        return opened.sha256()


def _below(top: LakePath, disk_path: str) -> Names:
    return LakePath.parse(disk_path).names[len(top.names) :]


def _row(row: ExpectedDirectory | ExpectedCollection) -> _Row:
    return _Row(row.identifier, row.mode, row.group, row.owner)


def _older(entry: Entry, now: datetime, age: timedelta) -> bool:
    """Whether ``entry`` changed more than ``age`` before ``now``, to the nanosecond."""
    return _nanoseconds(now - _EPOCH) - entry.mtime_ns > _nanoseconds(age)


def _nanoseconds(span: timedelta) -> int:
    return span // _MICROSECOND * 1000


_RANK = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}
#: The findings of an organization that make its directory untrusted wherever they are.
_UNTRUSTED = frozenset({"org_dir_missing", "org_marker_missing", "org_marker_mismatch"})
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MICROSECOND = timedelta(microseconds=1)
