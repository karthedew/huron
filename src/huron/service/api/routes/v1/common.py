"""Shared helpers for v1 endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import Header

from huron.pkg.catalog.errors import PreconditionFailed
from huron.service.api.repository import _jsonable

if TYPE_CHECKING:
    from collections.abc import Sequence

IdempotencyHeader = Annotated[str, Header(alias="Idempotency-Key", min_length=1)]
IfMatchHeader = Annotated[str, Header(alias="If-Match")]


def page(items: Sequence[object], limit: int) -> dict[str, object]:
    selected = list(items)[: max(1, min(limit, 200))]
    return {
        "items": [_jsonable(item) for item in selected],
        "next_cursor": None,
        "count": len(selected),
    }


def jsonable(item: object) -> dict[str, object]:
    return _jsonable(item)


def expected_version(if_match: str) -> int:
    try:
        return int(if_match.strip('W/"'))
    except ValueError as exc:
        raise PreconditionFailed("If-Match must contain the integer resource version") from exc
