"""Idempotency and optimistic-concurrency headers shared by v1 endpoints.

``IdempotencyHeader`` is the ``Idempotency-Key`` a creating POST requires:
replaying a key with the same request returns the resource the first call
created, and reusing it with a different request is refused, so a retried
create can never make two of something. ``IfMatchHeader`` is the
``If-Match`` a PATCH requires: it carries the ``version`` the caller last
read, and a write against any other version is refused with 412 rather
than overwriting an edit the caller never saw.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Header

from huron.pkg.catalog.errors import PreconditionFailed

IdempotencyHeader = Annotated[str, Header(alias="Idempotency-Key", min_length=1)]
IfMatchHeader = Annotated[str, Header(alias="If-Match")]


def expected_version(if_match: str) -> int:
    """Return the resource version an ``If-Match`` header names.

    The header carries the integer ``version`` a view reported, either
    bare or wrapped as an entity tag (``"3"`` or ``W/"3"``); the wrapping
    is stripped before parsing. A header that does not reduce to an
    integer can never match any version, so it is refused with the same
    412 a stale one gets.

    Args:
        if_match: The raw ``If-Match`` header value.

    Returns:
        The version the caller expects the resource to be at.

    Raises:
        PreconditionFailed: If the header does not contain an integer
            version.
    """
    try:
        return int(if_match.strip('W/"'))
    except ValueError as exc:
        raise PreconditionFailed("If-Match must contain the integer resource version") from exc
