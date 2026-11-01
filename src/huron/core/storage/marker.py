"""The ``.huron`` marker naming the service (and organization) a directory belongs to.

The share root's marker names only the service; an organization directory's marker also names
the organization.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from huron.core.storage.errors import StorageError
from huron.core.storage.layout import MARKER_FILE

if TYPE_CHECKING:
    from pathlib import Path

    from huron.core.storage.ports import Storage

__all__ = [
    "MARKER_MODE",
    "Marker",
    "MarkerState",
    "marker_state",
    "read_marker",
    "render_marker",
    "verify_marker",
]

MARKER_MODE = 0o644


@dataclass(frozen=True, slots=True)
class Marker:
    """The marker's content; ``organization`` is set on an organization directory's marker."""

    huron: int
    api_url: str
    instance_id: str
    organization: str | None = None


class MarkerState(StrEnum):
    """What a directory's marker says about it, as ``huron adm verify-mounts`` reports it."""

    OK = "ok"
    MISSING = "missing"
    NO_MARKER = "no marker"
    WRONG_INSTANCE = "wrong instance"
    WRONG_ORG = "wrong org"


def render_marker(marker: Marker) -> bytes:
    """The marker file's bytes."""
    document: dict[str, object] = {
        "huron": marker.huron,
        "api_url": marker.api_url,
        "instance_id": marker.instance_id,
    }
    if marker.organization is not None:
        document["organization"] = marker.organization
    return json.dumps(document, sort_keys=True).encode() + b"\n"


def read_marker(storage: Storage, directory: Path) -> Marker:
    """The marker in ``directory``; raises :class:`StorageError` when absent or unreadable.

    The error's ``context["state"]`` is the :class:`MarkerState` value of the refusal.
    """
    if not storage.is_directory(directory):
        raise StorageError(
            f"{directory} is not mounted on this machine",
            {"prefix": str(directory), "state": str(MarkerState.MISSING)},
        )
    data = storage.read_bytes(directory / MARKER_FILE)
    if data is None:
        raise StorageError(
            f"{directory} is not a Huron share: it has no {MARKER_FILE} marker",
            {"prefix": str(directory), "state": str(MarkerState.NO_MARKER)},
        )
    try:
        document = json.loads(data)
        organization = document.get("organization")
        return Marker(
            int(document["huron"]),
            str(document["api_url"]),
            str(document["instance_id"]),
            None if organization is None else str(organization),
        )
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise StorageError(
            f"{directory / MARKER_FILE} is unreadable",
            {"prefix": str(directory), "state": str(MarkerState.NO_MARKER)},
        ) from error


def verify_marker(
    storage: Storage, directory: Path, instance_id: str, organization: str | None = None
) -> Marker:
    """The marker, refused unless it names ``instance_id`` and exactly ``organization``.

    ``organization`` is ``None`` for the share root, whose marker must name no organization.
    """
    marker = read_marker(storage, directory)
    if marker.instance_id != instance_id:
        raise StorageError(
            f"{directory} belongs to another Huron service ({marker.api_url})",
            {
                "prefix": str(directory),
                "marker": marker.instance_id,
                "service": instance_id,
                "state": str(MarkerState.WRONG_INSTANCE),
            },
        )
    if marker.organization != organization:
        named = (
            "no organization"
            if marker.organization is None
            else f"organization {marker.organization}"
        )
        wanted = "the share root" if organization is None else f"organization {organization}"
        raise StorageError(
            f"the marker of {directory} names {named}, not {wanted}",
            {
                "prefix": str(directory),
                "marker": marker.organization,
                "organization": organization,
                "state": str(MarkerState.WRONG_ORG),
            },
        )
    return marker


def marker_state(
    storage: Storage, directory: Path, instance_id: str, organization: str | None = None
) -> MarkerState:
    """What :func:`verify_marker` would say, without raising."""
    try:
        verify_marker(storage, directory, instance_id, organization)
    except StorageError as error:
        return MarkerState(error.context["state"])
    return MarkerState.OK
