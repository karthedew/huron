"""Property tests pinning the invariants the pure catalog core is built on.

Generated inputs, rather than a handful of hand-picked examples, exercise the
four facts the rest of the system relies on without re-checking: that
:func:`~huron.pkg.catalog.paths.parse_revision_dir` inverts
:func:`~huron.pkg.catalog.paths.revision_dir` exactly, that
:func:`~huron.pkg.catalog.manifest.validate_manifest` catches every path
collision Unicode normalization and case folding can create, that
:func:`~huron.pkg.catalog.manifest.canonical_bytes` does not depend on key
order and enforces the JCS-safe integer bound, and that
:func:`~huron.pkg.catalog.ids.uuid7` produces well-formed identifiers whose
embedded timestamps never regress across calls.
"""

from __future__ import annotations

import itertools
import string
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

import pytest
from hypothesis import assume, example, given, settings
from hypothesis import strategies as st

from huron.pkg.catalog.errors import PathCollision
from huron.pkg.catalog.ids import uuid7
from huron.pkg.catalog.manifest import (
    MAX_SAFE_INT,
    ManifestEntry,
    canonical_bytes,
    validate_manifest,
)
from huron.pkg.catalog.models import EntityRef
from huron.pkg.catalog.paths import (
    DATASET_SLUG_MAX,
    ORG_PROJECT_SLUG_MAX,
    RevisionPath,
    parse_revision_dir,
    revision_dir,
)

if TYPE_CHECKING:
    from uuid import UUID

pytestmark = pytest.mark.unit

_property = settings(deadline=None, max_examples=200)

_ROOT = PurePosixPath("/data")

_ALNUM = string.ascii_lowercase + string.digits
_ALNUM_OR_HYPHEN = _ALNUM + "-"


@st.composite
def _slugs(draw: st.DrawFn, min_size: int, max_size: int) -> str:
    """Build a slug of the shape the catalog's ``SLUG`` pattern accepts.

    Args:
        draw: The Hypothesis draw function.
        min_size: The shortest slug to build.
        max_size: The longest slug to build.

    Returns:
        A slug starting with a letter or digit, otherwise letters, digits and
        single hyphens, never containing ``--``.
    """
    length = draw(st.integers(min_value=min_size, max_value=max_size))
    characters = [draw(st.sampled_from(_ALNUM))]
    for _ in range(length - 1):
        previous = characters[-1]
        choices = _ALNUM if previous == "-" else _ALNUM_OR_HYPHEN
        characters.append(draw(st.sampled_from(choices)))
    return "".join(characters)


@given(
    org_slug=_slugs(2, ORG_PROJECT_SLUG_MAX),
    org_id=st.builds(uuid7),
    project_slug=_slugs(2, ORG_PROJECT_SLUG_MAX),
    project_id=st.builds(uuid7),
    dataset_slug=_slugs(2, DATASET_SLUG_MAX),
    dataset_id=st.builds(uuid7),
    revision_number=st.integers(min_value=1, max_value=999_999),
    revision_id=st.builds(uuid7),
)
@_property
def test_parse_revision_dir_recovers_exactly_what_revision_dir_encoded(
    org_slug: str,
    org_id: UUID,
    project_slug: str,
    project_id: UUID,
    dataset_slug: str,
    dataset_id: UUID,
    revision_number: int,
    revision_id: UUID,
) -> None:
    """Parsing a built revision directory returns the slugs, ids and numbers that built it."""
    organization = EntityRef(org_id, org_slug)
    project = EntityRef(project_id, project_slug)
    dataset = EntityRef(dataset_id, dataset_slug)

    path = revision_dir(_ROOT, organization, project, dataset, revision_number, revision_id)

    assert parse_revision_dir(_ROOT, path) == RevisionPath(
        org_slug,
        org_id,
        project_slug,
        project_id,
        dataset_slug,
        dataset_id,
        revision_number,
        revision_id,
    )


# Precomposed accented letters (é, É) are already stable under NFC, unlike a
# base letter followed by a combining accent, so paths built from this
# alphabet always pass validate_manifest_path's NFC check on their own merits
# and any collision found is genuinely the case-folding rule, not the NFC one.
_COLLISION_ALPHABET = string.ascii_lowercase + string.ascii_uppercase + "éÉ"


def _swapped(text: str, flips: list[bool]) -> str:
    """Return `text` with the case of each flipped letter toggled.

    Args:
        text: The characters to transform.
        flips: One flag per character in ``text``; ``True`` toggles the case
            of that character if it is a letter.

    Returns:
        The transformed string, the same length as ``text``.
    """
    return "".join(
        character.swapcase() if flip and character.isalpha() else character
        for character, flip in zip(text, flips, strict=True)
    )


@st.composite
def _casefold_collision_pair(draw: st.DrawFn) -> tuple[str, str]:
    """Build two distinct strings equal once NFC-normalized and case-folded.

    Args:
        draw: The Hypothesis draw function.

    Returns:
        Two different strings whose ``unicodedata.normalize("NFC",
        …).casefold()`` values coincide.
    """
    base = draw(st.text(alphabet=_COLLISION_ALPHABET, min_size=1, max_size=8))
    assume(any(character.isalpha() for character in base))
    flips = draw(st.lists(st.booleans(), min_size=len(base), max_size=len(base)))
    variant = _swapped(base, flips)
    assume(variant != base)
    return base, variant


@st.composite
def _pairwise_distinct_paths(draw: st.DrawFn, size: int) -> list[str]:
    """Build path segments whose NFC+casefold forms are pairwise distinct.

    Args:
        draw: The Hypothesis draw function.
        size: How many segments to build.

    Returns:
        ``size`` strings, each a randomly-cased rendering of one of ``size``
        labels that are pairwise distinct once case-folded.
    """
    labels = draw(
        st.sets(
            st.text(alphabet=_COLLISION_ALPHABET, min_size=1, max_size=8).map(str.casefold),
            min_size=size,
            max_size=size,
        )
    )
    rendered = []
    for label in labels:
        flips = draw(st.lists(st.booleans(), min_size=len(label), max_size=len(label)))
        rendered.append(_swapped(label, flips))
    return rendered


def _entries(path_segments: list[str]) -> list[ManifestEntry]:
    """Build manifest entries for the given payload-relative segments.

    Args:
        path_segments: The part of each path after ``payload/``.

    Returns:
        One valid :class:`ManifestEntry` per segment, sharing a fixed size
        and digest since neither participates in collision detection.
    """
    return [
        ManifestEntry(path=f"payload/{segment}", size=1024, sha256="0" * 64)
        for segment in path_segments
    ]


@given(pair=_casefold_collision_pair())
@_property
def test_validate_manifest_rejects_paths_equal_under_nfc_and_casefold(
    pair: tuple[str, str],
) -> None:
    """Two entries whose paths coincide once NFC-normalized and case-folded are refused."""
    first, second = pair

    with pytest.raises(PathCollision):
        validate_manifest(_entries([first, second]))


@given(path_segments=_pairwise_distinct_paths(size=3))
@_property
def test_validate_manifest_accepts_paths_pairwise_distinct_under_nfc_and_casefold(
    path_segments: list[str],
) -> None:
    """Entries whose paths stay pairwise distinct once NFC-normalized and case-folded all pass."""
    entries = _entries(path_segments)

    manifest = validate_manifest(entries)

    assert len(manifest.files) == len(entries)


def _json_scalars() -> st.SearchStrategy[object]:
    """Return a strategy for JSON scalars within the JCS-exact integer range.

    Returns:
        Strings, booleans, floats and integers no larger in magnitude than
        :data:`MAX_SAFE_INT`.
    """
    return st.one_of(
        st.text(max_size=8),
        st.booleans(),
        st.integers(min_value=-MAX_SAFE_INT, max_value=MAX_SAFE_INT),
        st.floats(allow_nan=False, allow_infinity=False, width=32),
    )


def _json_values(depth: int) -> st.SearchStrategy[object]:
    """Return a strategy for JSON-compatible values nested up to `depth` levels deeper.

    Args:
        depth: How many further levels of list or mapping nesting to allow.

    Returns:
        Scalars at ``depth`` 0, otherwise also lists and mappings of
        recursively shallower values.
    """
    if depth <= 0:
        return _json_scalars()
    nested = _json_values(depth - 1)
    return st.one_of(
        _json_scalars(),
        st.lists(nested, max_size=4),
        st.dictionaries(st.text(min_size=1, max_size=6), nested, max_size=4),
    )


_documents = st.dictionaries(
    st.text(min_size=1, max_size=6), _json_values(2), min_size=1, max_size=5
)


def _reordered(value: object) -> object:
    """Rebuild every mapping inside `value` with its keys in reverse order.

    Args:
        value: A JSON-compatible value, possibly nested.

    Returns:
        An equal value in which every ``dict``'s iteration order is reversed
        from the original, recursively.
    """
    if isinstance(value, dict):
        return {key: _reordered(value[key]) for key in reversed(list(value))}
    if isinstance(value, list):
        return [_reordered(item) for item in value]
    return value


@given(document=_documents)
@_property
def test_canonical_bytes_does_not_depend_on_mapping_key_order(
    document: dict[str, object],
) -> None:
    """Reversing every nested mapping's key order leaves the canonical bytes unchanged."""
    assert canonical_bytes(document) == canonical_bytes(_reordered(document))


@given(document=_documents)
@example(document={"n": MAX_SAFE_INT})
@example(document={"n": -MAX_SAFE_INT})
@_property
def test_canonical_bytes_accepts_every_integer_within_the_safe_range(
    document: dict[str, object],
) -> None:
    """Every integer within the JCS-safe magnitude, at any depth, serializes without error."""
    canonical_bytes(document)


@st.composite
def _document_with_one_unsafe_integer(draw: st.DrawFn) -> dict[str, object]:
    """Embed one integer beyond the JCS-safe magnitude somewhere in a generated document.

    Args:
        draw: The Hypothesis draw function.

    Returns:
        A document built from :data:`_documents` with one extra key whose
        value is, is a list containing, or is a nested mapping containing,
        an integer whose magnitude exceeds :data:`MAX_SAFE_INT`.
    """
    base = draw(_documents)
    magnitude = MAX_SAFE_INT + 1 + draw(st.integers(min_value=0, max_value=10**6))
    unsafe = magnitude if draw(st.booleans()) else -magnitude
    placement = draw(st.sampled_from(["top_level", "inside_a_list", "inside_a_mapping"]))
    document = dict(base)
    if placement == "top_level":
        document["unsafe"] = unsafe
    elif placement == "inside_a_list":
        document["unsafe"] = [unsafe]
    else:
        document["unsafe"] = {"nested": unsafe}
    return document


@given(document=_document_with_one_unsafe_integer())
@example(document={"unsafe": MAX_SAFE_INT + 1})
@example(document={"unsafe": -(MAX_SAFE_INT + 1)})
@_property
def test_canonical_bytes_refuses_any_integer_beyond_the_safe_range(
    document: dict[str, object],
) -> None:
    """An integer beyond the JCS-safe magnitude, at any depth, is refused."""
    with pytest.raises(ValueError, match="JCS safe range"):
        canonical_bytes(document)


@given(call_count=st.integers(min_value=2, max_value=50))
@_property
def test_uuid7_calls_carry_the_correct_bits_and_their_timestamps_never_go_backwards(
    call_count: int,
) -> None:
    """Every uuid7() is version 7 with RFC 9562 variant bits, and its timestamp never regresses.

    Two ids minted within the same millisecond carry independently-random
    bits below the timestamp, so only the 48-bit timestamp itself — not the
    full 128-bit integer — is guaranteed to hold still or advance from one
    call to the next.
    """
    ids = [uuid7() for _ in range(call_count)]

    for value in ids:
        assert value.version == 7
        assert (value.int >> 62) & 0b11 == 0b10

    timestamps = [value.int >> 80 for value in ids]
    assert all(earlier <= later for earlier, later in itertools.pairwise(timestamps))
