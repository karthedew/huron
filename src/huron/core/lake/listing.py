"""Ordering and cursors shared by catalog, namespace and collection listings."""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from huron.pkg.paging import InvalidCursor, Page, decode_cursor, encode_cursor

__all__ = ["ListOrder", "Listed", "Position", "SortDirection", "SortField"]

type Position = str | tuple[str, str] | None


class SortField(StrEnum):
    """Recorded fields available for browsing in a consistent order."""

    NAME = "name"
    CREATED_BY = "created_by"
    CREATED_AT = "created_at"


class SortDirection(StrEnum):
    """The direction of both the primary field and its name tie-breaker."""

    ASC = "asc"
    DESC = "desc"


class Listed(Protocol):
    """The immutable recorded values needed to order a browse listing."""

    @property
    def name(self) -> str:
        """The unique name within the listing."""
        ...

    @property
    def created_by(self) -> str:
        """The subject that created the record."""
        ...

    @property
    def created_at(self) -> datetime:
        """The instant at which the record was created."""
        ...


@dataclass(frozen=True, slots=True)
class ListOrder:
    """Stable global ordering with cursors bound to the field and direction.

    The default keeps the existing single-name cursor. Other orders carry both their
    specification and the last record's field and name, so changing sort rejects a cursor.
    Names uniquely break ties within each of the three listing families.
    """

    field: SortField = SortField.NAME
    direction: SortDirection = SortDirection.ASC

    def key(self, row: Listed) -> tuple[str, str]:
        """The recorded field and unique name, with instants normalized to UTC."""
        if self.field is SortField.CREATED_AT:
            value = row.created_at.astimezone(UTC).isoformat(timespec="microseconds")
        else:
            value = row.name if self.field is SortField.NAME else row.created_by
        return value, row.name

    def after(self, cursor: str | None) -> Position:
        """Read a cursor for this order; reject other orders and malformed positions."""
        if cursor is None:
            return None
        values = decode_cursor(cursor)
        if self == ListOrder():
            if len(values) == 1 and isinstance(values[0], str):
                return values[0]
        elif len(values) == 5 and values[:3] == ("listing", self.field, self.direction):
            value, name = values[3:]
            if isinstance(value, str) and isinstance(name, str):
                return self._position(value, name)
        raise InvalidCursor("the cursor does not match the listing order")

    def position(self, after: Position) -> tuple[str, str] | None:
        """Normalize a legacy name position for adapters that compare pairs."""
        return (after, after) if isinstance(after, str) else after

    def rows[T: Listed](self, rows: Iterable[T], after: Position, limit: int) -> list[T]:
        """Order filtered records globally before taking the requested page."""
        descending = self.direction is SortDirection.DESC
        ordered = sorted(rows, key=self.key, reverse=descending)
        position = self.position(after)
        if position is not None:
            ordered = [row for row in ordered if self._follows(self.key(row), position)]
        return ordered[:limit]

    def page[T](self, rows: Sequence[T], size: int, record: Callable[[T], Listed]) -> Page[T]:
        """Return the requested rows and a cursor only when a further record was fetched."""
        items = tuple(rows[:size])
        if len(rows) <= size:
            return Page(items)
        value, name = self.key(record(items[-1]))
        values = (
            [name] if self == ListOrder() else ["listing", self.field, self.direction, value, name]
        )
        return Page(items, encode_cursor(values))

    def _position(self, value: str, name: str) -> tuple[str, str]:
        if self.field is SortField.CREATED_AT:
            try:
                instant = datetime.fromisoformat(value)
                if instant.tzinfo is None:
                    raise ValueError("a cursor instant needs a timezone")
                value = instant.astimezone(UTC).isoformat(timespec="microseconds")
            except (ValueError, OverflowError) as error:
                raise InvalidCursor("the cursor has a creation time that is not valid") from error
        if self.field is SortField.NAME and value != name:
            raise InvalidCursor("the cursor has inconsistent name values")
        return value, name

    def _follows(self, key: tuple[str, str], position: tuple[str, str]) -> bool:
        return key < position if self.direction is SortDirection.DESC else key > position
