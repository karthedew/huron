"""Cursor encoding and page-size bounds."""

import base64
import json

import pytest
from hypothesis import given
from hypothesis import strategies as st

from huron.pkg.paging import InvalidCursor, Page, clamp_limit, decode_cursor, encode_cursor

scalars = st.one_of(st.text(), st.integers(), st.booleans(), st.none())


@given(st.lists(scalars, max_size=4))
def test_cursor_round_trips(values: list[object]) -> None:
    assert decode_cursor(encode_cursor(values)) == tuple(values)  # type: ignore[arg-type]


def test_cursor_from_another_version_is_refused() -> None:
    other = base64.urlsafe_b64encode(json.dumps([2, "a"]).encode()).decode()
    with pytest.raises(InvalidCursor) as raised:
        decode_cursor(other)
    assert raised.value.status == 400


@pytest.mark.parametrize("text", ["!!!", "bm90IGpzb24", base64.urlsafe_b64encode(b"{}").decode()])
def test_unreadable_cursor_is_refused(text: str) -> None:
    with pytest.raises(InvalidCursor):
        decode_cursor(text)


@pytest.mark.parametrize(
    ("value", "expected"), [(None, 100), (0, 1), (-5, 1), (50, 50), (500, 500), (10_000, 500)]
)
def test_limits_are_clamped(value: int | None, expected: int) -> None:
    assert clamp_limit(value) == expected


def test_empty_page_has_no_next_cursor() -> None:
    page: Page[int] = Page()
    assert tuple(page.items) == ()
    assert page.next_cursor is None
