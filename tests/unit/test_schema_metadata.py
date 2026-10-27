"""Metadata diffs own their values and schema publication rejects unsafe keywords."""

from dataclasses import FrozenInstanceError
from types import MappingProxyType
from typing import Any

import pytest

from huron.schema.catalog_config import Problem
from huron.schema.metadata import (
    BASE_SCHEMA_NAME,
    DRAFT_2020_12,
    Absent,
    FieldChange,
    SchemaDocumentError,
    check_schema_document,
    field_changes,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "before,after,expected",
    [
        ({}, {"x": None}, [{"pointer": "/x", "new": None}]),
        ({"x": None}, {}, [{"pointer": "/x", "old": None}]),
        ({"x": 1}, {"x": 2}, [{"pointer": "/x", "old": 1, "new": 2}]),
        ({"x": {"y": 1}}, {"x": {"y": 2}}, [{"pointer": "/x/y", "old": 1, "new": 2}]),
        ({"x": {}}, {"x": [1]}, [{"pointer": "/x", "old": {}, "new": [1]}]),
        ({"x": [1]}, {"x": [2]}, [{"pointer": "/x", "old": [1], "new": [2]}]),
        ({"x": True}, {"x": 1}, [{"pointer": "/x", "old": True, "new": 1}]),
        ({"x": [True]}, {"x": [1]}, [{"pointer": "/x", "old": [True], "new": [1]}]),
        (
            {"x": [{"y": False}]},
            {"x": [{"y": 0}]},
            [{"pointer": "/x", "old": [{"y": False}], "new": [{"y": 0}]}],
        ),
        ({"x": 1}, {"x": 1.0}, []),
        ({"x": [{"y": 1}]}, {"x": [{"y": 1.0}]}, []),
        ({"x": [1]}, {"x": [1, 2]}, [{"pointer": "/x", "old": [1], "new": [1, 2]}]),
        (
            {"x": [{"a": 1}]},
            {"x": [{"b": 1}]},
            [{"pointer": "/x", "old": [{"a": 1}], "new": [{"b": 1}]}],
        ),
        ({}, {}, []),
        ({"x": {"y": [None, "a", False]}}, {"x": {"y": [None, "a", False]}}, []),
    ],
)
def test_field_changes_compare_json_types_and_values(
    before: Any, after: Any, expected: Any
) -> None:
    """Objects recurse, arrays stay whole, and bool remains distinct from numbers."""
    assert [change.as_json() for change in field_changes(before, after)] == expected


def test_escaped_pointers_sort_by_code_point() -> None:
    """Sorting uses escaped pointers and accepts read-only input mappings."""
    changes = field_changes(MappingProxyType({}), {"~": 1, "/": 2, "z": {"a": 3}, "": 4})
    assert [change.pointer for change in changes] == ["/", "/z", "/~0", "/~1"]
    assert field_changes({"a/b": {"~": 1}}, {"a/b": {"~": 2}})[0].pointer == "/a~1b/~0"


def test_changes_own_inputs_and_returned_values() -> None:
    """Caller mutations cannot alter a recorded change or its future serialization."""
    before = {"x": [1]}
    after = {"x": {"y": [2]}}
    change = field_changes(before, after)[0]
    before["x"].append(9)
    after["x"]["y"].append(9)
    old, new, encoded = change.old, change.new, change.as_json()
    assert isinstance(old, list) and isinstance(new, dict)
    old.clear()
    new.clear()
    encoded.clear()
    assert change.as_json() == {"pointer": "/x", "old": [1], "new": {"y": [2]}}
    with pytest.raises(FrozenInstanceError):
        change.pointer = "/other"


def test_absence_is_not_null() -> None:
    """Both-absent changes fail while either absent side is omitted from JSON."""
    with pytest.raises(ValueError, match="present value"):
        FieldChange("/x")
    assert FieldChange("/x", new=None).old is Absent.ABSENT
    assert FieldChange("/x", old=None).new is Absent.ABSENT
    assert FieldChange("/x", new=None).as_json() == {"pointer": "/x", "new": None}
    assert FieldChange("/x", old=None).as_json() == {"pointer": "/x", "old": None}


def test_schema_error_owns_and_sorts_problems() -> None:
    """Failures are nonempty and sorted by pointer, rule, then message."""
    with pytest.raises(ValueError, match="at least one"):
        SchemaDocumentError([])
    problems = [
        Problem("/b", "ref", "b"),
        Problem("/a", "regex", "z"),
        Problem("/a", "closed", "b"),
        Problem("/a", "closed", "a"),
    ]
    error = SchemaDocumentError(iter(problems))
    problems.clear()
    assert error.problems == (
        Problem("/a", "closed", "a"),
        Problem("/a", "closed", "b"),
        Problem("/a", "regex", "z"),
        Problem("/b", "ref", "b"),
    )
    assert "/b: b" in str(error)


@pytest.mark.parametrize(
    "patch,where,rule",
    [
        ({"$schema": "other"}, "/$schema", "dialect"),
        ({"type": "array"}, "/type", "root_type"),
        ({"minProperties": -1}, "/minProperties", "metaschema"),
        ({"$ref": "#/properties/x"}, "/$ref", "ref"),
        ({"$ref": "other.json#/x"}, "/$ref", "ref"),
        ({"$ref": "#/$defs/missing"}, "/$ref", "ref"),
        ({"$ref": 1}, "/$ref", "ref"),
        ({"$anchor": "a"}, "/$anchor", "ref"),
        ({"$dynamicAnchor": "a"}, "/$dynamicAnchor", "ref"),
        ({"$dynamicRef": "#a"}, "/$dynamicRef", "ref"),
        ({"properties": {"x": {"$id": "urn:nested"}}}, "/properties/x/$id", "ref"),
        ({"properties": {"x": {"pattern": "(?=a)"}}}, "/properties/x/pattern", "regex"),
        ({"patternProperties": {"(?=a)/~": True}}, "/patternProperties/(?=a)~1~0", "regex"),
        ({"additionalProperties": True}, "/additionalProperties", "closed"),
        ({"unevaluatedProperties": False}, "/unevaluatedProperties", "closed"),
        ({"properties": {"A/~": {}}}, "/properties/A~1~0", "field_name"),
        ({"properties": {"x" * 65: {}}}, "/properties/" + "x" * 65, "field_name"),
    ],
)
def test_publication_rules_report_document_pointers(
    metadata_schema_document: dict[str, Any], patch: dict[str, Any], where: str, rule: str
) -> None:
    """Each publication refusal retains its stable document location and rule."""
    with pytest.raises(SchemaDocumentError) as caught:
        check_schema_document(metadata_schema_document | patch)
    assert (where, rule) in [(p.where, p.rule) for p in caught.value.problems]


@pytest.mark.parametrize("keyword", ["const", "enum", "default", "examples", "x-annotation"])
def test_schema_shaped_literal_data_is_not_walked(
    metadata_schema_document: dict[str, Any], keyword: str
) -> None:
    """Literal payloads may contain refs, anchors, IDs and unsupported-looking patterns."""
    literal = {
        "pattern": "(?=a)",
        "$ref": "other.json",
        "$anchor": "a",
        "$id": "nested",
        "properties": {"Invalid": {"$dynamicRef": "#bad"}},
    }
    metadata_schema_document[keyword] = [literal] if keyword in {"enum", "examples"} else literal
    assert check_schema_document(metadata_schema_document) is None


@pytest.mark.parametrize(
    "keyword", ["properties", "patternProperties", "$defs", "dependentSchemas"]
)
def test_map_applicators_are_walked(metadata_schema_document: dict[str, Any], keyword: str) -> None:
    """Every schema-map applicator checks its children without inspecting names as schemas."""
    metadata_schema_document[keyword] = {"x": {"$anchor": "a"}, "safe": False}
    with pytest.raises(SchemaDocumentError) as caught:
        check_schema_document(metadata_schema_document)
    assert [(p.where, p.rule) for p in caught.value.problems] == [(f"/{keyword}/x/$anchor", "ref")]


@pytest.mark.parametrize("keyword", ["allOf", "anyOf", "oneOf", "prefixItems"])
def test_list_applicators_are_walked(
    metadata_schema_document: dict[str, Any], keyword: str
) -> None:
    """Each schema-list applicator checks object children and accepts boolean children."""
    metadata_schema_document[keyword] = [True, {"$anchor": "a"}, False]
    with pytest.raises(SchemaDocumentError) as caught:
        check_schema_document(metadata_schema_document)
    assert [(p.where, p.rule) for p in caught.value.problems] == [(f"/{keyword}/1/$anchor", "ref")]


@pytest.mark.parametrize(
    "keyword",
    [
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
    ],
)
def test_single_schema_applicators_are_walked(
    metadata_schema_document: dict[str, Any], keyword: str
) -> None:
    """Single-schema applicators recurse beneath property schemas, where closure is legal."""
    metadata_schema_document["properties"] = {"x": {keyword: {"$anchor": "a"}}}
    with pytest.raises(SchemaDocumentError) as caught:
        check_schema_document(metadata_schema_document)
    assert [(p.where, p.rule) for p in caught.value.problems] == [
        (f"/properties/x/{keyword}/$anchor", "ref")
    ]
    metadata_schema_document["properties"] = {"x": {keyword: False}}
    check_schema_document(metadata_schema_document)


def test_all_violations_are_aggregated(metadata_schema_document: dict[str, Any]) -> None:
    """Multiple metaschema errors and independent publication rules survive one refusal."""
    metadata_schema_document.update(
        {
            "$schema": "wrong",
            "type": "array",
            "minProperties": -1,
            "maxProperties": -2,
            "$defs": {"a": {}},
            "$ref": "#/$defs/a/missing",
            "additionalProperties": False,
            "properties": {"Bad": {"$anchor": "a", "pattern": "(?=a)"}},
        }
    )
    with pytest.raises(SchemaDocumentError) as caught:
        check_schema_document(metadata_schema_document)
    pairs = [(p.where, p.rule) for p in caught.value.problems]
    assert pairs == sorted(pairs)
    assert set(pairs) >= {
        ("/$schema", "dialect"),
        ("/$ref", "ref"),
        ("/type", "root_type"),
        ("/minProperties", "metaschema"),
        ("/maxProperties", "metaschema"),
        ("/additionalProperties", "closed"),
        ("/properties/Bad", "field_name"),
        ("/properties/Bad/$anchor", "ref"),
        ("/properties/Bad/pattern", "regex"),
    }


def test_open_schema_with_ordinary_enums_and_local_definitions_is_publishable(
    metadata_schema_document: dict[str, Any],
) -> None:
    """Root IDs, escaped definition keys, nested names, RE2 patterns and enums remain legal."""
    assert BASE_SCHEMA_NAME == "org"
    assert metadata_schema_document["$schema"] == DRAFT_2020_12
    metadata_schema_document.update(
        {
            "$id": "urn:example:metadata",
            "$defs": {"a/b~c": {"properties": {"X": {"type": "string"}}}},
            "properties": {
                "x": {"$ref": "#/$defs/a~1b~0c/properties/X"},
                "x" * 64: {"enum": ["a", "b"]},
                "nested": {
                    "properties": {"Any/~": {"pattern": r"\p{L}+"}},
                    "additionalProperties": False,
                },
            },
        }
    )
    assert check_schema_document(metadata_schema_document) is None


@pytest.mark.parametrize("reference", ["#/$defs/a~2b", "#/$defs/a~", "#/$defs/a~1b/~2"])
def test_malformed_pointer_escapes_are_refused(
    metadata_schema_document: dict[str, Any], reference: str
) -> None:
    """Malformed JSON pointer escapes cannot name a permitted definition reference."""
    metadata_schema_document.update({"$defs": {"a/b": {}}, "$ref": reference})
    with pytest.raises(SchemaDocumentError) as caught:
        check_schema_document(metadata_schema_document)
    assert ("/$ref", "ref") in [(p.where, p.rule) for p in caught.value.problems]


@pytest.mark.parametrize("patch", [{"properties": []}, {"allOf": {}}, {"items": 3}, {"pattern": 4}])
def test_malformed_applicators_are_reported_without_crashing(
    metadata_schema_document: dict[str, Any], patch: dict[str, Any]
) -> None:
    """Invalid keyword shapes become metaschema problems without traversal failures."""
    with pytest.raises(SchemaDocumentError) as caught:
        check_schema_document(metadata_schema_document | patch)
    assert all(p.rule == "metaschema" for p in caught.value.problems)


def test_read_only_schema_mapping_is_accepted(metadata_schema_document: dict[str, Any]) -> None:
    """The public Mapping contract accepts immutable top-level mapping wrappers."""
    assert check_schema_document(MappingProxyType(metadata_schema_document)) is None


@pytest.mark.parametrize(
    "key,reference,accepted",
    [
        ("a b", "#/$defs/a%20b", True),
        ("a/b", "#/$defs/a%7E1b", True),
        ("a%20b", "#/$defs/a%20b", False),
        ("a%", "#/$defs/a%", False),
        ("a", "#/$defs/%FF", False),
    ],
)
def test_definition_references_decode_uri_fragments(
    metadata_schema_document: dict[str, Any], key: str, reference: str, accepted: bool
) -> None:
    """URI percent encoding is resolved before checking the root definition's name."""
    metadata_schema_document.update({"$defs": {key: {}}, "$ref": reference})
    if accepted:
        assert check_schema_document(metadata_schema_document) is None
    else:
        with pytest.raises(SchemaDocumentError) as caught:
            check_schema_document(metadata_schema_document)
        assert ("/$ref", "ref") in [(p.where, p.rule) for p in caught.value.problems]


@pytest.mark.parametrize(
    "definition,suffix",
    [
        ({}, "/missing"),
        ({"type": "string"}, "/type"),
        ({"properties": {"x": {}}}, "/properties"),
        ({"allOf": [{}]}, "/allOf"),
        ({"allOf": [{}]}, "/allOf/1"),
        ({"allOf": [{}]}, "/allOf/00"),
        ({"allOf": [{}]}, "/allOf/-"),
        ({"allOf": [{}]}, "/allOf/-1"),
        ({"default": {"pattern": "(?=a)"}}, "/default"),
        ({"default": {"$ref": "https://example.invalid/evil"}}, "/default"),
        ({"const": True}, "/const"),
        ({"enum": [{}]}, "/enum/0"),
        ({"examples": [{}]}, "/examples/0"),
        ({"x-annotation": {"properties": {"x": {}}}}, "/x-annotation/properties/x"),
        (False, "/properties/x"),
        (3, ""),
    ],
)
def test_reference_targets_must_be_existing_schema_positions(
    metadata_schema_document: dict[str, Any], definition: Any, suffix: str
) -> None:
    """References cannot execute literal data or resolve missing and non-schema targets."""
    metadata_schema_document.update(
        {"$defs": {"a": definition}, "properties": {"x": {"$ref": "#/$defs/a" + suffix}}}
    )
    with pytest.raises(SchemaDocumentError) as caught:
        check_schema_document(metadata_schema_document)
    assert ("/properties/x/$ref", "ref") in [(p.where, p.rule) for p in caught.value.problems]


@pytest.mark.parametrize(
    "definition,suffix",
    [
        (True, ""),
        (False, ""),
        ({"properties": {"a/b~c": False}}, "/properties/a~1b~0c"),
        ({"properties": {"a/b~c": {}}}, "/properties/a%7E1b%7E0c"),
        ({"properties": {"a b": {}}}, "/properties/a%20b"),
        ({"properties": {"": {}}}, "/properties/"),
        ({"$defs": {"inner": {}}}, "/$defs/inner"),
        ({"items": False}, "/items"),
        ({"allOf": [True, {}]}, "/allOf/1"),
        ({"anyOf": [False]}, "/anyOf/0"),
        ({"oneOf": [{}]}, "/oneOf/0"),
        ({"prefixItems": [False]}, "/prefixItems/%30"),
    ],
)
def test_references_resolve_nested_object_and_boolean_schemas(
    metadata_schema_document: dict[str, Any], definition: Any, suffix: str
) -> None:
    """All pointer tokens resolve after fragment decoding, including array positions."""
    metadata_schema_document.update({"$defs": {"a": definition}, "$ref": "#/$defs/a" + suffix})
    assert check_schema_document(metadata_schema_document) is None
