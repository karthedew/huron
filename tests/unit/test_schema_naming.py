"""Strict explicit names and lossless lexical identifier forms."""

from dataclasses import FrozenInstanceError
from pathlib import PurePosixPath

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from huron.schema.naming import (
    IDENTIFIER_MAX_BYTES,
    SEGMENT_PATTERN,
    Identifier,
    NamingError,
    check_namespace,
    check_segment,
    is_reserved,
)

pytestmark = pytest.mark.unit
segments = st.from_regex(SEGMENT_PATTERN, fullmatch=True)
paths = st.lists(segments, max_size=12).map(tuple)


@settings(derandomize=True)
@given(segments)
def test_valid_segments_are_returned_unchanged(value: str) -> None:
    """All strict segments survive validation byte-for-byte and are never reserved."""
    assert check_segment(value) == value
    assert not is_reserved(value)


@settings(derandomize=True)
@given(st.text())
def test_arbitrary_names_are_rejected_without_sanitizing(value: str) -> None:
    """Validation either preserves the input or exposes that exact input in its refusal."""
    try:
        assert check_segment(value) == value
    except NamingError as error:
        assert error.rule == "segment"
        assert error.value == value
        assert repr(value) in str(error)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "...",
        "日本",
        "-_-",
        "Campaign 17",
        "Müller_ß",
        "v1.2",
        "a" * 65,
        "A",
        "a\n",
        "a\x00",
        "a/b",
        "a\\b",
        "_a",
        "-a",
    ],
)
def test_invalid_explicit_names_are_refused(value: str) -> None:
    """Names never undergo slugification, trimming, truncation or case conversion."""
    with pytest.raises(NamingError) as caught:
        check_segment(value)
    assert (caught.value.rule, caught.value.value) == ("segment", value)


@pytest.mark.parametrize(
    ("name", "reserved"),
    [
        (".snapshot", True),
        (".hidden", True),
        ("a.part", True),
        ("part", False),
        ("a.PART", False),
        ("", False),
    ],
)
def test_reserved_names(name: str, reserved: bool) -> None:
    """Hidden and partial names are reserved with exact case-sensitive spelling."""
    assert is_reserved(name) is reserved


@settings(derandomize=True)
@given(segments, paths)
def test_every_identifier_round_trips_through_all_four_forms(
    catalog: str, path: tuple[str, ...]
) -> None:
    """Catalogs and descendants round trip without filesystem or contextual guessing."""
    identifier = Identifier(catalog, path)
    prefix = PurePosixPath("/projects")
    assert Identifier.from_canonical(identifier.canonical()) == identifier
    assert Identifier.parse(identifier.fully_qualified()) == identifier
    assert Identifier.parse(identifier.catalog_rooted(), catalog=catalog) == identifier
    assert Identifier.parse(str(identifier.mount_path(prefix)), mount_prefix=prefix) == identifier
    assert identifier.canonical().replace(".", "/") == identifier.fully_qualified()


@settings(derandomize=True)
@given(st.lists(segments, min_size=1, max_size=13))
def test_valid_canonical_strings_round_trip_byte_for_byte(parts: list[str]) -> None:
    """Canonical parsing cannot normalize or change a valid spelling."""
    text = ".".join(parts)
    assert Identifier.from_canonical(text).canonical() == text


@pytest.mark.parametrize(
    ("text", "catalog", "expected"),
    [
        ("/projectsx/a", "cat", "cat.projectsx.a"),
        ("/projects/a/b/", None, "a.b"),
        ("/a/b/", "cat", "cat.a.b"),
        ("a/b/", None, "a.b"),
        ("a/", None, "a"),
        ("a.b", "ignored", "a.b"),
        ("/", "cat", "cat"),
        ("/projects/cat", "ignored", "cat"),
    ],
)
def test_form_detection_precedence(text: str, catalog: str | None, expected: str) -> None:
    """The first matching lexical form wins, with one trailing slash allowed."""
    assert (
        Identifier.parse(text, catalog=catalog, mount_prefix=PurePosixPath("/projects")).canonical()
        == expected
    )


@pytest.mark.parametrize(
    ("text", "rule"),
    [
        ("/projects", "outside_prefix"),
        ("/projects/", "outside_prefix"),
        ("/projects//", "empty_segment"),
        ("/psp/", "no_catalog"),
        ("a//b", "empty_segment"),
        ("a..b", "empty_segment"),
        (".a", "empty_segment"),
        ("a.", "empty_segment"),
        ("", "empty_segment"),
        ("a/../b", "segment"),
        ("a/./b", "segment"),
        ("a/b//", "empty_segment"),
        ("/projects/a//b", "empty_segment"),
        ("/projects/a/./b", "segment"),
        ("/projects/a/../b", "segment"),
        ("/projects//a", "empty_segment"),
        ("//projects/a", "no_catalog"),
    ],
)
def test_unsafe_forms_are_refused_before_path_normalization(text: str, rule: str) -> None:
    """Path normalization cannot hide malformed separators or traversal."""
    with pytest.raises(NamingError) as caught:
        Identifier.parse(text, mount_prefix=PurePosixPath("/projects"))
    assert caught.value.rule == rule


@pytest.mark.parametrize("text", ["a/b", "/a/b", "a\\b", "a..b", ".a", "a."])
def test_canonical_parser_never_accepts_another_form(text: str) -> None:
    """Server inputs cannot invoke the client form-selection rules."""
    with pytest.raises(NamingError):
        Identifier.from_canonical(text)


@pytest.mark.parametrize("depth", [9, 10, 11, 12, 100])
def test_deep_valid_paths_have_no_business_depth_limit(depth: int) -> None:
    """Recursive namespace and identifier values support well beyond six levels."""
    namespace = ("n",) * depth
    assert check_namespace(namespace) == namespace
    identifier = Identifier("cat", (*namespace, "collection"))
    assert (
        Identifier.parse(
            str(identifier.mount_path(PurePosixPath("/mnt"))), mount_prefix=PurePosixPath("/mnt")
        )
        == identifier
    )


def test_logical_byte_budget_is_independent_of_mount_prefix() -> None:
    """Maximum logical paths round trip with long prefixes, and the next byte is refused."""
    parts = ("a" * 63,) * 16
    identifier = Identifier(parts[0], parts[1:])
    assert len(identifier.fully_qualified()) == IDENTIFIER_MAX_BYTES
    prefix = PurePosixPath("/" + "prefix" * 100)
    assert Identifier.parse(str(identifier.mount_path(prefix)), mount_prefix=prefix) == identifier
    for text in (
        identifier.canonical() + "a",
        identifier.fully_qualified() + "a",
        identifier.catalog_rooted() + "a",
        str(identifier.mount_path(prefix)) + "a",
    ):
        with pytest.raises(NamingError) as caught:
            Identifier.parse(text, catalog=identifier.catalog, mount_prefix=prefix)
        assert caught.value.rule == "path_length"
    with pytest.raises(NamingError, match="exceeds"):
        check_namespace((*parts, "a"))


@pytest.mark.parametrize("path", [(), ("a", ".."), ("a", ""), ("A",)])
def test_namespace_requires_nonempty_strict_segments(path: tuple[str, ...]) -> None:
    """A namespace cannot be the catalog root or contain unsafe segments."""
    with pytest.raises(NamingError):
        check_namespace(path)


@pytest.mark.parametrize(
    "prefix", ["relative", "../mount", "/mount/../other", "//mount", "/mount\x00"]
)
def test_mount_prefix_must_be_absolute_and_safe(prefix: str) -> None:
    """Relative, parent-traversing and double-root mount prefixes are refused."""
    with pytest.raises(NamingError) as caught:
        Identifier("cat").mount_path(PurePosixPath(prefix))
    assert caught.value.rule == "outside_prefix"


def test_root_mount_prefix_is_supported() -> None:
    """A root mount still requires an identifier strictly below it."""
    identifier = Identifier("cat", ("ns",))
    assert identifier.mount_path(PurePosixPath("/")) == PurePosixPath("/cat/ns")
    assert Identifier.parse("/cat/ns", mount_prefix=PurePosixPath("/")) == identifier
    with pytest.raises(NamingError) as caught:
        Identifier.parse("/", mount_prefix=PurePosixPath("/"))
    assert caught.value.rule == "outside_prefix"


def test_identifier_values_are_immutable_hashable_and_ordered() -> None:
    """Values own an immutable copy of their path and sort by catalog then descendants."""
    path = ["ns"]
    identifier = Identifier("cat", path)
    path.append("other")
    assert identifier.path == ("ns",)
    assert len({identifier, Identifier("cat", ("ns",))}) == 1
    assert sorted([identifier, Identifier("cat"), Identifier("aaa")]) == [
        Identifier("aaa"),
        Identifier("cat"),
        identifier,
    ]
    with pytest.raises(FrozenInstanceError):
        identifier.catalog = "other"


def test_naming_error_preserves_rule_value_and_detail() -> None:
    """Consumers can translate errors without parsing their human-readable detail."""
    error = NamingError("segment", "Invalid Name", "explicit name required")
    assert error.rule == "segment"
    assert error.value == "Invalid Name"
    assert str(error) == "explicit name required: 'Invalid Name'"
