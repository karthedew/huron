"""Idempotency and optimistic-concurrency headers shared by v1 endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import Header

from huron.pkg.catalog.errors import PreconditionFailed

IdempotencyHeader = Annotated[str, Header(alias="Idempotency-Key", min_length=1)]
IfMatchHeader = Annotated[str, Header(alias="If-Match")]


def expected_version(if_match: str) -> int:
    try:
        return int(if_match.strip('W/"'))
    except ValueError as exc:
        raise PreconditionFailed("If-Match must contain the integer resource version") from exc
