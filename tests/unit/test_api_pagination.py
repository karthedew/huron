"""The keyset cursor and the generic page it walks, independent of any one resource.

Covers cursor encoding, decoding, and window slicing, plus the boundary
that keeps ``Page`` from ever being filled straight from a stored record.
"""

from __future__ import annotations

from base64 import urlsafe_b64encode
from dataclasses import dataclass
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from huron.applications.api.routes.v1.pagination import (
    Page,
    after_key,
    decode_cursor,
    encode_cursor,
    page,
    paginate,
    slug_cursor_key,
)
from huron.applications.api.errors import InvalidCursor
from huron.core.catalog.types import Window

pytestmark = pytest.mark.unit


@dataclass
class _Record:
    """A minimal stand-in for a stored record, carrying just the field ``_key`` reads."""

    value: str


class _View(BaseModel):
    """The read model ``paginate`` renders each ``_Record`` into, via ``from_attributes``."""

    model_config = ConfigDict(from_attributes=True)

    value: str


def _key(item: _Record) -> tuple[str, ...]:
    """A ``_Record``'s keyset position: its ``value`` field as a one-element tuple."""
    return (item.value,)


def test_paginate_returns_a_null_cursor_when_the_window_reaches_the_end() -> None:
    """A window that reaches the end of the collection returns every item and a null cursor."""
    records = [_Record("a"), _Record("b")]
    page = paginate(records, _View, key=_key, limit=50, after=None)
    assert [item.value for item in page.items] == ["a", "b"]
    assert page.next_cursor is None


def test_paginate_returns_the_empty_page_for_an_empty_collection() -> None:
    """An empty collection paginates to an empty page with a null cursor."""
    page = paginate([], _View, key=_key, limit=50, after=None)
    assert page.items == []
    assert page.next_cursor is None


def test_paginate_slices_the_window_and_encodes_the_cursor_of_the_last_item() -> None:
    """A limit smaller than the collection returns just that many items and cursors the last."""
    records = [_Record("a"), _Record("b"), _Record("c")]
    page = paginate(records, _View, key=_key, limit=2, after=None)
    assert [item.value for item in page.items] == ["a", "b"]
    assert page.next_cursor == encode_cursor(("b",))


def test_paginate_resumes_after_a_cursor_and_terminates_at_the_last_item() -> None:
    """Resuming from a cursor returns the remaining items, ending with a null cursor."""
    records = [_Record("a"), _Record("b"), _Record("c")]
    first = paginate(records, _View, key=_key, limit=2, after=None)
    second = paginate(records, _View, key=_key, limit=2, after=first.next_cursor)
    assert [item.value for item in second.items] == ["c"]
    assert second.next_cursor is None


def test_encode_and_decode_cursor_round_trip_a_multi_part_key() -> None:
    """A multi-part key round-trips through encode_cursor and decode_cursor unchanged."""
    assert decode_cursor(encode_cursor(("astro", "0123"))) == ("astro", "0123")


def test_decode_cursor_rejects_an_unsupported_version() -> None:
    """A cursor with an unrecognized version prefix raises InvalidCursor."""
    with pytest.raises(InvalidCursor, match="unsupported cursor version"):
        decode_cursor("v2:whatever")


def test_decode_cursor_rejects_a_payload_that_is_not_valid_utf8() -> None:
    """A v1 cursor whose decoded payload is not valid UTF-8 raises InvalidCursor."""
    packed = urlsafe_b64encode(b"\xff\xfe").decode().rstrip("=")
    with pytest.raises(InvalidCursor, match="not a keyset position"):
        decode_cursor(f"v1:{packed}")


def test_page_has_no_from_attributes_and_cannot_be_filled_from_a_bare_object() -> None:
    """An object with matching attributes still fails validation without ``from_attributes``.

    ``Page`` is constructed field by field, never validated from a stored
    record; an object with matching attributes must still fail validation,
    since only a dict or another model would be accepted without the config.
    """
    bare = SimpleNamespace(items=[], next_cursor=None)
    with pytest.raises(ValidationError):
        Page[_View].model_validate(bare)


def test_page_encodes_the_cursor_of_the_last_item_when_more_items_follow() -> None:
    """A window whose store reports more items encodes the last item's key as next_cursor."""
    window = Window(items=[_Record("a"), _Record("b")], has_more=True)
    result = page(window, _View, key=_key)
    assert [item.value for item in result.items] == ["a", "b"]
    assert result.next_cursor == encode_cursor(("b",))


def test_page_returns_a_null_cursor_when_no_further_item_follows() -> None:
    """A window whose store reports no further item returns a null next_cursor."""
    window = Window(items=[_Record("a"), _Record("b")], has_more=False)
    result = page(window, _View, key=_key)
    assert result.next_cursor is None


def test_page_over_an_empty_window_returns_an_empty_page() -> None:
    """An empty window returns an empty page with a null cursor."""
    window = Window[_Record](items=[], has_more=False)
    result = page(window, _View, key=_key)
    assert result.items == []
    assert result.next_cursor is None


def test_after_key_returns_none_for_a_none_cursor() -> None:
    """A None cursor decodes to None, the start of the collection."""
    assert after_key(None) is None


def test_after_key_round_trips_what_encode_cursor_was_given() -> None:
    """A cursor decodes to exactly the key encode_cursor was given."""
    assert after_key(encode_cursor(("astro", "0123"))) == ("astro", "0123")


def test_slug_cursor_key_returns_none_for_a_none_cursor() -> None:
    """A None cursor decodes to None, the start of the collection."""
    assert slug_cursor_key(None) is None


def test_slug_cursor_key_decodes_a_valid_slug_and_id() -> None:
    """A two-part cursor of a slug and a UUID string decodes to the slug and the UUID."""
    dataset_id = uuid4()
    cursor = encode_cursor(("astro", str(dataset_id)))
    assert slug_cursor_key(cursor) == ("astro", dataset_id)


def test_slug_cursor_key_rejects_a_one_part_cursor() -> None:
    """A cursor naming only a slug, with no id, raises InvalidCursor."""
    with pytest.raises(InvalidCursor, match="expected a slug and an id"):
        slug_cursor_key(encode_cursor(("astro",)))


def test_slug_cursor_key_rejects_a_three_part_cursor() -> None:
    """A cursor naming three parts raises InvalidCursor."""
    with pytest.raises(InvalidCursor, match="expected a slug and an id"):
        slug_cursor_key(encode_cursor(("astro", str(uuid4()), "extra")))


def test_slug_cursor_key_rejects_a_non_uuid_second_part() -> None:
    """A two-part cursor whose second part is not a valid UUID raises InvalidCursor."""
    with pytest.raises(InvalidCursor, match="not a valid UUID"):
        slug_cursor_key(encode_cursor(("astro", "not-a-uuid")))
