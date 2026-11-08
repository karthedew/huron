"""Provisioning: mark the lake path, and prepare each organization's directory under its root.

The storage administrator owns the lake path and each root; Huron never creates one. The lake
path gets the marker that names the service. Below each root the organization's directory is
created when missing, given the organization mode, and marked for the service and the
organization. Running it again changes nothing, and a marker naming another service or
organization is never overwritten.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import TYPE_CHECKING

from huron.core.storage.errors import LakeUnavailable, StorageError
from huron.core.storage.lakepath import LakePath
from huron.core.storage.layout import MARKER_FILE, ORGANIZATION_MODE
from huron.core.storage.marker import (
    MARKER_MODE,
    MarkerState,
    marker_state,
    read_marker,
    render_marker,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from huron.core.storage.layout import OrganizationPlace
    from huron.core.storage.marker import Marker
    from huron.core.storage.ports import Stat, Storage

__all__ = ["OrganizationTarget", "Provisioner", "absolute", "provision_script"]


@dataclass(frozen=True, slots=True)
class OrganizationTarget:
    """One organization to provision: where it goes and the marker it gets."""

    place: OrganizationPlace
    marker: Marker


class Provisioner:
    """Marks the lake path, and creates and marks organization directories below their roots.

    ``storage`` is rooted at the lake path, and every organization's ``base`` lies below it.
    ``lake_path`` is where that root is on this machine; the steps name absolute paths.
    """

    def __init__(self, storage: Storage, lake_path: str) -> None:
        self._storage = storage
        self._lake_path = lake_path

    def mark_lake(self, marker: Marker, *, dry_run: bool = False) -> list[str]:
        """Write ``marker`` (it names no organization) at the lake path; one line per step.

        Raises :class:`StorageError` when the lake path is missing or already holds a marker of
        another service or of an organization; nothing is changed then.
        """
        root = LakePath()
        if not self._is_directory(root):
            raise StorageError(
                f"the lake path {self._lake_path} does not exist. The storage admin creates it",
                {"path": self._lake_path},
            )
        return [self._mark(root, marker, self._marked(root, marker), dry_run)]

    def provision(self, target: OrganizationTarget, *, dry_run: bool = False) -> list[str]:
        """Prepare one organization; returns a line per step, done or (``dry_run``) planned.

        Raises :class:`StorageError` when the root is missing or the directory already holds a
        marker of another service or organization; nothing is changed then.
        """
        place = target.place
        if not self._is_directory(place.base):
            root = self._shown(place.base)
            raise StorageError(
                f"the root {root} of organization {place.name} does not exist."
                " The storage admin creates it",
                {"organization": place.name, "root": root},
            )
        directory = place.directory
        found = self._storage.stat(directory)
        exists = found is not None and found.kind == "dir"
        marked = exists and self._marked(directory, target.marker)
        if dry_run:
            steps = self._planned(directory, found if exists else None)
        else:
            steps = self._made(directory)
        return [*steps, self._mark(directory, target.marker, marked, dry_run)]

    def _planned(self, directory: LakePath, found: Stat | None) -> list[str]:
        """The steps that would make the organization directory, which is ``found``."""
        shown = self._shown(directory)
        if found is None:
            return [f"would create: {shown}"]
        steps = [f"exists: {shown}"]
        if found.mode != ORGANIZATION_MODE:
            steps.append(f"would set mode {ORGANIZATION_MODE:o}: {shown}")
        return steps

    def _made(self, directory: LakePath) -> list[str]:
        """Make the organization directory with its mode; the steps done."""
        shown = self._shown(directory)
        created = self._storage.make_directory(directory, ORGANIZATION_MODE)
        steps = [f"created: {shown}" if created else f"exists: {shown}"]
        if self._storage.set_mode(directory, ORGANIZATION_MODE):
            steps.append(f"mode set to {ORGANIZATION_MODE:o}: {shown}")
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

    def _is_directory(self, location: LakePath) -> bool:
        try:
            found = self._storage.stat(location)
        except LakeUnavailable:
            return False
        return found is not None and found.kind == "dir"

    def _shown(self, location: LakePath) -> str:
        return absolute(self._lake_path, location)


def provision_script(
    lake_path: str, lake_marker: Marker, targets: Sequence[OrganizationTarget]
) -> str:
    """A POSIX shell script doing what :class:`Provisioner` does, for root-owned directories.

    ``lake_path`` is where the lake path is on this machine; each organization's ``base``
    lies below it.
    """
    lines = [
        "#!/bin/sh",
        "# Prepare the Huron lake path and organization directories:"
        " huron adm provision-orgs --emit-script.",
        "# Run as a user that may write the lake path and each root (or as root)."
        " Running it again is harmless.",
        "set -eu",
        "",
        f"# lake path {lake_path}",
        *_require(lake_path, "the lake path"),
        *_marker_check(lake_path, lake_marker),
        *_marker_write(lake_path, lake_marker),
    ]
    for target in targets:
        lines += ["", *_script(lake_path, target)]
    return "\n".join(lines) + "\n"


def absolute(root: str, location: LakePath) -> str:
    """Where ``location`` is on this machine, for a storage rooted at ``root``."""
    return f"{root.rstrip('/')}/{location}" if location.names else root


def _script(lake_path: str, target: OrganizationTarget) -> list[str]:
    place = target.place
    shown = absolute(lake_path, place.directory)
    directory = shlex.quote(shown)
    return [
        f"# organization {place.name}",
        *_require(absolute(lake_path, place.base), "the root"),
        *_marker_check(shown, target.marker),
        f"[ -d {directory} ] || mkdir {directory}",
        f"chmod {ORGANIZATION_MODE:o} {directory}",
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
    path = shlex.quote(f"{directory.rstrip('/')}/{MARKER_FILE}")
    rendered = shlex.quote(render_marker(marker).decode().rstrip("\n"))
    return [f"[ -e {path} ] || printf '%s\\n' {rendered} > {path}", f"chmod {MARKER_MODE:o} {path}"]
