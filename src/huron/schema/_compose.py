"""Schema-position traversal and deterministic intersection of metadata schema parts."""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING, Final, cast

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

    from huron.schema.metadata import JsonValue


def pointer(parent: str, token: str | int) -> str:
    return parent + "/" + str(token).replace("~", "~0").replace("/", "~1")


_MAP_SCHEMAS: Final = frozenset({"properties", "patternProperties", "$defs", "dependentSchemas"})
_LIST_SCHEMAS: Final = frozenset({"allOf", "anyOf", "oneOf", "prefixItems"})
_SINGLE_SCHEMAS: Final = frozenset(
    {
        "not",
        "if",
        "then",
        "else",
        "items",
        "contains",
        "additionalProperties",
        "unevaluatedItems",
        "unevaluatedProperties",
        "propertyNames",
        "contentSchema",
    }
)


def _schema_children(schema: Mapping[str, JsonValue]) -> Iterator[tuple[str, JsonValue]]:
    for keyword, value in schema.items():
        if keyword in _MAP_SCHEMAS and isinstance(value, dict):
            yield from ((pointer("/" + keyword, key), child) for key, child in value.items())
        elif keyword in _LIST_SCHEMAS and isinstance(value, list):
            yield from ((pointer("/" + keyword, i), child) for i, child in enumerate(value))
        elif keyword in _SINGLE_SCHEMAS:
            yield "/" + keyword, value


def _schema_nodes(
    schema: Mapping[str, JsonValue] | bool, where: str = ""
) -> Iterator[tuple[str, Mapping[str, JsonValue] | bool]]:
    yield where, schema
    if isinstance(schema, bool):
        return
    for suffix, child in _schema_children(schema):
        if isinstance(child, (dict, bool)):
            yield from _schema_nodes(child, where + suffix)


_ANNOTATIONS: Final = ("title", "description", "examples")
_ROOT_MEMBERS: Final = frozenset(
    {
        "$schema",
        "$id",
        "$comment",
        "$defs",
        "type",
        "title",
        "description",
        "properties",
        "required",
        "x-huron",
    }
)


def _part(name: str, document: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    result = deepcopy(dict(document))
    for _, node in _schema_nodes(result):
        if isinstance(node, dict) and "$ref" in node:
            reference = cast("str", node["$ref"])
            node["$ref"] = "#/$defs/" + name + "." + reference[len("#/$defs/") :]
    return result


def _property(parts: Sequence[JsonValue]) -> JsonValue:
    if len(parts) == 1:
        return parts[0]
    result: dict[str, JsonValue] = {"allOf": list(parts)}
    for part in parts:
        if isinstance(part, dict):
            result.update({key: part[key] for key in _ANNOTATIONS if key in part})
    return result


def _properties(parts: Sequence[tuple[str, Mapping[str, JsonValue]]]) -> dict[str, JsonValue]:
    declarations: dict[str, list[JsonValue]] = {}
    for _, part in parts:
        for key, value in cast("dict[str, JsonValue]", part.get("properties", {})).items():
            declarations.setdefault(key, []).append(value)
    return {key: _property(values) for key, values in declarations.items()}


def flatten(parts: Sequence[tuple[str, Mapping[str, JsonValue]]]) -> dict[str, JsonValue]:
    rewritten = [(name, _part(name, document)) for name, document in parts]
    definitions: dict[str, JsonValue] = {}
    required: list[str] = []
    clauses: list[JsonValue] = []
    for name, part in rewritten:
        for key, value in cast("dict[str, JsonValue]", part.get("$defs", {})).items():
            definitions[name + "." + key] = value
        required.extend(cast("list[str]", part.get("required", [])))
        if clause := {key: value for key, value in part.items() if key not in _ROOT_MEMBERS}:
            clauses.append(clause)
    result: dict[str, JsonValue] = {
        "properties": _properties(rewritten),
        "required": list(dict.fromkeys(required)),
    }
    if definitions:
        result["$defs"] = definitions
    if clauses:
        result["allOf"] = clauses
    return result
