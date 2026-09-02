"""The paged-collection envelope and the keyset cursor that walks it.

A page is a window over an ordering, so the cursor is the ordering key of the
last item in the window rather than an offset: an insert between two requests
shifts an offset and does not shift a key. The window is applied here, at the
HTTP boundary, because the hierarchy lives in process dictionaries and the
query methods return the whole ordered sequence; when the hierarchy gets a
persistent store, ``limit`` and ``after`` descend into those methods and this
module becomes the encoder alone.
"""

from __future__ import annotations

from base64 import urlsafe_b64decode, urlsafe_b64encode
from collections.abc import Callable, Sequence
from typing import Annotated

from fastapi import Query
from pydantic import BaseModel

from huron.pkg.catalog.errors import InvalidCursor

#: Bumped when the meaning of an encoded key changes, so a cursor minted by an
#: older deployment is refused rather than silently misread.
CURSOR_VERSION = "v1"

_KEY_SEPARATOR = "\x1f"

PageLimit = Annotated[int, Query(ge=1, le=200)]
PageCursor = Annotated[str | None, Query(pattern=r"^v1:[A-Za-z0-9_-]+$")]


class Page[ItemT: BaseModel](BaseModel):
    """One window over an ordered collection, and the way to the next.

    ``next_cursor`` is ``null`` if and only if this window reaches the end of
    the collection. It is never a promise that the collection is small; it is
    the statement that there is nothing after ``items``.
    """

    items: list[ItemT]
    next_cursor: str | None


def encode_cursor(key: tuple[str, ...]) -> str:
    packed = urlsafe_b64encode(_KEY_SEPARATOR.join(key).encode()).decode().rstrip("=")
    return f"{CURSOR_VERSION}:{packed}"


def decode_cursor(cursor: str) -> tuple[str, ...]:
    version, _, packed = cursor.partition(":")
    if version != CURSOR_VERSION:
        raise InvalidCursor(f"unsupported cursor version: {version}")
    try:
        decoded = urlsafe_b64decode(packed + "=" * (-len(packed) % 4)).decode()
    except (ValueError, UnicodeDecodeError) as exc:
        raise InvalidCursor("cursor is not a keyset position") from exc
    return tuple(decoded.split(_KEY_SEPARATOR))


def paginate[RecordT, ViewT: BaseModel](
    records: Sequence[RecordT],
    view: type[ViewT],
    *,
    key: Callable[[RecordT], tuple[str, ...]],
    limit: int,
    after: str | None,
) -> Page[ViewT]:
    """Window ``records`` after ``after``, at most ``limit`` of them.

    ``records`` must already be ordered by ``key`` before this is called,
    whether by the repository's query method or by the caller sorting the
    sequence itself.
    """
    remaining = list(records)
    if after is not None:
        cutoff = decode_cursor(after)
        remaining = [record for record in remaining if key(record) > cutoff]
    window = remaining[:limit]
    return Page(
        items=[view.model_validate(record) for record in window],
        next_cursor=encode_cursor(key(window[-1])) if window and len(remaining) > limit else None,
    )
