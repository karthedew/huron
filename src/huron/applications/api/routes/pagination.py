"""Cursor query parameters shared by every list route."""

from __future__ import annotations

from typing import Annotated

from fastapi import Query

__all__ = ["Cursor", "Limit"]

Cursor = Annotated[str | None, Query(description="The next_cursor of the previous page.")]
Limit = Annotated[int | None, Query(ge=1, le=500, description="Page size, 1 to 500.")]
