"""Parameterized PostgreSQL keyset ordering for browse listings."""

from dataclasses import dataclass
from datetime import datetime

from huron.core.lake.listing import ListOrder, Position, SortDirection, SortField

__all__ = ["ListingSql"]


@dataclass(frozen=True, slots=True)
class ListingSql:
    """A predicate and ordering built only from the closed listing field enums."""

    order: ListOrder
    parameter: int

    def clause(self) -> str:
        """The keyset predicate, global ordering and limit for three bound parameters."""
        field = self.order.field.value
        column = field if self.order.field is SortField.CREATED_AT else f'{field} collate "C"'
        kind = "timestamptz" if self.order.field is SortField.CREATED_AT else "text"
        operator = "<" if self.order.direction is SortDirection.DESC else ">"
        direction = self.order.direction.value
        first, second = self.parameter, self.parameter + 1
        return (
            f' and (${first}::{kind} is null or ({column}, name collate "C")'
            f' {operator} (${first}::{kind}, ${second}::text collate "C"))'
            f' order by {column} {direction}, name collate "C" {direction}'
            f" limit ${self.parameter + 2}"
        )

    def values(self, after: Position, limit: int) -> tuple[str | datetime | None, str | None, int]:
        """Bind values separately from SQL, converting creation instants for asyncpg."""
        position = self.order.position(after)
        if position is None:
            return None, None, limit
        value, name = position
        if self.order.field is SortField.CREATED_AT:
            return datetime.fromisoformat(value), name, limit
        return value, name, limit
