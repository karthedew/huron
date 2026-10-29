"""JSON Schema 2020-12 validation with RE2 patterns and a fixed set of formats."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import re2
from jsonschema import Draft202012Validator, FormatChecker, ValidationError, validators

from huron.pkg.errors import HuronError, register
from huron.schema.loader import load_document

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping

__all__ = [
    "FORMATS",
    "Problem",
    "SchemaInvalid",
    "Validator",
    "check_schema_document",
    "problems_context",
]

FORMATS = ("date", "date-time", "email", "uri")

SCHEMA_INVALID = register("SCHEMA_INVALID", 422, "Schema invalid")


@dataclass(frozen=True, slots=True)
class Problem:
    """One validation failure: where (JSON pointer), what, and which keyword failed."""

    path: str
    message: str
    rule: str

    def as_dict(self) -> dict[str, str]:
        """Render for problem documents and CLI output."""
        return {"path": self.path, "message": self.message, "rule": self.rule}


class SchemaInvalid(HuronError):
    """A schema document is not in the allowed subset of JSON Schema."""

    error_code = SCHEMA_INVALID


class Validator:
    """Validates instances against one schema document."""

    def __init__(self, document: Mapping[str, Any]) -> None:
        self._validator = _RE2_VALIDATOR(dict(document), format_checker=_FORMAT_CHECKER)

    @classmethod
    def for_document(cls, document: Mapping[str, Any]) -> Validator:
        """Build a validator for ``document``."""
        return cls(document)

    def validate(self, instance: Any) -> list[Problem]:
        """Return every problem with ``instance``, sorted by path; empty when it is valid."""
        found = [_problem(error) for error in self._validator.iter_errors(instance)]
        return sorted(found, key=lambda problem: (problem.path, problem.rule, problem.message))


def check_schema_document(document: Any) -> dict[str, Any]:
    """Return ``document`` when it is an allowed metadata schema; raises :class:`SchemaInvalid`."""
    problems = Validator(load_document("schema-document-v1")).validate(document)
    if not problems:
        problems = list(_pattern_problems(document, ""))
    if problems:
        raise SchemaInvalid("schema document is not allowed", problems_context(problems))
    result: dict[str, Any] = document
    return result


def problems_context(problems: Iterable[Problem]) -> dict[str, Any]:
    """The ``context`` of an error that carries validation problems."""
    return {"problems": [problem.as_dict() for problem in problems]}


def _re2_pattern(
    validator: Any, pattern: str, instance: Any, schema: Mapping[str, Any]
) -> Iterator[ValidationError]:
    if not validator.is_type(instance, "string"):
        return
    try:
        matched = re2.compile(pattern).search(instance)
    except re2.error:
        yield ValidationError(f"pattern {pattern!r} is not valid RE2")
        return
    if matched is None:
        yield ValidationError(f"{instance!r} does not match {pattern!r}")


def _problem(error: ValidationError) -> Problem:
    path = "".join(f"/{part}" for part in error.absolute_path) or "/"
    return Problem(path, error.message, str(error.validator))


def _pattern_problems(node: Any, path: str) -> Iterator[Problem]:
    if isinstance(node, dict):
        pattern = node.get("pattern")
        if isinstance(pattern, str):
            try:
                re2.compile(pattern)
            except re2.error:
                yield Problem(path + "/pattern", f"{pattern!r} is not valid RE2", "pattern")
        for key, value in node.items():
            if key not in {"enum", "const", "default"}:
                yield from _pattern_problems(value, f"{path}/{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _pattern_problems(value, f"{path}/{index}")


_FORMAT_CHECKER = FormatChecker(FORMATS)
_RE2_VALIDATOR = validators.extend(Draft202012Validator, {"pattern": _re2_pattern})  # type: ignore[no-untyped-call]
