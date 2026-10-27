"""Owned metadata changes and safe publication of JSON Schema documents."""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING, Final, Literal
from urllib.parse import unquote

from jsonschema import SchemaError

from huron.schema._validator import HuronValidator, compile_regex
from huron.schema.catalog_config import Problem

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping

type JsonValue = bool | int | float | str | list[JsonValue] | dict[str, JsonValue] | None

BASE_SCHEMA_NAME: Final = "org"
DRAFT_2020_12: Final = "https://json-schema.org/draft/2020-12/schema"


class Absent(Enum):
    """Distinguish an omitted member from a member containing JSON null."""

    ABSENT = auto()


type _ChangeValue = JsonValue | Literal[Absent.ABSENT]


@dataclass(frozen=True, slots=True, init=False)
class FieldChange:
    """A field replacement with owned snapshots of its present values."""

    pointer: str
    _old: _ChangeValue
    _new: _ChangeValue

    def __init__(
        self, pointer: str, old: _ChangeValue = Absent.ABSENT, new: _ChangeValue = Absent.ABSENT
    ) -> None:
        """Snapshot a change independently of caller-owned containers.

        Args:
            pointer: The changed member's RFC 6901 pointer.
            old: Previous value, or absence for an added member.
            new: Replacement value, or absence for a removed member.
        """
        object.__setattr__(self, "pointer", pointer)
        object.__setattr__(self, "_old", deepcopy(old))
        object.__setattr__(self, "_new", deepcopy(new))
        self.__post_init__()

    def __post_init__(self) -> None:
        """Refuse changes that contain neither a previous nor replacement value.

        Raises:
            ValueError: If both sides are absent.
        """
        if self._old is Absent.ABSENT and self._new is Absent.ABSENT:
            raise ValueError("a field change requires at least one present value")

    @property
    def old(self) -> _ChangeValue:
        """Return an independent copy of the previous value.

        Returns:
            The previous JSON value or the absent sentinel.
        """
        return deepcopy(self._old)

    @property
    def new(self) -> _ChangeValue:
        """Return an independent copy of the replacement value.

        Returns:
            The replacement JSON value or the absent sentinel.
        """
        return deepcopy(self._new)

    def as_json(self) -> dict[str, JsonValue]:
        """Encode the change, omitting absent sides and retaining JSON nulls.

        Returns:
            An independent JSON object containing the pointer and present values.
        """
        result: dict[str, JsonValue] = {"pointer": self.pointer}
        for key, value in (("old", self.old), ("new", self.new)):
            if value is not Absent.ABSENT:
                result[key] = value
        return result


def _pointer(parent: str, token: str | int) -> str:
    return parent + "/" + str(token).replace("~", "~0").replace("/", "~1")


def _equal(left: JsonValue, right: JsonValue) -> bool:
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(_equal(v, right[k]) for k, v in left.items())
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _equal(a, b) for a, b in zip(left, right, strict=True)
        )
    if isinstance(left, bool) != isinstance(right, bool):
        return False
    return left == right


def _changes(
    before: Mapping[str, JsonValue], after: Mapping[str, JsonValue], parent: str
) -> Iterator[FieldChange]:
    for key in before.keys() | after.keys():
        pointer = _pointer(parent, key)
        old, new = before.get(key, Absent.ABSENT), after.get(key, Absent.ABSENT)
        if isinstance(old, dict) and isinstance(new, dict):
            yield from _changes(old, new, pointer)
        elif old is Absent.ABSENT or new is Absent.ABSENT or not _equal(old, new):
            yield FieldChange(pointer, old, new)


def field_changes(
    before: Mapping[str, JsonValue], after: Mapping[str, JsonValue]
) -> tuple[FieldChange, ...]:
    """Compare object members recursively and arrays as whole JSON values.

    Booleans differ from numbers; numerically equal integers and floats compare
    equal. Returned snapshots cannot be changed through either input document.

    Args:
        before: The previous metadata object.
        after: The replacement metadata object.

    Returns:
        Changes sorted by escaped pointer in Unicode code-point order.
    """
    return tuple(sorted(_changes(before, after, ""), key=lambda change: change.pointer))


class SchemaDocumentError(ValueError):
    """A nonempty, deterministically ordered set of publication failures."""

    def __init__(self, problems: Iterable[Problem]) -> None:
        """Collect all failures in stable pointer, rule and message order.

        Args:
            problems: Publication failures to report together.

        Raises:
            ValueError: If no problems were supplied.
        """
        ordered = sorted(
            problems, key=lambda problem: (problem.where, problem.rule, problem.message)
        )
        if not ordered:
            raise ValueError("schema document errors require at least one problem")
        self.problems = tuple(ordered)
        super().__init__("; ".join(f"{problem.where}: {problem.message}" for problem in ordered))


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
_FORBIDDEN_REFS: Final = frozenset({"$dynamicRef", "$dynamicAnchor", "$anchor"})


def _schema_children(schema: Mapping[str, JsonValue]) -> Iterator[tuple[str, JsonValue]]:
    for keyword, value in schema.items():
        if keyword in _MAP_SCHEMAS and isinstance(value, dict):
            yield from ((_pointer("/" + keyword, key), child) for key, child in value.items())
        elif keyword in _LIST_SCHEMAS and isinstance(value, list):
            yield from ((_pointer("/" + keyword, i), child) for i, child in enumerate(value))
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


def _valid_ref(value: JsonValue, positions: Mapping[str, Mapping[str, JsonValue] | bool]) -> bool:
    if not isinstance(value, str) or not value.startswith("#/$defs/"):
        return False
    try:
        pointer = unquote(value, errors="strict")
    except UnicodeDecodeError:
        return False
    if re.search(r"~(?![01])", pointer) or re.search(r"%(?![0-9a-fA-F]{2})", value):
        return False
    resolved = ""
    for token in pointer[2:].split("/"):
        resolved = _pointer(resolved, token.replace("~1", "/").replace("~0", "~"))
    return resolved in positions


def _node_problems(
    where: str,
    schema: Mapping[str, JsonValue],
    positions: Mapping[str, Mapping[str, JsonValue] | bool],
) -> Iterator[Problem]:
    for keyword in schema:
        if keyword in _FORBIDDEN_REFS or (keyword == "$id" and where):
            yield Problem(_pointer(where, keyword), "ref", f"{keyword} is not allowed here")
    if "$ref" in schema and not _valid_ref(schema["$ref"], positions):
        yield Problem(
            _pointer(where, "$ref"), "ref", "reference must name a schema within root $defs"
        )
    yield from _regex_problems(where, schema)


def _regex_problems(where: str, schema: Mapping[str, JsonValue]) -> Iterator[Problem]:
    patterns = []
    pattern = schema.get("pattern")
    if isinstance(pattern, str):
        patterns.append((_pointer(where, "pattern"), pattern))
    properties = schema.get("patternProperties")
    if isinstance(properties, dict):
        patterns.extend(
            (_pointer(_pointer(where, "patternProperties"), key), key) for key in properties
        )
    for pointer, pattern in patterns:
        try:
            compile_regex(pattern)
        except ValueError as error:
            yield Problem(pointer, "regex", str(error))


def _root_problems(document: Mapping[str, JsonValue]) -> Iterator[Problem]:
    if document.get("$schema") != DRAFT_2020_12:
        yield Problem("/$schema", "dialect", f"expected {DRAFT_2020_12}")
    if document.get("type") != "object":
        yield Problem("/type", "root_type", "root type must be object")
    for keyword in ("additionalProperties", "unevaluatedProperties"):
        if keyword in document:
            yield Problem("/" + keyword, "closed", "only the composed schema may close the root")
    properties = document.get("properties")
    if isinstance(properties, dict):
        for name in properties:
            if re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name) is None:
                yield Problem(
                    _pointer("/properties", name), "field_name", "invalid metadata field name"
                )


def _metaschema_problems(document: Mapping[str, JsonValue]) -> Iterator[Problem]:
    try:
        HuronValidator.check_schema(document)
    except SchemaError:
        metaschema = HuronValidator(
            HuronValidator.META_SCHEMA, format_checker=HuronValidator.FORMAT_CHECKER
        )
        for error in metaschema.iter_errors(document):
            where = ""
            for token in error.absolute_path:
                where = _pointer(where, token)
            yield Problem(where, "metaschema", error.message)


def check_schema_document(document: Mapping[str, JsonValue]) -> None:
    """Check every document-level publication rule without following references.

    Only Draft 2020-12 schema positions are walked. Annotation and literal values
    remain data, even when their keys resemble schema keywords.

    Args:
        document: The metadata schema part to publish.

    Raises:
        SchemaDocumentError: If any publication rule is violated.
    """
    document = dict(document)
    problems = list(_root_problems(document))
    problems.extend(_metaschema_problems(document))
    positions = dict(_schema_nodes(document))
    for where, schema in positions.items():
        if not isinstance(schema, bool):
            problems.extend(_node_problems(where, schema, positions))
    if problems:
        raise SchemaDocumentError(problems)
