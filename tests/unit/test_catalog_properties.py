"""Generated properties for canonical JSON and monotonic UUID timestamps."""

from __future__ import annotations

import hashlib
import itertools

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

from huron.core.foundation.canonical import MAX_SAFE_INT, canonical_bytes, content_identity
from huron.core.foundation.identifiers import uuid7

pytestmark = pytest.mark.unit

_property = settings(deadline=None, max_examples=200)


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
    """Reordered documents retain canonical bytes and their SHA-256 content identity."""
    encoded = canonical_bytes(document)
    assert encoded == canonical_bytes(_reordered(document))
    assert content_identity(document) == content_identity(_reordered(document))
    assert content_identity(document) == hashlib.sha256(encoded).hexdigest()


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
