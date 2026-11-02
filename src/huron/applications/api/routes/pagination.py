"""Cursor query parameters shared by every list route."""

from __future__ import annotations

from typing import Annotated

from fastapi import Query

from huron.core.lake.listing import SortDirection, SortField

__all__ = ["Cursor", "Limit", "Order", "Sort"]

Cursor = Annotated[str | None, Query(description="The next_cursor of the previous page.")]
Limit = Annotated[int | None, Query(ge=1, le=500, description="Page size, 1 to 500.")]

Sort = Annotated[SortField, Query(description="Global sort field; names break ties.")]
Order = Annotated[SortDirection, Query(description="Sort direction, also used for name ties.")]
