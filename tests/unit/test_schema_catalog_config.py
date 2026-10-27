"""Catalog configuration owns exact schema selection without metadata-driven placement."""

from dataclasses import FrozenInstanceError
from typing import Any

import pytest
import yaml

from huron.schema import load_schema, validator
from huron.schema._validator import HuronValidator
from huron.schema.catalog_config import CatalogConfig, ConfigError, SchemaRef
from huron.schema.naming import SEGMENT_PATTERN, NamingError

pytestmark = pytest.mark.unit


def test_minimal_config_defaults_optional_annotations(
    catalog_config_document: dict[str, Any],
) -> None:
    """A minimal config retains its exact schema with absent annotations as None."""
    config = CatalogConfig.from_document(catalog_config_document)
    assert config == CatalogConfig("heliophysics", SchemaRef("heliophysics", 1))
    assert config.title is config.snapshot_class is config.config_version is None


def test_stored_yaml_config_loads_exact_selection() -> None:
    """The stored YAML example loads its display, receipt and operator policy fields."""
    document = yaml.safe_load("""
catalog: heliophysics
config_version: 7
title: Heliophysics
schema: {name: heliophysics, version: 3}
snapshot_class: standard
""")
    assert CatalogConfig.from_document(document) == CatalogConfig(
        "heliophysics", SchemaRef("heliophysics", 3), 7, "Heliophysics", "standard"
    )


@pytest.mark.parametrize("name", ["a", "0", "a" * 64, "schema_2-name"])
def test_strict_name_boundaries_are_accepted(name: str) -> None:
    """Catalog and schema names share the accepted strict segment boundaries."""
    assert CatalogConfig.from_document(
        {"catalog": name, "schema": {"name": name, "version": 1}}
    ).schema == SchemaRef(name, 1)


@pytest.mark.parametrize("name", ["", "a" * 65, "space science", "UPPER", "a.b", "a/b", "a\n", "é"])
def test_invalid_names_are_refused_unchanged(
    name: str, catalog_config_document: dict[str, Any]
) -> None:
    """Neither catalog nor schema names are silently sanitized."""
    catalog_config_document.update(catalog=name, schema={"name": name, "version": 1})
    with pytest.raises(ConfigError) as caught:
        CatalogConfig.from_document(catalog_config_document)
    assert [(p.where, p.rule) for p in caught.value.problems] == [
        ("/catalog", "pattern"),
        ("/schema/name", "pattern"),
    ]
    assert catalog_config_document["catalog"] == name
    with pytest.raises(NamingError):
        SchemaRef(name, 1)


@pytest.mark.parametrize("version", [True, False, 0, -1, "1", 1.0, 1.5, None])
def test_versions_require_positive_integers(
    version: Any, catalog_config_document: dict[str, Any]
) -> None:
    """Both stored and selected versions refuse booleans, floats and nonpositive values."""
    catalog_config_document.update(
        config_version=version, schema={"name": "science", "version": version}
    )
    with pytest.raises(ConfigError) as caught:
        CatalogConfig.from_document(catalog_config_document)
    assert {p.where for p in caught.value.problems} == {"/config_version", "/schema/version"}
    with pytest.raises(ValueError, match="positive integer"):
        SchemaRef("science", version)


@pytest.mark.parametrize(
    "schema",
    [
        "heliophysics-v1",
        None,
        [],
        {},
        {"name": "science"},
        {"version": 1},
        {"name": "science", "version": 1, "latest": True},
    ],
)
def test_schema_requires_an_exact_closed_reference(
    schema: Any, catalog_config_document: dict[str, Any]
) -> None:
    """A string alias, partial reference or extra reference field cannot select a schema."""
    catalog_config_document["schema"] = schema
    with pytest.raises(ConfigError) as caught:
        CatalogConfig.from_document(catalog_config_document)
    assert all(p.where == "/schema" for p in caught.value.problems)


@pytest.mark.parametrize(
    "key,value",
    [
        ("namespace_fields", ["mission"]),
        ("collection_name", {"field": "run_id"}),
        ("vocabularies", {"mission": ["psp"]}),
        ("identity_fields", ["mission"]),
        ("choices", {}),
        ("place", {}),
        ("slugify", True),
        ("extra/~field", 1),
    ],
)
def test_obsolete_and_unknown_keys_are_rejected(
    key: str, value: Any, catalog_config_document: dict[str, Any]
) -> None:
    """Placement vocabulary and arbitrary extras have no place in catalog config."""
    catalog_config_document[key] = value
    with pytest.raises(ConfigError) as caught:
        CatalogConfig.from_document(catalog_config_document)
    assert [(p.where, p.rule) for p in caught.value.problems] == [("", "additionalProperties")]


@pytest.mark.parametrize(
    "key,value,rule",
    [
        ("catalog", 5, "type"),
        ("title", "", "minLength"),
        ("title", "x" * 201, "maxLength"),
        ("title", None, "type"),
        ("title", 1, "type"),
        ("snapshot_class", None, "type"),
        ("snapshot_class", "has space", "pattern"),
    ],
)
def test_optional_fields_must_be_valid_when_present(
    key: str, value: Any, rule: str, catalog_config_document: dict[str, Any]
) -> None:
    """Omission is distinct from malformed or explicit-null annotation fields."""
    catalog_config_document[key] = value
    with pytest.raises(ConfigError) as caught:
        CatalogConfig.from_document(catalog_config_document)
    assert [(p.where, p.rule) for p in caught.value.problems] == [(f"/{key}", rule)]


@pytest.mark.parametrize("document", [None, [], "config", {}, {"catalog": "science"}])
def test_missing_or_nonobject_documents_are_aggregated(document: Any) -> None:
    """Malformed roots and missing mandatory keys produce configuration failures."""
    with pytest.raises(ConfigError) as caught:
        CatalogConfig.from_document(document)
    assert all(p.where == "" for p in caught.value.problems)


def test_problems_are_aggregated_sorted_and_owned(catalog_config_document: dict[str, Any]) -> None:
    """All independent failures survive deterministic pointer ordering in one error."""
    catalog_config_document.update(
        title="", catalog="bad name", schema={"name": "Bad", "version": 0}
    )
    with pytest.raises(ConfigError) as caught:
        CatalogConfig.from_document(catalog_config_document)
    problems = caught.value.problems
    assert [p.where for p in problems] == ["/catalog", "/schema/name", "/schema/version", "/title"]
    assert all(p.message for p in problems)
    supplied = list(reversed(problems))
    error = ConfigError(supplied)
    supplied.clear()
    assert error.problems == problems
    assert "/schema/version:" in str(error)
    with pytest.raises(ValueError, match="at least one"):
        ConfigError([])
    with pytest.raises(FrozenInstanceError):
        problems[0].where = "/changed"


def test_config_owns_immutable_values(catalog_config_document: dict[str, Any]) -> None:
    """Mutating source aliases or frozen values cannot alter a loaded configuration."""
    config = CatalogConfig.from_document(catalog_config_document)
    catalog_config_document["schema"]["version"] = 9
    catalog_config_document["catalog"] = "changed"
    assert config == CatalogConfig("heliophysics", SchemaRef("heliophysics", 1))
    assert hash(config) == hash(CatalogConfig("heliophysics", SchemaRef("heliophysics", 1)))
    with pytest.raises(FrozenInstanceError):
        config.catalog = "changed"
    with pytest.raises(FrozenInstanceError):
        config.schema.version = 9
    with pytest.raises(ConfigError):
        CatalogConfig("Bad", SchemaRef("science", 1))


def test_document_segment_pattern_is_the_naming_rule() -> None:
    """The packaged segment pattern cannot drift from shared strict naming."""
    assert (
        load_schema("catalog-config-v1.json")["$defs"]["segment"]["pattern"]
        == "^" + SEGMENT_PATTERN + "$"
    )


def test_catalog_config_validator_is_a_huron_validator() -> None:
    """Catalog validation retains bounded matching and offline references."""
    assert isinstance(validator("catalog-config-v1.json"), HuronValidator)
