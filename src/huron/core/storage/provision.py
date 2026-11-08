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

from huron.core.storage.errors import StorageError
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
    from pathlib import Path

    from huron.core.storage.layout import OrganizationPlace
    from huron.core.storage.marker import Marker
    from huron.core.storage.ports import Storage

__all__ = ["OrganizationTarget", "Provisioner", "provision_script"]


@dataclass(frozen=True, slots=True)
class OrganizationTarget:
    """One organization to provision: where it goes and the marker it gets."""

    place: OrganizationPlace
    marker: Marker


class Provisioner:
    """Marks the lake path, and creates and marks organization directories below their roots."""

    def __init__(self, storage: Storage, lake_path: Path) -> None:
        self._storage = storage
        self._lake_path = lake_path

    def mark_lake(self, marker: Marker, *, dry_run: bool = False) -> list[str]:
        """Write ``marker`` (it names no organization) at the lake path; one line per step.

        Raises :class:`StorageError` when the lake path is missing or already holds a marker of
        another service or of an organization; nothing is changed then.
        """
        lake_path = self._lake_path
        if not self._storage.is_directory(lake_path):
            raise StorageError(
                f"the lake path {lake_path} does not exist. The storage admin creates it",
                {"path": str(lake_path)},
            )
        return [self._mark(lake_path, marker, self._marked(lake_path, marker), dry_run)]

    def provision(self, target: OrganizationTarget, *, dry_run: bool = False) -> list[str]:
        """Prepare one organization; returns a line per step, done or (``dry_run``) planned.

        Raises :class:`StorageError` when the root is missing or the directory already holds a
        marker of another service or organization; nothing is changed then.
        """
        storage, place = self._storage, target.place
        directory = place.directory
        if not storage.is_directory(place.base):
            raise StorageError(
                f"the root {place.base} of organization {place.name} does not exist."
                " The storage admin creates it",
                {"organization": place.name, "root": str(place.base)},
            )
        exists = storage.is_directory(directory)
        marked = exists and self._marked(directory, target.marker)
        mode = f"{ORGANIZATION_MODE:o}"
        if dry_run:
            steps = [f"exists: {directory}" if exists else f"would create: {directory}"]
            if exists and storage.owner(directory).mode != ORGANIZATION_MODE:
                steps.append(f"would set mode {mode}: {directory}")
        else:
            created = storage.make_directory(directory, ORGANIZATION_MODE)
            steps = [f"created: {directory}" if created else f"exists: {directory}"]
            if storage.set_mode(directory, ORGANIZATION_MODE):
                steps.append(f"mode set to {mode}: {directory}")
        return [*steps, self._mark(directory, target.marker, marked, dry_run)]

    def _mark(self, directory: Path, marker: Marker, marked: bool, dry_run: bool) -> str:
        """Write ``marker`` in ``directory`` unless ``marked``; the step done or planned."""
        path = directory / MARKER_FILE
        if marked:
            return f"marker ok: {path}"
        if dry_run:
            return f"would write marker: {path}"
        self._storage.write_bytes(path, render_marker(marker), MARKER_MODE)
        return f"marker written: {path}"

    def _marked(self, directory: Path, marker: Marker) -> bool:
        """Whether a matching marker is already there; refuses a marker it must not overwrite."""
        if self._storage.read_bytes(directory / MARKER_FILE) is None:
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
        raise StorageError(
            f"{directory / MARKER_FILE} {detail}. Huron does not overwrite it",
            {"organization": marker.organization, "path": str(directory), "state": str(state)},
        )


def provision_script(
    lake_path: Path, lake_marker: Marker, targets: Sequence[OrganizationTarget]
) -> str:
    """A POSIX shell script doing what :class:`Provisioner` does, for root-owned directories."""
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
        lines += ["", *_script(target)]
    return "\n".join(lines) + "\n"


def _script(target: OrganizationTarget) -> list[str]:
    place = target.place
    directory = shlex.quote(str(place.directory))
    return [
        f"# organization {place.name}",
        *_require(place.base, "the root"),
        *_marker_check(place.directory, target.marker),
        f"[ -d {directory} ] || mkdir {directory}",
        f"chmod {ORGANIZATION_MODE:o} {directory}",
        *_marker_write(place.directory, target.marker),
    ]


def _require(directory: Path, what: str) -> list[str]:
    # Paths reach the shell only quoted: messages pass them to printf as arguments, never
    # inside a double-quoted string the shell would expand.
    quoted = shlex.quote(str(directory))
    return [
        f"test -d {quoted} || {{",
        f"  printf 'error: {what} %s does not exist\\n' {quoted} >&2; exit 1; }}",
    ]


def _marker_check(directory: Path, marker: Marker) -> list[str]:
    path = shlex.quote(str(directory / MARKER_FILE))
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


def _marker_write(directory: Path, marker: Marker) -> list[str]:
    path = shlex.quote(str(directory / MARKER_FILE))
    rendered = shlex.quote(render_marker(marker).decode().rstrip("\n"))
    return [f"[ -e {path} ] || printf '%s\\n' {rendered} > {path}", f"chmod {MARKER_MODE:o} {path}"]
