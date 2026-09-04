"""Idempotency and optimistic-concurrency headers shared by v1 endpoints.

``IdempotencyHeader`` is the ``Idempotency-Key`` a creating POST requires:
replaying a key with the same request returns the resource the first call
created, and reusing it with a different request is refused, so a retried
create can never make two of something. ``IfMatchHeader`` is the
``If-Match`` a PATCH requires: it carries the resource ``version`` the
caller last read, either quoted as an entity tag (``"3"`` or ``W/"3"``) or
as a bare integer, and a write against any other version is refused with
412 rather than overwriting an edit the caller never saw.
"""

from __future__ import annotations

import re
from typing import Annotated

from fastapi import Header
from fastapi.exceptions import RequestValidationError

IdempotencyHeader = Annotated[str, Header(alias="Idempotency-Key", min_length=1)]
IfMatchHeader = Annotated[str, Header(alias="If-Match")]

#: A resource version, either a bare integer or quoted as a strong or weak
#: entity tag. The bare form predates the entity-tag form and stays accepted
#: because existing callers send it; new callers should prefer the quoted
#: form RFC 9110 defines for ``If-Match``. The digit run is capped at 19
#: characters — more than an int64 version column can ever hold — so an
#: absurdly long header fails the match instead of reaching ``int()``, whose
#: own digit-length ceiling (``sys.int_max_str_digits``) raises an uncaught
#: ``ValueError`` rather than the 422 a malformed header should produce.
_IF_MATCH = re.compile(r'(?:W/)?"(?P<quoted>\d{1,19})"|(?P<bare>\d{1,19})')


def expected_version(if_match: str) -> int:
    """Return the resource version an ``If-Match`` header names.

    The header carries the integer ``version`` a view reported, either
    bare or wrapped as a strong or weak entity tag (``"3"``, ``W/"3"`` or
    ``3``). A header that is none of those shapes never named a version at
    all, so it is a schema violation rather than something a stored version
    could match or fail to match; a header that does name a version but the
    wrong one is a separate, later check against the stored record.

    Args:
        if_match: The raw ``If-Match`` header value.

    Returns:
        The version the caller expects the resource to be at.

    Raises:
        RequestValidationError: If the header is not ``"N"``, ``W/"N"`` or
            a bare integer.
    """
    match = _IF_MATCH.fullmatch(if_match)
    if match is None:
        raise RequestValidationError(
            [
                {
                    "type": "string_pattern_mismatch",
                    "loc": ("header", "if-match"),
                    "msg": 'If-Match must name a resource version: "N", W/"N", or a bare integer',
                    "input": if_match,
                }
            ]
        )
    return int(match["quoted"] or match["bare"])
