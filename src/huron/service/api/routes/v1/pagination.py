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
    """Return the opaque cursor that names the position just after ``key``.

    The cursor is ``CURSOR_VERSION``, a colon, then the key parts joined by
    a separator and URL-safe base64 encoded without padding - the shape
    ``PageCursor`` accepts back. It is opaque to clients by contract: the
    only thing a client may do with one is pass it as ``after``.

    Args:
        key: The ordering key of the last item in a window, as the
            ``key`` callable given to ``paginate`` produces it.

    Returns:
        The versioned, URL-safe cursor string.
    """
    packed = urlsafe_b64encode(_KEY_SEPARATOR.join(key).encode()).decode().rstrip("=")
    return f"{CURSOR_VERSION}:{packed}"


def decode_cursor(cursor: str) -> tuple[str, ...]:
    """Return the ordering key an ``encode_cursor`` cursor stands for.

    A cursor from a deployment with a different ``CURSOR_VERSION`` is
    refused rather than misread, and so is any value that does not decode
    to a key: both are the caller's ``INVALID_CURSOR`` 400, never a page
    that silently starts somewhere else.

    Args:
        cursor: The ``after`` value a client sent back.

    Returns:
        The key parts, in the order ``encode_cursor`` was given them.

    Raises:
        InvalidCursor: If the version prefix is not ``CURSOR_VERSION``, or
            the remainder is not the base64 of a key.
    """
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
    sequence itself. The window is every record whose key sorts after the
    cursor's, cut to ``limit``; ``next_cursor`` names the last record in
    the window, and only when a record follows it, so a page that reaches
    the end of the collection says so with ``null``.

    Args:
        records: The whole collection, already ordered by ``key``.
        view: The response model each record in the window is rendered
            through, via ``model_validate``.
        key: Maps a record to its ordering key: a tuple of strings that is
            unique per record and compares in the collection's order.
        limit: The most items the page may hold; at least one.
        after: The cursor of the previous page, or ``None`` to start from
            the beginning of the collection.

    Returns:
        The rendered window and the cursor to continue from, ``None`` if
        nothing follows.
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
