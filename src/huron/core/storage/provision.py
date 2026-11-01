"""Provisioning: prepare an organization's directory under its root, with its ACL and marker.

The storage administrator owns each root; Huron never creates one. Below it the organization's
directory is created when missing, given the organization ACL plan, and marked for the service
and the organization. Running it again changes nothing, and a marker naming another service or
organization is never overwritten.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import TYPE_CHECKING

from huron.core.storage.errors import StorageError
from huron.core.storage.layout import MARKER_FILE
from huron.core.storage.marker import (
    MARKER_MODE,
    MarkerState,
    marker_state,
    read_marker,
    render_marker,
)
from huron.pkg.fs.acl import render_acl

if TYPE_CHECKING:
    from collections.abc import Sequence

    from huron.core.storage.aclplan import AclPlan
    from huron.core.storage.layout import OrganizationPlace
    from huron.core.storage.marker import Marker
    from huron.core.storage.ports import Storage

__all__ = ["OrganizationTarget", "Provisioner", "provision_script"]


@dataclass(frozen=True, slots=True)
class OrganizationTarget:
    """One organization to provision: where it goes, its ACL plan and the marker it gets."""

    place: OrganizationPlace
    plan: AclPlan
    marker: Marker


class Provisioner:
    """Creates organization directories below existing roots and marks them."""

    def __init__(self, storage: Storage) -> None:
        self._storage = storage

    def provision(self, target: OrganizationTarget, *, dry_run: bool = False) -> list[str]:
        """Prepare one organization; returns a line per step, done or (``dry_run``) planned.

        Raises :class:`StorageError` when the root is missing or the directory already holds a
        marker of another service or organization; nothing is changed then.
        """
        storage, place = self._storage, target.place
        directory = place.directory
        if not storage.is_directory(place.base):
            raise StorageError(
                f"the root {place.base} of organization {place.name} does not exist;"
                " the storage administrator creates it",
                {"organization": place.name, "root": str(place.base)},
            )
        exists = storage.is_directory(directory)
        marked = exists and self._existing_marker(target)
        marker = directory / MARKER_FILE
        if dry_run:
            steps = [
                f"would apply the organization ACL plan to: {directory}"
                if exists
                else f"would create: {directory}",
                f"marker ok: {marker}" if marked else f"would write marker: {marker}",
            ]
            return steps
        created = storage.ensure_directory(directory, target.plan)
        steps = [f"{'created' if created else 'exists'}: {directory}"]
        if marked:
            steps.append(f"marker ok: {marker}")
        else:
            storage.write_bytes(marker, render_marker(target.marker), MARKER_MODE)
            steps.append(f"marker written: {marker}")
        return steps

    def _existing_marker(self, target: OrganizationTarget) -> bool:
        """Whether a matching marker is already there; refuses a marker it must not overwrite."""
        directory = target.place.directory
        if self._storage.read_bytes(directory / MARKER_FILE) is None:
            return False
        state = marker_state(self._storage, directory, target.marker.instance_id, target.place.name)
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
            f"refusing to overwrite {directory / MARKER_FILE}: it {detail}",
            {"organization": target.place.name, "path": str(directory), "state": str(state)},
        )


def provision_script(targets: Sequence[OrganizationTarget], *, acls: bool) -> str:
    """A POSIX shell script doing what :meth:`Provisioner.provision` does, for root-owned roots.

    Without ``acls`` (``acl_backend: none``) it sets modes only.
    """
    lines = [
        "#!/bin/sh",
        "# Prepare Huron organization directories: huron adm provision-orgs --emit-script.",
        "# Run as a user that may write each root (or as root). Running it again is harmless.",
        "set -eu",
    ]
    for target in targets:
        lines += ["", *_script(target, acls)]
    return "\n".join(lines) + "\n"


def _script(target: OrganizationTarget, acls: bool) -> list[str]:
    place, plan = target.place, target.plan
    root, directory = shlex.quote(str(place.base)), shlex.quote(str(place.directory))
    marker = shlex.quote(str(place.directory / MARKER_FILE))
    service = shlex.quote(f'"instance_id": "{target.marker.instance_id}"')
    organization = shlex.quote(f'"organization": "{place.name}"')
    # Paths and group names reach the shell only quoted: messages pass them to printf as
    # arguments, never inside a double-quoted string the shell would expand.
    lines = [
        f"# organization {place.name}",
        f"test -d {root} || {{",
        f"  printf 'error: the root %s does not exist\\n' {root} >&2; exit 1; }}",
        f"if [ -e {marker} ]; then",
        f"  grep -qF {service} {marker} && grep -qF {organization} {marker} || {{",
        f"    printf 'error: %s names another service or organization\\n' {marker} >&2; exit 1; }}",
        "fi",
        f"[ -d {directory} ] || mkdir {directory}",
    ]
    if plan.owning_group is not None:
        group = shlex.quote(plan.owning_group)
        lines.append(
            f"chgrp {group} {directory} || printf"
            f" 'warning: group %s is unknown here; group left unchanged\\n' {group} >&2"
        )
    lines.append(f"chmod {plan.mode:o} {directory}")
    if acls:
        lines += [f"setfacl --set-file=- {directory} <<'ACL'", *render_acl(plan.acl).splitlines()]
        lines.append("ACL")
    rendered = shlex.quote(render_marker(target.marker).decode().rstrip("\n"))
    lines += [
        f"[ -e {marker} ] || printf '%s\\n' {rendered} > {marker}",
        f"chmod {MARKER_MODE:o} {marker}",
    ]
    return lines
