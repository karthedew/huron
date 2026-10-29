"""Validation with RE2 patterns and the allowed schema subset."""

import time

import pytest

from huron.schema.loader import DOCUMENTS, load_document
from huron.schema.validator import Problem, SchemaInvalid, Validator, check_schema_document

ALLOWED = {
    "type": "object",
    "title": "T",
    "description": "D",
    "additionalProperties": False,
    "required": ["a"],
    "properties": {
        "a": {"type": "string", "minLength": 1, "maxLength": 9, "pattern": "^[a-z]+$"},
        "b": {"type": "integer", "minimum": 0, "maximum": 9, "default": 1},
        "c": {"type": "number", "enum": [1.5, 2.5]},
        "d": {"type": "boolean", "const": True},
        "e": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "maxItems": 3,
            "uniqueItems": True,
        },
        "f": {
            "type": "object",
            "properties": {"g": {"type": "string", "format": "date"}},
            "required": ["g"],
            "additionalProperties": {"type": "string"},
        },
        "h": {"type": "string", "format": "uri"},
    },
}


def test_every_shipped_document_is_a_valid_json_schema() -> None:
    from jsonschema import Draft202012Validator

    for name in DOCUMENTS:
        Draft202012Validator.check_schema(load_document(name))


def test_the_base_schema_is_in_the_allowed_subset() -> None:
    check_schema_document(load_document("huron-base-v1"))


def test_allowed_keywords_are_accepted() -> None:
    assert check_schema_document(ALLOWED) is ALLOWED


@pytest.mark.parametrize(
    "document",
    [
        {"type": "array"},
        {"type": "object", "$ref": "#/x"},
        {"type": "object", "properties": {"a": {"type": "string", "if": {}}}},
        {"type": "object", "patternProperties": {}},
        {"type": "object", "properties": {"a": {"type": "string", "format": "ipv4"}}},
        {"type": "object", "properties": {"a": {"type": "null"}}},
        {"type": "object", "properties": {"a": {"minLength": 1}}},
        {"type": "object", "properties": {"a": {"type": "string", "pattern": "(?<=x)y"}}},
    ],
)
def test_disallowed_documents_are_refused(document: dict[str, object]) -> None:
    with pytest.raises(SchemaInvalid) as raised:
        check_schema_document(document)
    assert raised.value.context["problems"]


def test_patterns_inside_enum_values_are_not_compiled() -> None:
    document = {"type": "object", "properties": {"a": {"type": "string", "enum": ["("]}}}
    assert check_schema_document(document) == document


def test_validation_reports_every_problem_sorted_by_path() -> None:
    problems = Validator.for_document(ALLOWED).validate(
        {"a": "UP", "b": 10, "f": {"g": "not-a-date", "x": 1}, "h": "not a uri", "z": 1}
    )
    paths = [(problem.path, problem.rule) for problem in problems]
    assert ("/a", "pattern") in paths
    assert ("/b", "maximum") in paths
    assert ("/f/g", "format") in paths
    assert ("/f/x", "type") in paths
    assert ("/", "additionalProperties") in paths
    assert paths == sorted(paths)
    assert Problem("/a", "m", "r").as_dict() == {"path": "/a", "message": "m", "rule": "r"}


def test_valid_instances_have_no_problems() -> None:
    assert Validator(ALLOWED).validate({"a": "ok", "f": {"g": "2026-10-29"}}) == []


def test_re2_patterns_run_in_linear_time() -> None:
    validator = Validator({"type": "string", "pattern": "^(a+)+$"})
    started = time.monotonic()
    assert validator.validate("a" * 5000 + "b")
    assert time.monotonic() - started < 1.0
    assert Validator({"type": "string", "pattern": "^a"}).validate(5) == [
        Problem("/", "5 is not of type 'string'", "type")
    ]


def test_an_invalid_pattern_in_a_raw_validator_is_a_problem() -> None:
    problems = Validator({"type": "string", "pattern": "(?<=x)y"}).validate("y")
    assert problems[0].rule == "pattern"


def test_loader_returns_fresh_copies_and_rejects_unknown_names() -> None:
    first = load_document("huron-base-v1")
    first["title"] = "changed"
    assert load_document("huron-base-v1")["title"] != "changed"
    with pytest.raises(KeyError):
        load_document("nope")
