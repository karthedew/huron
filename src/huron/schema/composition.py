"""Compose metadata schema documents along an ``extends`` chain."""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any

from huron.pkg.errors import HuronError, register

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = ["SchemaIncompatible", "compose", "resolve_chain"]

SCHEMA_INCOMPATIBLE = register("SCHEMA_INCOMPATIBLE", 422, "Schema incompatible")

_INHERITED_KEYS = ("title", "description", "additionalProperties")


class SchemaIncompatible(HuronError):
    """A child schema contradicts the schema it extends."""

    error_code = SCHEMA_INCOMPATIBLE


def compose(parent: Mapping[str, Any], child: Mapping[str, Any]) -> dict[str, Any]:
    """Return ``child`` composed on top of ``parent``.

    Properties merge with the child winning per property; ``required`` is the union; the child's
    ``title``, ``description`` and ``additionalProperties`` replace the parent's when present. A
    child that changes the ``type`` of a property the parent requires is refused.
    """
    parent_properties: dict[str, Any] = dict(parent.get("properties", {}))
    child_properties: Mapping[str, Any] = child.get("properties", {})
    parent_required: list[str] = list(parent.get("required", []))
    for name in parent_required:
        if name in child_properties and name in parent_properties:
            _check_same_type(name, parent_properties[name], child_properties[name])
    result: dict[str, Any] = {"type": "object"}
    for key in _INHERITED_KEYS:
        if key in child:
            result[key] = copy.deepcopy(child[key])
        elif key in parent:
            result[key] = copy.deepcopy(parent[key])
    properties = {**parent_properties, **child_properties}
    result["properties"] = copy.deepcopy(properties)
    required = parent_required + [
        name for name in child.get("required", []) if name not in parent_required
    ]
    result["required"] = required
    return result


def resolve_chain(documents: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Compose a chain of documents from the root (first) to the leaf (last)."""
    if not documents:
        raise ValueError("resolve_chain needs at least one document")
    resolved = compose({}, documents[0])
    for document in documents[1:]:
        resolved = compose(resolved, document)
    return resolved


def _check_same_type(name: str, before: Mapping[str, Any], after: Mapping[str, Any]) -> None:
    if before.get("type") != after.get("type"):
        raise SchemaIncompatible(
            f"property {name!r} is required by the parent schema and cannot change type",
            {"property": name, "parent_type": before.get("type"), "child_type": after.get("type")},
        )
