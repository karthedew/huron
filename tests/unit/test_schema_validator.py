"""Shared validators bound regex work and keep references offline at every depth."""

from __future__ import annotations

import socket
import subprocess
import sys
from typing import Any

import pytest
from jsonschema import SchemaError, ValidationError
from referencing.exceptions import Unresolvable

from huron.schema import validator
from huron.schema._validator import HuronValidator, build, compile_regex

pytestmark = pytest.mark.unit
DIALECT = "https://json-schema.org/draft/2020-12/schema"


@pytest.mark.parametrize(
    "schema,instance",
    [
        ({"pattern": "^(a|aa)+$"}, "value"),
        ({"patternProperties": {"^(a|aa)+$": False}}, "key"),
        ({"propertyNames": {"pattern": "^(a|aa)+$"}}, "key"),
        ({"patternProperties": {"^(a|aa)+$": True}, "additionalProperties": False}, "key"),
        ({"patternProperties": {"^(a|aa)+$": True}, "unevaluatedProperties": False}, "key"),
        ({"allOf": [{"$schema": DIALECT, "pattern": "^(a|aa)+$"}]}, "value"),
        (
            {
                "$defs": {"value": {"$schema": DIALECT, "pattern": "^(a|aa)+$"}},
                "$ref": "#/$defs/value",
            },
            "value",
        ),
    ],
)
def test_re2_matches_a_pathological_pattern_in_linear_time(
    schema: dict[str, Any], instance: str
) -> None:
    """Every matching path finishes on a million-character near miss within two seconds."""
    code = f"""
from time import perf_counter
from huron.schema._validator import build
schema = {schema!r}
value = 'a' * 1_000_000 + 'b'
instance = value if {instance!r} == 'value' else {{value: 1}}
start = perf_counter()
list(build(schema).iter_errors(instance))
assert perf_counter() - start < 2
"""
    subprocess.run([sys.executable, "-c", code], check=True, timeout=4, capture_output=True)


@pytest.mark.parametrize("pattern", [r"(a)\1", "(?=a)b", "(?<=a)b", "a" * 1025, "["])
def test_compile_regex_refuses_backreferences_lookaround_and_length_silently(
    pattern: str, capfd: pytest.CaptureFixture[str]
) -> None:
    """Invalid or unsupported patterns raise without RE2 logging to stderr."""
    with pytest.raises(ValueError):
        compile_regex(pattern)
    assert capfd.readouterr().err == ""


@pytest.mark.parametrize("pattern", ["", "a" * 1024, "^(a|aa)+$", r"\p{L}+"])
def test_supported_patterns_compile(pattern: str) -> None:
    """Empty, boundary-length, ambiguous, and Unicode patterns compile under RE2."""
    assert compile_regex(pattern) is None


def test_packaged_validators_are_huron_validators() -> None:
    """The public cached factory returns the extended validator class."""
    built = validator("snapshot-provenance-v1.json")
    assert isinstance(built, HuronValidator)
    assert built is validator("snapshot-provenance-v1.json")


@pytest.mark.parametrize("keyword", ["$ref", "$dynamicRef"])
def test_a_remote_ref_fails_closed(keyword: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Unregistered HTTPS references fail without contacting a network socket."""

    def refuse_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("validation attempted network access")

    monkeypatch.setattr(socket, "getaddrinfo", refuse_network)
    monkeypatch.setattr(socket.socket, "connect", refuse_network)
    built = build({"allOf": [{"$schema": DIALECT, keyword: "https://example.com/schema.json"}]})
    with pytest.raises(Unresolvable):
        built.validate({})


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "nonsense"},
        {"pattern": "(?=a)b"},
        {"patternProperties": {r"(a)\1": {}}},
        {"properties": {"x": {"pattern": "a" * 1025}}},
    ],
)
def test_build_checks_schema_and_regex_formats(schema: dict[str, Any]) -> None:
    """Malformed schemas and patterns are refused before any metadata is examined."""
    with pytest.raises(SchemaError):
        build(schema)


def test_annotation_data_is_not_interpreted_as_schema() -> None:
    """Literal data may contain unsupported-looking regexes without executing them."""
    literal = {"pattern": "(?=a)b", "$schema": "https://example.com/not-a-schema"}
    build({"const": literal, "default": literal, "examples": [literal]}).validate(literal)


@pytest.mark.parametrize("instance", ["ok", 12, None, []])
def test_object_keywords_ignore_nonobjects(instance: Any) -> None:
    """Property matching and closure only constrain object instances."""
    build(
        {
            "patternProperties": {"x": False},
            "additionalProperties": False,
            "unevaluatedProperties": False,
        }
    ).validate(instance)


def test_pattern_validation_preserves_error_message_and_path() -> None:
    """Nested pattern failures retain the standard message and both descend paths."""
    built = build({"patternProperties": {"^x": {"pattern": "ok"}}})
    error = next(built.iter_errors({"xyz": "bad"}))
    assert error.message == "'bad' does not match 'ok'"
    assert list(error.path) == ["xyz"]
    assert list(error.schema_path) == ["patternProperties", "^x", "pattern"]
    built.validate({"xyz": "looks ok", "other": "bad"})
    built.validate({"xyz": 12})


@pytest.mark.parametrize(
    "schema,instance,message,path",
    [
        (
            {"additionalProperties": False},
            {"a": 1},
            "Additional properties are not allowed ('a' was unexpected)",
            [],
        ),
        (
            {"patternProperties": {"x": True}, "additionalProperties": False},
            {"a": 1, "b": 2},
            "'a', 'b' do not match any of the regexes: 'x'",
            [],
        ),
        (
            {"patternProperties": {"x": True}, "additionalProperties": False},
            {"a": 1},
            "'a' does not match any of the regexes: 'x'",
            [],
        ),
        (
            {"additionalProperties": {"type": "integer"}},
            {"a": "bad"},
            "'bad' is not of type 'integer'",
            ["a"],
        ),
        (
            {"unevaluatedProperties": False},
            {"a": 1},
            "Unevaluated properties are not allowed ('a' was unexpected)",
            [],
        ),
        (
            {"unevaluatedProperties": {"type": "integer"}},
            {"a": "bad"},
            "Unevaluated properties are not valid under the given schema ('a' was unevaluated and invalid)",
            [],
        ),
    ],
)
def test_property_closure_preserves_errors(
    schema: dict[str, Any], instance: dict[str, Any], message: str, path: list[str]
) -> None:
    """Additional and unevaluated property failures preserve JSON Schema error contracts."""
    error = next(build(schema).iter_errors(instance))
    assert error.message == message
    assert list(error.path) == path


@pytest.mark.parametrize(
    "schema,instance",
    [
        (
            {
                "properties": {"x": True},
                "patternProperties": {"^y": True},
                "additionalProperties": False,
            },
            {"x": 1, "yz": 2},
        ),
        ({"additionalProperties": True}, {"x": 1}),
        ({"unevaluatedProperties": {"type": "integer"}}, {"x": 1}),
        ({"allOf": [True, {"properties": {"x": True}}], "unevaluatedProperties": False}, {"x": 1}),
        (
            {
                "anyOf": [{"required": ["missing"]}, {"patternProperties": {"^x": True}}],
                "unevaluatedProperties": False,
            },
            {"xyz": 1},
        ),
        (
            {
                "dependentSchemas": {"x": {"properties": {"x": True}}, "absent": False},
                "unevaluatedProperties": False,
            },
            {"x": 1},
        ),
        (
            {
                "if": {"required": ["x"], "properties": {"x": True}},
                "then": {"properties": {"y": True}},
                "else": False,
                "unevaluatedProperties": False,
            },
            {"x": 1, "y": 2},
        ),
        (
            {
                "if": {"required": ["x"]},
                "else": {"properties": {"y": True}},
                "unevaluatedProperties": False,
            },
            {"y": 2},
        ),
        ({"if": {"properties": {"x": True}}, "unevaluatedProperties": False}, {"x": 1}),
        ({"additionalProperties": {"type": "integer"}, "unevaluatedProperties": False}, {"x": 1}),
        (
            {
                "$defs": {"obj": {"properties": {"x": True}}},
                "$ref": "#/$defs/obj",
                "unevaluatedProperties": False,
            },
            {"x": 1},
        ),
        (
            {
                "$defs": {"obj": {"properties": {"x": True}}},
                "$dynamicRef": "#/$defs/obj",
                "unevaluatedProperties": False,
            },
            {"x": 1},
        ),
    ],
)
def test_property_annotations_survive_applicators_and_local_references(
    schema: dict[str, Any], instance: dict[str, Any]
) -> None:
    """Closure respects successful branch, dependency, and reference annotations."""
    build(schema).validate(instance)


def test_formats_are_enforced() -> None:
    """Date-time and regex formats enforce their installed checkers on values."""
    with pytest.raises(ValidationError):
        build({"format": "date-time"}).validate("yesterday")
    built = build({"format": "regex"})
    built.validate(12)
    with pytest.raises(ValidationError):
        built.validate("(?=a)b")
