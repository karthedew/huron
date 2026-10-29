"""The ``.huron`` marker at the share root, naming the service the share belongs to."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from huron.core.storage.errors import StorageError
from huron.core.storage.layout import MARKER_FILE

if TYPE_CHECKING:
    from pathlib import Path

    from huron.core.storage.ports import Storage

__all__ = ["Marker", "read_marker", "render_marker", "verify_marker"]


@dataclass(frozen=True, slots=True)
class Marker:
    """The marker's content."""

    huron: int
    api_url: str
    instance_id: str


def render_marker(marker: Marker) -> bytes:
    """The marker file's bytes."""
    document = {"huron": marker.huron, "api_url": marker.api_url, "instance_id": marker.instance_id}
    return json.dumps(document, sort_keys=True).encode() + b"\n"


def read_marker(storage: Storage, prefix: Path) -> Marker:
    """The marker at ``prefix``; raises :class:`StorageError` when absent or unreadable."""
    if not storage.is_directory(prefix):
        raise StorageError(f"{prefix} is not mounted on this machine", {"prefix": str(prefix)})
    data = storage.read_bytes(prefix / MARKER_FILE)
    if data is None:
        raise StorageError(
            f"{prefix} is not a Huron share (no {MARKER_FILE})", {"prefix": str(prefix)}
        )
    try:
        document = json.loads(data)
        return Marker(
            int(document["huron"]), str(document["api_url"]), str(document["instance_id"])
        )
    except (ValueError, KeyError, TypeError) as error:
        raise StorageError(
            f"{prefix / MARKER_FILE} is unreadable", {"prefix": str(prefix)}
        ) from error


def verify_marker(storage: Storage, prefix: Path, instance_id: str) -> Marker:
    """The marker, refused unless it names ``instance_id``."""
    marker = read_marker(storage, prefix)
    if marker.instance_id != instance_id:
        raise StorageError(
            f"{prefix} belongs to another Huron service ({marker.api_url})",
            {"prefix": str(prefix), "marker": marker.instance_id, "service": instance_id},
        )
    return marker
