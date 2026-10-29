"""Bodies shared across the API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

__all__ = ["Health", "Page", "ProblemBody", "page_of"]


class Health(BaseModel):
    """The liveness answer."""

    status: str
    instance_id: str
    version: str


class Page[T](BaseModel):
    """One page of items and the cursor of the next page."""

    items: list[T]
    next_cursor: str | None = None


class ProblemBody(BaseModel):
    """An RFC 9457 problem document."""

    type: str
    title: str
    status: int
    detail: str
    code: str
    context: dict[str, Any]
    instance: str | None = None


def page_of[M: BaseModel](
    model: type[M], rows: list[dict[str, Any]], next_cursor: str | None
) -> Page[M]:
    """Build a page of ``model`` from rendered rows."""
    return Page[M](items=[model.model_validate(row) for row in rows], next_cursor=next_cursor)
