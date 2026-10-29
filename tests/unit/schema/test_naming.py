"""Segment, identifier and relative-path rules."""

import unicodedata

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from huron.schema.naming import (
    Identifier,
    NamingError,
    RelPathError,
    check_rel_path,
    check_segment,
    collection_identifier,
    namespace_identifier,
    parse_identifier,
    part_name,
    rel_path_key,
)
from tests.support.naming import path_segments, segments


@given(segments)
def test_valid_segments_are_accepted_unchanged(value: str) -> None:
    assert check_segment(value) == value


@pytest.mark.parametrize(
    ("value", "rule"),
    [
        ("Upper", "segment_chars"),
        ("-lead", "segment_chars"),
        ("_lead", "segment_chars"),
        ("has.dot", "segment_chars"),
        ("", "segment_chars"),
        ("a" * 64, "segment_length"),
        ("huron", "segment_reserved"),
        ("metadata", "segment_reserved"),
        (unicodedata.normalize("NFD", "café"), "segment_nfc"),
        ("café", "segment_chars"),
    ],
)
def test_invalid_segments_name_the_broken_rule(value: str, rule: str) -> None:
    with pytest.raises(NamingError) as raised:
        check_segment(value)
    assert raised.value.rule == rule
    assert raised.value.context == {"rule": rule, "value": value}
    assert raised.value.status == 422


@given(st.lists(segments, min_size=3, max_size=6))
def test_collection_identifiers_round_trip(parts: list[str]) -> None:
    text = ".".join(parts)
    assume(len(text.encode()) <= 255)
    identifier = collection_identifier(text)
    assert str(identifier) == text
    assert identifier.name == parts[-1]
    assert identifier.parent == Identifier(parts[0], tuple(parts[1:-1]))


def test_namespace_identifiers_and_parents() -> None:
    identifier = namespace_identifier("helio.solar-wind.l0")
    assert identifier.namespace == "solar-wind.l0"
    assert identifier.parent == Identifier("helio", ("solar-wind",))
    assert Identifier("helio", ("a",)).parent == Identifier("helio")
    assert Identifier("helio").parent is None
    assert Identifier("helio").segments == ("helio",)


@pytest.mark.parametrize(
    ("text", "rule"),
    [
        ("", "identifier_empty"),
        ("a." * 128 + "a", "identifier_length"),
        ("helio..x", "segment_chars"),
    ],
)
def test_invalid_identifiers(text: str, rule: str) -> None:
    with pytest.raises(NamingError) as raised:
        parse_identifier(text)
    assert raised.value.rule == rule


def test_identifier_depth_is_enforced() -> None:
    with pytest.raises(NamingError, match="identifier_depth"):
        namespace_identifier("helio")
    with pytest.raises(NamingError, match="identifier_depth"):
        collection_identifier("helio.ns")


@given(st.lists(path_segments, min_size=1, max_size=4))
def test_valid_relative_paths_are_accepted(parts: list[str]) -> None:
    value = unicodedata.normalize("NFC", "/".join(parts))
    assume("\\" not in value and value != "metadata.json")
    assume(all(part not in {"", ".", ".."} for part in value.split("/")))
    assert check_rel_path(value) == value


@pytest.mark.parametrize(
    ("value", "rule"),
    [
        (unicodedata.normalize("NFD", "café.txt"), "rel_path_nfc"),
        ("", "rel_path_length"),
        ("a" * 1025, "rel_path_length"),
        ("a/" + "b" * 256, "rel_path_segment"),
        ("bad\x00name", "rel_path_control"),
        ("back\\slash", "rel_path_control"),
        ("/abs", "rel_path_separator"),
        ("trailing/", "rel_path_separator"),
        ("a//b", "rel_path_separator"),
        ("a/./b", "rel_path_separator"),
        ("../up", "rel_path_separator"),
        ("metadata.json", "rel_path_reserved"),
        (".huron", "rel_path_reserved"),
        ("x/.huronstate", "rel_path_reserved"),
        ("x.bin.huron-part", "rel_path_reserved"),
    ],
)
def test_invalid_relative_paths_name_the_broken_rule(value: str, rule: str) -> None:
    with pytest.raises(RelPathError) as raised:
        check_rel_path(value)
    assert raised.value.rule == rule


def test_metadata_json_below_the_root_is_an_ordinary_file() -> None:
    assert check_rel_path("sub/metadata.json") == "sub/metadata.json"
    assert check_rel_path("metadata.json.d/x") == "metadata.json.d/x"


def test_keys_fold_case_and_part_names_append_the_suffix() -> None:
    assert rel_path_key("Data/File.TXT") == rel_path_key("data/file.txt")
    assert rel_path_key("Straße") == rel_path_key("STRASSE")
    assert part_name("a/b.bin") == "a/b.bin.huron-part"
