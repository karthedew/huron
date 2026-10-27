"""Owned metadata changes and safe publication of JSON Schema documents."""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING, Final, Literal, cast
from urllib.parse import unquote

from jsonschema import SchemaError

from huron.schema._compose import _schema_nodes
from huron.schema._compose import flatten as _flatten
from huron.schema._compose import pointer as _pointer
from huron.schema._validator import HuronValidator, build, compile_regex
from huron.schema.catalog_config import Problem, SchemaRef

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


_FORBIDDEN_REFS: Final = frozenset({"$dynamicRef", "$dynamicAnchor", "$anchor"})


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


class CompositionError(SchemaDocumentError):
    """A nonempty collection of failures composing exact metadata schema parts."""


def compose(
    base: Mapping[str, JsonValue],
    extension: tuple[str, Mapping[str, JsonValue]] | None,
    *,
    schema: SchemaRef,
    base_version: int,
) -> ComposedSchema:
    """Intersect an org base and its selected extension into a closed document.

    Args:
        base: The open organization base schema.
        extension: The selected extension's name and open schema, or no extension.
        schema: The exact selected schema reference.
        base_version: The exact organization base version.

    Returns:
        An owned, self-contained schema with exact version provenance.

    Raises:
        CompositionError: If parts, provenance or their composition are invalid.
    """
    try:
        _check_selection(extension, schema, base_version)
        parts = [(BASE_SCHEMA_NAME, base)] + ([extension] if extension else [])
        for _, document in parts:
            check_schema_document(document)
        document = _flatten(parts)
        document.update(
            {
                "$schema": DRAFT_2020_12,
                "$id": f"urn:huron:metadata-schema:{schema.name}:{schema.version}",
                "title": schema.name,
                "type": "object",
                "unevaluatedProperties": False,
                "x-huron": {
                    "schema": {"name": schema.name, "version": schema.version},
                    "base_version": base_version,
                },
            }
        )
        return ComposedSchema.from_document(document)
    except SchemaDocumentError as error:
        raise CompositionError(error.problems) from error
    except (ValueError, SchemaError) as error:
        raise CompositionError([Problem("", "composition", str(error))]) from error


def _check_selection(
    extension: tuple[str, Mapping[str, JsonValue]] | None, schema: SchemaRef, base_version: int
) -> None:
    base_ref = SchemaRef(BASE_SCHEMA_NAME, base_version)
    if extension is None:
        if schema != base_ref:
            raise ValueError("a base-only composition must select its exact org version")
    elif extension[0] != schema.name or schema.name == BASE_SCHEMA_NAME:
        raise ValueError("extension name must match the selected non-org schema")


def _check_composed(document: Mapping[str, JsonValue]) -> None:
    provenance = document.get("x-huron")
    if not isinstance(provenance, dict) or set(provenance) != {"schema", "base_version"}:
        raise ValueError("x-huron must contain schema and base_version")
    reference = provenance["schema"]
    if not isinstance(reference, dict) or set(reference) != {"name", "version"}:
        raise ValueError("x-huron schema must contain name and version")
    if not isinstance(reference["name"], str):
        raise ValueError("schema name must be a string")
    selected = SchemaRef(reference["name"], cast("int", reference["version"]))
    base = SchemaRef(BASE_SCHEMA_NAME, cast("int", provenance["base_version"]))
    if selected.name == BASE_SCHEMA_NAME and selected != base:
        raise ValueError("org schema and base versions must match")
    if document.get("unevaluatedProperties") is not False:
        raise ValueError("composed schema must close unevaluated properties")
    open_document = dict(document)
    del open_document["unevaluatedProperties"]
    check_schema_document(open_document)


@dataclass(frozen=True, slots=True, init=False)
class FieldSpec:
    """A descriptive field and independent snapshots of its schema annotations."""

    name: str
    required: bool
    _schema: JsonValue

    def __init__(self, name: str, required: bool, schema: JsonValue) -> None:
        """Own a field's complete subschema, including boolean schemas.

        Args:
            name: The metadata member name.
            required: Whether the root requires this member.
            schema: The composed member subschema.
        """
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "required", required)
        object.__setattr__(self, "_schema", deepcopy(schema))

    @property
    def schema(self) -> JsonValue:
        """Return an independent copy of the complete member subschema.

        Returns:
            The member schema without resolving references or changing constraints.
        """
        return deepcopy(self._schema)

    def _annotation(self, name: str) -> JsonValue:
        return self._schema.get(name) if isinstance(self._schema, dict) else None

    @property
    def title(self) -> str | None:
        """Return the field's own display title.

        Returns:
            The declared title, or no title.
        """
        return cast("str | None", self._annotation("title"))

    @property
    def description(self) -> str | None:
        """Return the field's own description.

        Returns:
            The declared description, or no description.
        """
        return cast("str | None", self._annotation("description"))

    @property
    def examples(self) -> tuple[JsonValue, ...]:
        """Return independently owned examples.

        Returns:
            The declared examples in their original order.
        """
        return tuple(deepcopy(cast("list[JsonValue]", self._annotation("examples") or [])))


@dataclass(frozen=True, slots=True, init=False)
class ComposedSchema:
    """An owned closed schema with validated exact version provenance."""

    _document: dict[str, JsonValue]

    def __init__(self, document: Mapping[str, JsonValue]) -> None:
        """Validate and snapshot a composed document.

        Args:
            document: A self-contained, closed schema carrying x-huron provenance.
        """
        owned = deepcopy(dict(document))
        _check_composed(owned)
        object.__setattr__(self, "_document", owned)

    @property
    def document(self) -> dict[str, JsonValue]:
        """Return a separate document that callers may safely serialize or edit.

        Returns:
            An independent copy of the composed schema.
        """
        return deepcopy(self._document)

    @classmethod
    def from_document(cls, document: Mapping[str, JsonValue]) -> ComposedSchema:
        """Validate a served schema before using its fields or validator.

        Invalid provenance or schema raises ``ValueError``.

        Args:
            document: The served closed schema and its exact version provenance.

        Returns:
            An independently owned schema.
        """
        return cls(document)

    def fields(self) -> tuple[FieldSpec, ...]:
        """List declared fields in required order followed by sorted optional names.

        Returns:
            Owned fields with their own annotations and intersected constraints.
        """
        properties = cast("dict[str, JsonValue]", self._document.get("properties", {}))
        required = cast("list[str]", self._document.get("required", []))
        names = [name for name in required if name in properties]
        names.extend(sorted(properties.keys() - set(names)))
        return tuple(FieldSpec(name, name in required, properties[name]) for name in names)

    def validator(self) -> MetadataValidator:
        """Build a synchronous validator from this immutable schema snapshot.

        Returns:
            A validator safe to use concurrently.
        """
        return MetadataValidator(self._document)


class MetadataValidator:
    """Synchronous RE2 validation with stable pointers and partial-object support."""

    def __init__(self, document: Mapping[str, JsonValue]) -> None:
        """Own and check the schema used by each independent validation call.

        Args:
            document: A safe, self-contained composed schema.
        """
        self._document = ComposedSchema(document).document
        self._validator = build(self._document)

    def problems(self, metadata: object, *, partial: bool = False) -> tuple[Problem, ...]:
        """Collect stable instance errors, optionally tolerating missing root members.

        Args:
            metadata: The JSON metadata object to validate.
            partial: Omit root required errors while retaining nested requirements.

        Returns:
            All problems sorted by pointer, rule and message.
        """
        if not isinstance(metadata, dict):
            return (Problem("", "type", "metadata must be an object"),)
        failures = []
        for error in self._validator.evolve().iter_errors(metadata):
            where = ""
            for token in error.absolute_path:
                where = _pointer(where, token)
            if not (partial and where == "" and error.validator == "required"):
                failures.append(Problem(where, str(error.validator), error.message))
        return tuple(sorted(failures, key=lambda p: (p.where, p.rule, p.message)))
