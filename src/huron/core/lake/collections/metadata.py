"""Metadata documents: merge patches and the ``metadata.json`` sidecar."""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any

from huron.core.lake.collections.errors import MetadataInvalid
from huron.pkg.canonical import canonical_bytes

if TYPE_CHECKING:
    from huron.core.lake.collections.models import CollectionView

__all__ = [
    "MAX_METADATA_BYTES",
    "SIDECAR_FORMAT",
    "check_metadata",
    "merge_patch",
    "render_sidecar",
]

MAX_METADATA_BYTES = 1024 * 1024
SIDECAR_FORMAT = 1


def merge_patch(document: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Apply an RFC 7396 JSON merge patch to ``document`` and return the result."""
    result = copy.deepcopy(document)
    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
        elif isinstance(value, dict):
            current = result.get(key)
            result[key] = merge_patch(current if isinstance(current, dict) else {}, value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def check_metadata(document: Any) -> dict[str, Any]:
    """Return ``document`` when it is a JSON object within the size limit."""
    if not isinstance(document, dict):
        raise MetadataInvalid(
            "metadata must be a JSON object",
            {
                "problems": [
                    {"path": "/", "message": "metadata must be a JSON object", "rule": "type"}
                ]
            },
        )
    size = len(canonical_bytes(document))
    if size > MAX_METADATA_BYTES:
        raise MetadataInvalid(
            "metadata is larger than 1 MiB",
            {"problems": [{"path": "/", "message": f"{size} bytes", "rule": "size"}]},
        )
    return document


def render_sidecar(view: CollectionView) -> bytes:
    """The canonical ``metadata.json`` written beside a settled collection's files.

    It omits the version and file count so that pushes do not make it stale; only metadata,
    override and schema changes do.
    """
    collection = view.collection
    document = {
        "huron": SIDECAR_FORMAT,
        "identifier": collection.identifier,
        "organization": view.organization,
        "catalog": view.catalog,
        "schema": view.schema.as_dict(),
        "schema_override": collection.schema_override,
        "metadata": collection.metadata,
        "created_by": collection.created_by,
        "created_at": collection.created_at.isoformat(),
    }
    return canonical_bytes(document) + b"\n"
