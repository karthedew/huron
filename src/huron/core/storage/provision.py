"""Provisioning: prepare the lake path, each organization's directory, and catalog groups.

The storage administrator creates the lake path and each root; Huron never creates one. The
lake path gets the service owner, its mode, tusd's ``.tus-uploads`` and the marker that names
the service. Below each root the organization's directory is created when missing, given the
service owner and the organization mode, given its object area, and marked for the service and
the organization. No step of the lake path or of an organization is recursive. A catalog step
gives the catalog directory and every directory in it the catalog's group and the directory
mode; files keep their group and mode. The catalog step does not enter a ``.snapshot`` or
``.huron-objects`` directory and does not change it. Running a step again changes nothing, and
a marker naming another service or organization is never overwritten.
"""

from __future__ import annotations

import shlex
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from huron.core.storage.errors import LakeUnavailable, PermissionDenied, StorageError
from huron.core.storage.lakepath import LakePath
from huron.core.storage.layout import (
    DIRECTORY_MODE,
    MARKER_FILE,
    OBJECT_DIR_MODE,
    ORGANIZATION_MODE,
    UNWALKED,
    UPLOAD_DIR_MODE,
    UPLOADS,
)
from huron.core.storage.marker import (
    MARKER_MODE,
    MarkerState,
    marker_state,
    read_marker,
    render_marker,
)
from huron.core.storage.ports import GroupOutcome

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Iterable, Iterator, Sequence

    from huron.core.storage.layout import OrganizationPlace
    from huron.core.storage.marker import Marker
    from huron.core.storage.ports import Entry, GroupResult, ShareReader, Storage

__all__ = [
    "CatalogTarget",
    "OrganizationTarget",
    "Owner",
    "Provisioner",
    "absolute",
    "catalog_script",
    "provision_catalogs",
    "provision_script",
]


@dataclass(frozen=True, slots=True)
class Owner:
    """The service user's uid and the gid of the service group, which own the lake path, each
    organization directory, ``.tus-uploads`` and each object area.
    """

    uid: int
    gid: int

    def __str__(self) -> str:
        """The numeric ``uid:gid`` form of ``chown``."""
        return f"{self.uid}:{self.gid}"


@dataclass(frozen=True, slots=True)
class OrganizationTarget:
    """One organization to provision: where it goes, the marker it gets and its owner."""

    place: OrganizationPlace
    marker: Marker
    owner: Owner


@dataclass(frozen=True, slots=True)
class CatalogTarget:
    """A catalog directory and the group that it and every directory in it must carry, except a
    ``.snapshot`` or ``.huron-objects`` directory.

    ``place`` is the catalog's organization and ``location`` the catalog directory, both on a
    storage rooted at the lake path. ``group`` is the catalog's share group by name, or the gid
    of the service group for a catalog without one.
    """

    place: OrganizationPlace
    location: LakePath
    group: str | int


class Provisioner:
    """Prepares the lake path, organization directories below their roots, and catalogs.

    ``storage`` is rooted at the lake path, and every organization's ``base`` lies below it.
    ``lake_path`` is where that root is on this machine. The steps, the errors that this class
    makes and a refusal of a step (:class:`PermissionDenied`) name absolute paths. Every other
    :class:`StorageError` of ``storage`` keeps its path relative to the lake path.
    """

    def __init__(self, storage: Storage, lake_path: str) -> None:
        self._storage = storage
        self._lake_path = lake_path

    def prepare_lake(self, marker: Marker, owner: Owner, *, dry_run: bool = False) -> list[str]:
        """Give the lake path ``owner`` and its mode, prepare ``.tus-uploads`` and write
        ``marker`` (it names no organization); one line per step, done or planned.

        Raises :class:`StorageError` when the lake path is missing or already holds a marker of
        another service or of an organization; nothing is changed then.
        """
        root = LakePath()
        with self._named():
            if not self._is_directory(root):
                raise StorageError(
                    f"the lake path {self._lake_path} does not exist. The storage admin creates it",
                    {"path": self._lake_path},
                )
            marked = self._marked(root, marker)
            steps = self._directory(root, ORGANIZATION_MODE, owner, dry_run, create=False)
            steps += self._directory(UPLOADS, UPLOAD_DIR_MODE, owner, dry_run)
            return [*steps, self._mark(root, marker, marked, dry_run)]

    def provision(self, target: OrganizationTarget, *, dry_run: bool = False) -> list[str]:
        """Prepare one organization; returns a line per step, done or (``dry_run``) planned.

        Raises :class:`StorageError` when the root is missing or the directory already holds a
        marker of another service or organization; nothing is changed then.
        """
        place = target.place
        directory = place.directory
        with self._named():
            if not self._is_directory(place.base):
                root = self._shown(place.base)
                raise StorageError(
                    f"the root {root} of organization {place.name} does not exist."
                    " The storage admin creates it",
                    {"organization": place.name, "root": root},
                )
            found = self._storage.stat(directory)
            marked = (
                found is not None and found.kind == "dir" and self._marked(directory, target.marker)
            )
            steps = self._directory(directory, ORGANIZATION_MODE, target.owner, dry_run)
            steps += self._directory(place.objects, OBJECT_DIR_MODE, target.owner, dry_run)
            return [*steps, self._mark(directory, target.marker, marked, dry_run)]

    def provision_catalog(self, target: CatalogTarget, *, dry_run: bool = False) -> list[str]:
        """Give the catalog directory and every directory in it the group of ``target`` and the
        directory mode; one line for the catalog, done or planned.

        A ``.snapshot`` or ``.huron-objects`` directory is the exception: the step does not
        enter it and does not change it. Files keep their group and mode. The walk never
        follows a link. Raises :class:`StorageError` when a directory cannot be read or refuses
        the group.
        """
        shown = self._shown(target.location)
        group = target.group
        if dry_run:
            return [f"would set group {group} and mode {DIRECTORY_MODE:o}: {shown}"]
        with self._named():
            directories = [target.location, *self._below(target.location)]
            changed = sum(self._give(location, group) for location in directories)
        return [
            f"group {group} and mode {DIRECTORY_MODE:o}:"
            f" {changed} of {len(directories)} directories changed in {shown}"
        ]

    @contextmanager
    def _named(self) -> Generator[None]:
        """Name the place of a refused step (:class:`PermissionDenied`) by its absolute path, as
        the steps name it. Every other error passes unchanged.
        """
        try:
            yield
        except PermissionDenied as refused:
            path = str(refused.context["path"])
            shown = self._shown(LakePath.parse(path) if path else LakePath())
            raise PermissionDenied(
                f"permission denied on {shown}", {**refused.context, "path": shown}
            ) from refused

    def _directory(
        self, location: LakePath, mode: int, owner: Owner, dry_run: bool, *, create: bool = True
    ) -> list[str]:
        """The steps that make the directory ``location`` (with ``create``), then give it
        ``owner`` and ``mode``.
        """
        if dry_run:
            return self._planned(location, mode, owner, create)
        shown = self._shown(location)
        steps = []
        if create:
            made = self._storage.make_directory(location, mode)
            steps.append(f"created: {shown}" if made else f"exists: {shown}")
        if self._storage.set_owner(location, owner.uid, owner.gid):
            steps.append(f"owner set to {owner}: {shown}")
        if self._storage.set_mode(location, mode):
            steps.append(f"mode set to {mode:o}: {shown}")
        return steps

    def _planned(self, location: LakePath, mode: int, owner: Owner, create: bool) -> list[str]:
        shown = self._shown(location)
        found = self._storage.stat(location)
        if found is None:
            return [f"would create with owner {owner} and mode {mode:o}: {shown}"]
        steps = [f"exists: {shown}"] if create else []
        if (found.uid, found.gid) != (owner.uid, owner.gid):
            steps.append(f"would set owner {owner}: {shown}")
        if found.mode != mode:
            steps.append(f"would set mode {mode:o}: {shown}")
        return steps

    def _mark(self, directory: LakePath, marker: Marker, marked: bool, dry_run: bool) -> str:
        """Write ``marker`` in ``directory`` unless ``marked``; the step done or planned."""
        location = directory.joinpath(MARKER_FILE)
        path = self._shown(location)
        if marked:
            return f"marker ok: {path}"
        if dry_run:
            return f"would write marker: {path}"
        self._storage.write_bytes(location, render_marker(marker), MARKER_MODE)
        return f"marker written: {path}"

    def _marked(self, directory: LakePath, marker: Marker) -> bool:
        """Whether a matching marker is already there; refuses a marker it must not overwrite."""
        if self._storage.read_bytes(directory.joinpath(MARKER_FILE)) is None:
            return False
        state = marker_state(self._storage, directory, marker.instance_id, marker.organization)
        if state is MarkerState.OK:
            return True
        detail = "is unreadable"
        if state is not MarkerState.NO_MARKER:
            found = read_marker(self._storage, directory)
            detail = (
                f"names service {found.instance_id} and organization"
                f" {found.organization or '(none)'}"
            )
        shown = self._shown(directory)
        raise StorageError(
            f"{self._shown(directory.joinpath(MARKER_FILE))} {detail}. Huron does not overwrite it",
            {"organization": marker.organization, "path": shown, "state": str(state)},
        )

    def _below(self, location: LakePath) -> Iterator[LakePath]:
        """Every directory below ``location``, except a ``.snapshot`` or ``.huron-objects``
        directory, which the walk does not enter. An entry that cannot be read is an error.
        """
        for entry in self._storage.walk(location):
            found = location.joinpath(*entry.names)
            if entry.kind == "unreadable":
                raise StorageError(
                    f"the CLI cannot read {self._shown(found)}", {"path": self._shown(found)}
                )
            if entry.kind == "dir" and entry.names[-1] not in UNWALKED:
                yield found

    def _give(self, location: LakePath, group: str | int) -> bool:
        """Give the directory ``location`` ``group`` and the directory mode; whether either
        changed.
        """
        result = self._storage.set_group(location, group)
        if result.outcome is GroupOutcome.PENDING:
            shown = self._shown(location)
            raise StorageError(
                f"the CLI cannot give {shown} the group {group}: {_cause(result, location)}",
                {"path": shown, "group": f"{group}"},
            )
        moded = self._storage.set_mode(location, DIRECTORY_MODE)
        return result.outcome is GroupOutcome.CHANGED or moded

    def _is_directory(self, location: LakePath) -> bool:
        try:
            found = self._storage.stat(location)
        except LakeUnavailable:
            return False
        return found is not None and found.kind == "dir"

    def _shown(self, location: LakePath) -> str:
        return absolute(self._lake_path, location)


def provision_catalogs(
    storage: ShareReader,
    targets: Iterable[CatalogTarget],
    groups: Callable[[str], int | None],
) -> list[CatalogTarget]:
    """The catalogs that need the storage administrator.

    A catalog is selected when its directory has another group than ``target.group`` or no
    setgid bit, or when a directory in it has no setgid bit or another group than the catalog
    directory. A ``.snapshot`` or ``.huron-objects`` directory, and what is in it, do not
    select a catalog. ``groups`` gives the gid of a group name on this machine; a name that it does
    not know selects the catalog. A missing catalog directory is not selected: ``huron adm
    repair`` makes it. An entry that cannot be read, or a link, does not select the catalog:
    the check reports it. Raises :class:`LakeUnavailable` when the lake is not mounted.
    """
    return [target for target in targets if _selected(storage, target, groups)]


def provision_script(
    lake_path: str, lake_marker: Marker, owner: Owner, targets: Sequence[OrganizationTarget]
) -> str:
    """A POSIX shell script that does what :meth:`Provisioner.prepare_lake` and
    :meth:`Provisioner.provision` do, for root-owned directories.

    ``lake_path`` is where the lake path is on this machine; each organization's ``base``
    lies below it. The script refuses a symbolic link at each path that it changes.
    """
    uploads = absolute(lake_path, UPLOADS)
    lines = [
        "#!/bin/sh",
        "# Prepare the Huron lake path and organization directories:"
        " huron adm provision-orgs --emit-script.",
        "# Run it as root: it changes the owner of each directory. Running it again is harmless.",
        "set -eu",
        "",
        f"# lake path {lake_path}",
        *_require(lake_path, "the lake path"),
        *_marker_check(lake_path, lake_marker),
        *_owned(lake_path, ORGANIZATION_MODE, owner),
        *_made(uploads, UPLOAD_DIR_MODE, owner),
        *_marker_write(lake_path, lake_marker),
    ]
    for target in targets:
        lines += ["", *_script(lake_path, target)]
    return "\n".join(lines) + "\n"


def catalog_script(lake_path: str, targets: Sequence[CatalogTarget]) -> str:
    """A POSIX shell script that gives each catalog of ``targets`` its group: one ``find`` line
    for each catalog, for root.

    ``find`` keeps its default ``-P``, so it follows no symbolic link. It changes directories
    only, so files keep their group and mode. Unlike :meth:`Provisioner.provision_catalog`, it
    does not skip a ``.snapshot`` or ``.huron-objects`` directory.
    """
    lines = [
        "#!/bin/sh",
        "# Give each catalog directory and every directory in it the group of the catalog and"
        f" the mode {DIRECTORY_MODE:o}: huron adm provision-catalogs --emit-script.",
        "# Run it as root. Files keep their group and mode. Running it again is harmless.",
        "set -eu",
        "",
    ]
    for target in targets:
        directory = shlex.quote(absolute(lake_path, target.location))
        group = shlex.quote(f"{target.group}")
        lines.append(
            f"find {directory} -type d -exec chgrp {group} {{}} +"
            f" -exec chmod {DIRECTORY_MODE:o} {{}} +"
        )
    return "\n".join(lines) + "\n"


def absolute(root: str, location: LakePath) -> str:
    """Where ``location`` is on this machine, for a storage rooted at ``root``."""
    return f"{root.rstrip('/')}/{location}" if location.names else root


def _cause(result: GroupResult, location: LakePath) -> str:
    """Why the group change of ``location`` did not happen, without the lake path of the place.

    A storage names the place in the reason (``<place>: <error>`` or ``<place> does not
    exist``); the message of :meth:`Provisioner._give` names it already, by its absolute path.
    """
    reason, place = result.reason or "", f"{location}"
    if reason == f"{place} does not exist":
        return "the directory does not exist"
    return reason.removeprefix(f"{place}: ")


def _selected(
    storage: ShareReader, target: CatalogTarget, groups: Callable[[str], int | None]
) -> bool:
    # The check reports every storage error but an unmounted lake as an `unreadable` or a
    # `symbolic_link` finding, so such an error leaves the catalog to the check.
    group = target.group
    wanted = group if isinstance(group, int) else groups(group)
    try:
        found = storage.stat(target.location)
        if found is None or found.kind != "dir":
            return False
        if wanted is None or found.gid != wanted or not found.mode & stat.S_ISGID:
            return True
        return any(_drifted(entry, found.gid) for entry in storage.walk(target.location))
    except LakeUnavailable:
        raise
    except StorageError:
        return False


def _drifted(entry: Entry, gid: int) -> bool:
    """Whether a directory in a catalog has no setgid bit or another group than ``gid``.

    A directory that cannot be listed is yielded as ``unreadable``, never as ``dir``.
    """
    if entry.kind != "dir" or entry.names[-1] in UNWALKED:
        return False
    return entry.gid != gid or not entry.mode & stat.S_ISGID


def _script(lake_path: str, target: OrganizationTarget) -> list[str]:
    place = target.place
    shown = absolute(lake_path, place.directory)
    return [
        f"# organization {place.name}",
        *_require(absolute(lake_path, place.base), "the root"),
        *_marker_check(shown, target.marker),
        *_made(shown, ORGANIZATION_MODE, target.owner),
        *_made(absolute(lake_path, place.objects), OBJECT_DIR_MODE, target.owner),
        *_marker_write(shown, target.marker),
    ]


def _require(directory: str, what: str) -> list[str]:
    # Paths reach the shell only quoted: messages pass them to printf as arguments, never
    # inside a double-quoted string the shell would expand.
    quoted = shlex.quote(directory)
    return [
        f"test -d {quoted} || {{",
        f"  printf 'error: {what} %s does not exist\\n' {quoted} >&2; exit 1; }}",
    ]


def _no_link(path: str) -> str:
    # chmod follows a link, so a link at a path that root changes would change its target.
    quoted = shlex.quote(path)
    return (
        f"[ ! -L {quoted} ] || {{ printf 'error: %s is a symbolic link\\n' {quoted} >&2; exit 1; }}"
    )


def _owned(directory: str, mode: int, owner: Owner) -> list[str]:
    quoted = shlex.quote(directory)
    return [_no_link(directory), f"chown {owner} {quoted}", f"chmod {_exact(mode)} {quoted}"]


def _made(directory: str, mode: int, owner: Owner) -> list[str]:
    quoted = shlex.quote(directory)
    return [
        _no_link(directory),
        f"[ -d {quoted} ] || mkdir {quoted}",
        f"chown {owner} {quoted}",
        f"chmod {_exact(mode)} {quoted}",
    ]


def _exact(mode: int) -> str:
    # GNU chmod keeps the setgid bit of a directory for a numeric mode of four digits or fewer;
    # five digits set every bit.
    return f"{mode:05o}"


def _marker_check(directory: str, marker: Marker) -> list[str]:
    path = shlex.quote(f"{directory.rstrip('/')}/{MARKER_FILE}")
    service = shlex.quote(f'"instance_id": "{marker.instance_id}"')
    if marker.organization is None:
        named = f"! grep -qF '\"organization\"' {path}"
    else:
        organization = shlex.quote(f'"organization": "{marker.organization}"')
        named = f"grep -qF {organization} {path}"
    return [
        f"if [ -e {path} ]; then",
        f"  grep -qF {service} {path} && {named} || {{",
        f"    printf 'error: %s names another service or organization\\n' {path} >&2; exit 1; }}",
        "fi",
    ]


def _marker_write(directory: str, marker: Marker) -> list[str]:
    location = f"{directory.rstrip('/')}/{MARKER_FILE}"
    path = shlex.quote(location)
    rendered = shlex.quote(render_marker(marker).decode().rstrip("\n"))
    return [
        _no_link(location),
        f"[ -e {path} ] || printf '%s\\n' {rendered} > {path}",
        f"chmod {MARKER_MODE:o} {path}",
    ]
