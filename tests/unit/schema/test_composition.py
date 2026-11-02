"""Composition of schema documents along an extends chain."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from huron.schema.composition import SchemaIncompatible, compose, resolve_chain
from huron.schema.loader import load_document

names = st.sampled_from(["a", "b", "c", "d"])
properties = st.dictionaries(names, st.sampled_from([{"type": "string"}, {"type": "integer"}]))


@st.composite
def documents(draw: st.DrawFn) -> dict[str, object]:
    props = draw(properties)
    required = draw(st.lists(st.sampled_from(sorted(props) or ["a"]), unique=True))
    return {"type": "object", "properties": props, "required": [r for r in required if r in props]}


@given(documents())
def test_composing_with_an_empty_child_is_identity(parent: dict[str, object]) -> None:
    composed = compose(parent, {"type": "object"})
    assert composed["properties"] == parent["properties"]
    assert composed["required"] == parent["required"]


@given(documents(), documents())
def test_required_fields_only_grow(parent: dict[str, object], child: dict[str, object]) -> None:
    try:
        composed = compose(parent, child)
    except SchemaIncompatible:
        return
    assert set(parent["required"]) <= set(composed["required"])  # type: ignore[arg-type]
    assert set(child["required"]) <= set(composed["required"])  # type: ignore[arg-type]


def test_child_overrides_metadata_and_tightens_properties() -> None:
    base = load_document("huron-base-v1")
    child = {
        "type": "object",
        "title": "Heliophysics",
        "additionalProperties": False,
        "properties": {"title": {"type": "string", "maxLength": 80}, "mission": {"type": "string"}},
        "required": ["mission", "title"],
    }
    composed = compose(base, child)
    assert composed["title"] == "Heliophysics"
    assert composed["description"] == base["description"]
    assert composed["additionalProperties"] is False
    assert composed["properties"]["title"] == {"type": "string", "maxLength": 80}
    assert composed["required"] == ["title", "description", "mission"]


def test_changing_the_type_of_a_required_property_is_refused() -> None:
    parent = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}
    with pytest.raises(SchemaIncompatible) as raised:
        compose(parent, {"type": "object", "properties": {"a": {"type": "integer"}}})
    assert raised.value.context["property"] == "a"
    optional = {"type": "object", "properties": {"a": {"type": "string"}}}
    assert compose(optional, {"properties": {"a": {"type": "integer"}}})["properties"]["a"] == {
        "type": "integer"
    }


def test_resolving_a_chain_composes_root_to_leaf() -> None:
    root = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}
    middle = {"type": "object", "properties": {"b": {"type": "string"}}, "required": ["b"]}
    leaf = {"type": "object", "properties": {"c": {"type": "string"}}}
    resolved = resolve_chain([root, middle, leaf])
    assert resolved["required"] == ["a", "b"]
    assert set(resolved["properties"]) == {"a", "b", "c"}
    with pytest.raises(ValueError):
        resolve_chain([])
