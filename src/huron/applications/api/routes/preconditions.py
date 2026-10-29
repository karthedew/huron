"""``If-Match`` parsing and ``ETag`` rendering for versioned collections."""

from __future__ import annotations

import re
from typing import Annotated

from fastapi import Header, Response

from huron.pkg.errors import HuronError, register

__all__ = ["IfMatch", "PreconditionRequired", "etag", "expected_version", "set_etag"]

PRECONDITION_REQUIRED = register("PRECONDITION_REQUIRED", 428, "Precondition required")

_ETAG = re.compile(r'"(\d{1,9})"')


class PreconditionRequired(HuronError):
    """A write to a collection without a usable ``If-Match`` header."""

    error_code = PRECONDITION_REQUIRED


def etag(version: int) -> str:
    """The strong ETag of a collection version."""
    return f'"{version}"'


def set_etag(response: Response, version: int) -> None:
    """Attach the collection version's ETag to ``response``."""
    response.headers["ETag"] = etag(version)


def expected_version(if_match: str | None) -> int:
    """The version an ``If-Match`` header names; exactly one quoted integer."""
    if if_match is None:
        raise PreconditionRequired("writes to a collection need an If-Match header")
    matched = _ETAG.fullmatch(if_match.strip())
    if matched is None:
        raise PreconditionRequired(
            'If-Match must be one quoted version, for example "3"', {"if_match": if_match}
        )
    return int(matched.group(1))


IfMatch = Annotated[str | None, Header(alias="If-Match")]
