"""Stable browse ordering and its cursor boundaries."""

from dataclasses import replace
from datetime import timedelta, timezone

import pytest

from huron.core.lake.listing import ListOrder, SortDirection, SortField
from huron.pkg.paging import InvalidCursor, decode_cursor, encode_cursor
from tests.contract.suite import catalog, organization
from tests.support.clock import START


@pytest.mark.parametrize("field", list(SortField))
@pytest.mark.parametrize("direction", list(SortDirection))
def test_every_order_pages_all_records_and_breaks_ties_by_name(
    field: SortField, direction: SortDirection
) -> None:
    org = organization()
    records = [
        replace(
            catalog(org, org.id, name), created_by=creator, created_at=START + timedelta(days=day)
        )
        for name, creator, day in [("alpha", "zoe", 3), ("bravo", "amy", 1), ("charlie", "amy", 1)]
    ]
    order = ListOrder(field, direction)
    expected = (
        ["alpha", "bravo", "charlie"] if field is SortField.NAME else ["bravo", "charlie", "alpha"]
    )
    if direction is SortDirection.DESC:
        expected.reverse()
    names = []
    cursor = None
    for _ in records:
        rows = order.rows(reversed(records), order.after(cursor), 2)
        page = order.page(rows, 1, lambda item: item)
        names.extend(row.name for row in page.items)
        cursor = page.next_cursor
    assert names == expected
    assert cursor is None
    assert order.rows([], None, 1) == []
    assert order.page([], 1, lambda item: item).items == ()


def test_default_order_keeps_existing_name_cursors() -> None:
    order = ListOrder()
    org = organization()
    first, second = catalog(org, org.id, "alpha"), catalog(org, org.id, "bravo")
    page = order.page([first, second], 1, lambda item: item)
    assert page.next_cursor == encode_cursor(["alpha"])
    assert order.after(page.next_cursor) == "alpha"
    assert order.position("alpha") == ("alpha", "alpha")
    assert order.position(None) is None


@pytest.mark.parametrize("field", list(SortField))
@pytest.mark.parametrize("direction", list(SortDirection))
def test_a_cursor_cannot_be_reused_for_another_sort(
    field: SortField, direction: SortDirection
) -> None:
    order = ListOrder(field, direction)
    org = organization()
    records = [catalog(org, org.id, "alpha"), catalog(org, org.id, "bravo")]
    cursor = order.page(records, 1, lambda item: item).next_cursor
    assert cursor is not None
    for other_field in SortField:
        for other_direction in SortDirection:
            other = ListOrder(other_field, other_direction)
            if other != order:
                with pytest.raises(InvalidCursor):
                    other.after(cursor)


@pytest.mark.parametrize(
    "values", [[], [1], ["alpha", "extra"], ["listing", "name", "desc", "a", "b"]]
)
def test_malformed_or_inconsistent_positions_are_rejected(values: list[str | int]) -> None:
    cursor = encode_cursor(values)
    with pytest.raises(InvalidCursor):
        ListOrder().after(cursor)
    with pytest.raises(InvalidCursor):
        ListOrder(SortField.NAME, SortDirection.DESC).after(cursor)


@pytest.mark.parametrize("value", ["not-a-date", "2026-01-01", "9999-12-31T23:00:00-12:00", 42])
def test_creation_cursors_require_a_valid_timezone_aware_instant(value: str | int) -> None:
    cursor = encode_cursor(["listing", "created_at", "asc", value, "alpha"])
    with pytest.raises(InvalidCursor):
        ListOrder(SortField.CREATED_AT).after(cursor)


def test_creation_order_compares_instants_in_utc() -> None:
    order = ListOrder(SortField.CREATED_AT)
    org = organization()
    row = replace(catalog(org, org.id), created_at=START.astimezone(timezone(timedelta(hours=-7))))
    value = START.isoformat(timespec="microseconds")
    assert order.key(row) == (value, row.name)
    cursor = encode_cursor(["listing", "created_at", "asc", row.created_at.isoformat(), row.name])
    assert order.after(cursor) == (value, row.name)
    page = order.page([row, row], 1, lambda item: item)
    assert page.next_cursor is not None
    assert decode_cursor(page.next_cursor)[3] == value
