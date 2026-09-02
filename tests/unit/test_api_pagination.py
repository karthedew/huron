"""The keyset cursor and the generic page it walks, independent of any one
resource: encoding, decoding, windowing, and the boundary that keeps ``Page``
from ever being filled straight from a stored record."""

from __future__ import annotations

from base64 import urlsafe_b64encode
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from huron.pkg.catalog.errors import InvalidCursor
from huron.service.api.routes.v1.pagination import Page, decode_cursor, encode_cursor, paginate

pytestmark = pytest.mark.unit


@dataclass
class _Record:
    value: str


class _View(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    value: str


def _key(item: _Record) -> tuple[str, ...]:
    return (item.value,)


def test_paginate_returns_a_null_cursor_when_the_window_reaches_the_end() -> None:
    records = [_Record("a"), _Record("b")]
    page = paginate(records, _View, key=_key, limit=50, after=None)
    assert [item.value for item in page.items] == ["a", "b"]
    assert page.next_cursor is None


def test_paginate_returns_the_empty_page_for_an_empty_collection() -> None:
    page = paginate([], _View, key=_key, limit=50, after=None)
    assert page.items == []
    assert page.next_cursor is None


def test_paginate_slices_the_window_and_encodes_the_cursor_of_the_last_item() -> None:
    records = [_Record("a"), _Record("b"), _Record("c")]
    page = paginate(records, _View, key=_key, limit=2, after=None)
    assert [item.value for item in page.items] == ["a", "b"]
    assert page.next_cursor == encode_cursor(("b",))


def test_paginate_resumes_after_a_cursor_and_terminates_at_the_last_item() -> None:
    records = [_Record("a"), _Record("b"), _Record("c")]
    first = paginate(records, _View, key=_key, limit=2, after=None)
    second = paginate(records, _View, key=_key, limit=2, after=first.next_cursor)
    assert [item.value for item in second.items] == ["c"]
    assert second.next_cursor is None


def test_encode_and_decode_cursor_round_trip_a_multi_part_key() -> None:
    assert decode_cursor(encode_cursor(("astro", "0123"))) == ("astro", "0123")


def test_decode_cursor_rejects_an_unsupported_version() -> None:
    with pytest.raises(InvalidCursor, match="unsupported cursor version"):
        decode_cursor("v2:whatever")


def test_decode_cursor_rejects_a_payload_that_is_not_valid_utf8() -> None:
    packed = urlsafe_b64encode(b"\xff\xfe").decode().rstrip("=")
    with pytest.raises(InvalidCursor, match="not a keyset position"):
        decode_cursor(f"v1:{packed}")


def test_page_has_no_from_attributes_and_cannot_be_filled_from_a_bare_object() -> None:
    """``Page`` is constructed field by field, never validated from a stored
    record; an object with matching attributes must still fail validation,
    since only a dict or another model would be accepted without the config."""
    bare = SimpleNamespace(items=[], next_cursor=None)
    with pytest.raises(ValidationError):
        Page[_View].model_validate(bare)
