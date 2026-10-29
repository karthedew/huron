"""Opaque cursors and pages for keyset pagination."""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from huron.pkg.errors import HuronError, register

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    "CURSOR_VERSION",
    "DEFAULT_LIMIT",
    "MAXIMUM_LIMIT",
    "InvalidCursor",
    "Page",
    "clamp_limit",
    "decode_cursor",
    "encode_cursor",
]

CURSOR_VERSION = 1
DEFAULT_LIMIT = 100
MAXIMUM_LIMIT = 500

INVALID_CURSOR = register("INVALID_CURSOR", 400, "Invalid cursor")

type CursorValue = str | int | float | bool | None


class InvalidCursor(HuronError):
    """A cursor that this version did not produce."""

    error_code = INVALID_CURSOR


@dataclass(frozen=True, slots=True)
class Page[T]:
    """One page of results and the cursor for the next page, if any."""

    items: Sequence[T] = field(default_factory=tuple)
    next_cursor: str | None = None


def encode_cursor(values: Sequence[CursorValue]) -> str:
    """Encode the sort key of the last item of a page as an opaque cursor."""
    payload = json.dumps([CURSOR_VERSION, *values], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[CursorValue, ...]:
    """Decode a cursor produced by :func:`encode_cursor`; raises :class:`InvalidCursor`."""
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        decoded = json.loads(base64.urlsafe_b64decode(padded.encode()))
    except (binascii.Error, ValueError, UnicodeDecodeError) as error:
        raise InvalidCursor("cursor is not readable", {"cursor": cursor}) from error
    if not isinstance(decoded, list) or not decoded or decoded[0] != CURSOR_VERSION:
        raise InvalidCursor("cursor version is not supported", {"cursor": cursor})
    return tuple(decoded[1:])


def clamp_limit(
    value: int | None, default: int = DEFAULT_LIMIT, maximum: int = MAXIMUM_LIMIT
) -> int:
    """Return a page size within ``1..maximum``, ``default`` when ``value`` is ``None``."""
    if value is None:
        return default
    return max(1, min(value, maximum))
