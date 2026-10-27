"""Exact metadata composition preserves constraints, safe references and owned values."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import FrozenInstanceError
from typing import Any

import pytest
import rfc8785
from hypothesis import given
from hypothesis import strategies as st

from huron.schema import load_schema
from huron.schema._validator import HuronValidator
from huron.schema.catalog_config import Problem, SchemaRef
from huron.schema.metadata import (
    DRAFT_2020_12,
    ComposedSchema,
    CompositionError,
    FieldSpec,
    MetadataValidator,
    check_schema_document,
    compose,
)

pytestmark = pytest.mark.unit

GOLDEN = {
    "$schema": DRAFT_2020_12,
    "$id": "urn:huron:metadata-schema:heliophysics:1",
    "title": "heliophysics",
    "type": "object",
    "properties": {
        "title": {
            "description": "Short human title",
            "allOf": [
                {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 200,
                    "description": "Short human title",
                },
                {"maxLength": 80},
            ],
        },
        "description": {"type": "string", "maxLength": 10000},
        "pi": {"type": "string", "minLength": 1, "description": "Principal investigator"},
        "organization": {"type": "string", "minLength": 1},
        "contact": {"$ref": "#/$defs/org.email"},
        "keywords": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "uniqueItems": True,
        },
        "mission": {"type": "string", "description": "Spacecraft mission"},
        "instrument": {"type": "string"},
        "campaign": {
            "type": "string",
            "description": "Encounter, free text",
            "examples": ["Enc 17"],
        },
        "run_id": {"type": "string", "pattern": "^run[0-9]{3}$"},
        "start_time": {"$ref": "#/$defs/heliophysics.instant"},
        "perihelion": {"type": "integer", "minimum": 1},
    },
    "required": ["title", "pi", "contact", "run_id", "start_time"],
    "$defs": {
        "org.email": {"type": "string", "format": "email"},
        "heliophysics.instant": {"type": "string", "format": "date-time"},
    },
    "allOf": [
        {
            "if": {"properties": {"mission": {"const": "psp"}}, "required": ["mission"]},
            "then": {"required": ["perihelion"]},
        }
    ],
    "unevaluatedProperties": False,
    "x-huron": {"schema": {"name": "heliophysics", "version": 1}, "base_version": 1},
}
VALID = {
    "title": "Encounter 17 FIELDS",
    "pi": "K",
    "contact": "k@example.org",
    "mission": "psp",
    "instrument": "fields",
    "campaign": "Enc 17",
    "run_id": "run042",
    "start_time": "2026-10-23T00:00:00Z",
    "perihelion": 17,
}


def test_worked_example_composes_to_the_golden_document(
    metadata_extension_document: dict[str, Any],
) -> None:
    """Canonical bytes preserve the exact intersection and descriptive-only provenance."""
    base = load_schema("org-base-v1.json")
    check_schema_document(base)
    assert 2 <= len(rfc8785.dumps(base)) <= 262144
    result = compose(
        base,
        ("heliophysics", metadata_extension_document),
        schema=SchemaRef("heliophysics", 1),
        base_version=1,
    )
    assert rfc8785.dumps(result.document) == rfc8785.dumps(GOLDEN)
    assert (
        compose(base, None, schema=SchemaRef("org", 1), base_version=1)
        .validator()
        .problems(VALID | {"extra": 1})
    )


@pytest.mark.parametrize(
    "patch,removed,expected",
    [
        ({}, None, []),
        ({"colour": "red"}, None, [("", "unevaluatedProperties")]),
        ({"instrument": "epd"}, None, []),
        ({"mission": "solo", "instrument": "fields"}, None, []),
        ({"contact": "nope"}, None, [("/contact", "format")]),
        ({"start_time": "yesterday"}, None, [("/start_time", "format")]),
        ({"title": "a" * 81}, None, [("/title", "maxLength")]),
        ({}, "perihelion", [("", "required")]),
        ({"run_id": "r42"}, None, [("/run_id", "pattern")]),
    ],
)
def test_worked_example_outcomes(patch: dict[str, Any], removed: str | None, expected: Any) -> None:
    """Schema constraints hold without imposing retired placement vocabularies."""
    metadata = VALID | patch
    if removed:
        del metadata[removed]
    assert [(p.where, p.rule) for p in MetadataValidator(GOLDEN).problems(metadata)] == expected


@given(st.lists(st.sampled_from(["alpha", "beta", "gamma"]), unique=True), st.integers(1, 100))
def test_composition_is_deterministic_and_always_a_valid_schema(
    names: list[str], version: int
) -> None:
    """Property insertion order cannot change canonical composition bytes."""
    base = {
        "$schema": DRAFT_2020_12,
        "type": "object",
        "properties": {name: {"type": "integer"} for name in names},
    }
    first = compose(base, None, schema=SchemaRef("org", version), base_version=version)
    base["properties"] = dict(reversed(list(base["properties"].items())))
    second = compose(base, None, schema=SchemaRef("org", version), base_version=version)
    assert rfc8785.dumps(first.document) == rfc8785.dumps(second.document)
    HuronValidator.check_schema(first.document)


def test_refs_namespace_only_schema_positions(metadata_schema_document: dict[str, Any]) -> None:
    """Escaped, percent-encoded and nested references retain their own definition scopes."""
    literal = {"$ref": "#/$defs/a~1b~0c", "properties": {"bad": {"$anchor": "x"}}}
    base = metadata_schema_document | {
        "$defs": {
            "a/b~c": {
                "$defs": {"inner": {"type": "integer"}},
                "properties": {"x": {"$ref": "#/$defs/a~1b~0c/$defs/inner"}},
            }
        },
        "properties": {
            "base": {"$ref": "#/$defs/a%7E1b~0c"},
            "literal": {
                "const": literal,
                "default": literal,
                "examples": [literal],
                "x-note": literal,
            },
        },
    }
    extension = metadata_schema_document | {
        "$defs": {"a/b~c": {"type": "string"}},
        "properties": {"ext": {"$ref": "#/$defs/a~1b~0c"}},
    }
    result = compose(base, ("custom", extension), schema=SchemaRef("custom", 2), base_version=3)
    assert result.document["properties"]["literal"] == base["properties"]["literal"]
    assert result.validator().problems({"base": {"x": 3}, "ext": "yes", "literal": literal}) == ()
    assert {
        (p.where, p.rule) for p in result.validator().problems({"base": {"x": "no"}, "ext": 1})
    } == {("/base/x", "type"), ("/ext", "type")}


def test_root_applicators_and_nested_requirements(metadata_schema_document: dict[str, Any]) -> None:
    """Conditional members are allowed only when evaluated; partial keeps nested errors."""
    base = metadata_schema_document | {
        "properties": {
            "nested": {
                "type": "object",
                "required": ["x"],
                "properties": {"a/~": {"type": "integer"}},
            }
        },
        "required": ["nested"],
        "if": {"required": ["nested"]},
        "then": {"properties": {"conditional": {"enum": []}}, "required": ["conditional"]},
    }
    validator = compose(base, None, schema=SchemaRef("org", 1), base_version=1).validator()
    assert validator.problems({}, partial=True) == ()
    problems = validator.problems({"nested": {"a/~": False}, "conditional": 1}, partial=True)
    assert {(p.where, p.rule) for p in problems} >= {
        ("/nested", "required"),
        ("/nested/a~1~0", "type"),
        ("/conditional", "enum"),
    }
    assert problems == tuple(sorted(problems, key=lambda p: (p.where, p.rule, p.message)))
    assert [(p.where, p.rule) for p in validator.problems({"conditional": 1})] == [
        ("", "required"),
        ("", "unevaluatedProperties"),
    ]


@pytest.mark.parametrize("instance", [None, [], "x", 1, True])
def test_non_objects_have_one_type_problem(instance: object) -> None:
    """Non-object inputs cannot produce cascades of unrelated schema errors."""
    assert MetadataValidator(GOLDEN).problems(instance) == (
        Problem("", "type", "metadata must be an object"),
    )


def test_fields_and_documents_own_all_containers(metadata_schema_document: dict[str, Any]) -> None:
    """Required order, hoisted annotations and boolean fields survive caller mutations."""
    base = metadata_schema_document | {
        "required": ["z", "a"],
        "properties": {
            "z": {"title": "Base", "examples": [{"x": [1]}]},
            "a": True,
            "optional": False,
        },
    }
    extension = metadata_schema_document | {
        "required": ["a"],
        "properties": {"z": {"title": "New", "description": "Help"}},
    }
    result = compose(base, ("custom", extension), schema=SchemaRef("custom", 1), base_version=1)
    fields = result.fields()
    assert [(f.name, f.required) for f in fields] == [("z", True), ("a", True), ("optional", False)]
    assert (fields[0].title, fields[0].description) == ("New", "Help")
    assert fields[1].title is None and fields[1].examples == ()
    expected = result.document
    base.clear()
    extension.clear()
    result.document.clear()
    fields[0].schema.clear()
    fields[0].examples[0]["x"].append(2)
    assert result.document == expected
    assert fields[0].examples == ({"x": [1]},)
    with pytest.raises(FrozenInstanceError):
        fields[0].name = "other"
    with pytest.raises(FrozenInstanceError):
        result._document = {}
    direct = {"examples": [[1]]}
    field = FieldSpec("x", False, direct)
    direct.clear()
    assert field.examples == ([1],)


@pytest.mark.parametrize(
    "patch",
    [
        {"x-huron": None},
        {"x-huron": {}},
        {"x-huron": {"schema": {}, "base_version": 1}},
        {"x-huron": {"schema": {"name": 1, "version": 1}, "base_version": 1}},
        {"x-huron": {"schema": {"name": "org", "version": 2}, "base_version": 1}},
        {"x-huron": {"schema": {"name": "org", "version": True}, "base_version": 1}},
        {"unevaluatedProperties": True},
        {"minProperties": -1},
        {"properties": {"bad": {"$ref": "https://example.invalid"}}},
    ],
)
def test_served_documents_are_checked_before_use(patch: Any) -> None:
    """Malformed provenance, schema and unsafe references cannot enter served values."""
    with pytest.raises(ValueError):
        ComposedSchema.from_document(GOLDEN | patch)


def test_missing_provenance_is_refused() -> None:
    """An ordinary schema cannot impersonate a composed served document."""
    with pytest.raises(ValueError, match="x-huron"):
        ComposedSchema.from_document({"$schema": DRAFT_2020_12, "type": "object"})


@pytest.mark.parametrize(
    "extension,reference,version",
    [
        (None, SchemaRef("other", 1), 1),
        (None, SchemaRef("org", 2), 1),
        (None, SchemaRef("org", 1), True),
        (None, SchemaRef("org", 1), 1.0),
        (("other", {}), SchemaRef("custom", 1), 1),
        (("org", {}), SchemaRef("org", 1), 1),
    ],
)
def test_composition_refuses_inconsistent_provenance(
    metadata_schema_document: Any, extension: Any, reference: SchemaRef, version: Any
) -> None:
    """Base and extension identities must agree with the selected exact reference."""
    with pytest.raises(CompositionError) as caught:
        compose(metadata_schema_document, extension, schema=reference, base_version=version)
    assert caught.value.problems[0].rule == "composition"


def test_composition_refuses_unsafe_parts(metadata_schema_document: Any) -> None:
    """Publication failures keep their stable pointers in composition errors."""
    with pytest.raises(CompositionError) as caught:
        compose(
            metadata_schema_document | {"$ref": "#/$defs/missing"},
            None,
            schema=SchemaRef("org", 1),
            base_version=1,
        )
    assert caught.value.problems[0].rule == "ref"
    with pytest.raises(ValueError):
        CompositionError([])


def test_validator_is_owned_and_concurrent() -> None:
    """Shared validators keep resolver state isolated and ignore later document edits."""
    document = deepcopy(GOLDEN)
    validator = MetadataValidator(document)
    document.clear()
    inputs = [VALID, VALID | {"perihelion": True}, VALID | {"perihelion": 1.0}] * 10
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(validator.problems, inputs))
    assert (
        results == [(), (Problem("/perihelion", "type", "True is not of type 'integer'"),), ()] * 10
    )


@pytest.mark.parametrize(
    "choices,accepted", [(["fields", "sweap"], True), (["epd"], False), ([], False)]
)
def test_ordinary_enums_remain_field_constraints(
    metadata_schema_document: dict[str, Any], choices: list[str], accepted: bool
) -> None:
    """Enums narrow descriptive values and report refusals at the field pointer."""
    base = metadata_schema_document | {
        "properties": {"instrument": {"type": "string", "enum": choices}}
    }
    result = compose(base, None, schema=SchemaRef("org", 1), base_version=1)
    assert result.fields()[0].schema["enum"] == choices
    problems = result.validator().problems({"instrument": "fields"})
    assert [(p.where, p.rule) for p in problems] == ([] if accepted else [("/instrument", "enum")])


def test_partial_removes_only_root_required_errors(
    metadata_schema_document: dict[str, Any],
) -> None:
    """Conditional root requirements disappear in partial mode; nested requirements persist."""
    base = metadata_schema_document | {
        "properties": {"nested": {"type": "object", "required": ["child"]}},
        "required": ["outer"],
        "if": {"required": ["nested"]},
        "then": {"required": ["conditional"]},
    }
    validator = compose(base, None, schema=SchemaRef("org", 1), base_version=1).validator()
    full = validator.problems({"nested": {}})
    assert [(p.where, p.rule) for p in full] == [
        ("", "required"),
        ("", "required"),
        ("/nested", "required"),
    ]
    assert validator.problems({"nested": {}}, partial=True) == tuple(p for p in full if p.where)


def test_base_seed_validates_without_extension() -> None:
    """The packaged organization base alone validates its declared required metadata."""
    result = compose(
        load_schema("org-base-v1.json"), None, schema=SchemaRef("org", 4), base_version=4
    )
    assert (
        result.validator().problems({"title": "Observation", "pi": "K", "contact": "k@example.org"})
        == ()
    )
    assert result.document["x-huron"] == {
        "schema": {"name": "org", "version": 4},
        "base_version": 4,
    }
