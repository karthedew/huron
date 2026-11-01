"""Canonical JSON bytes (RFC 8785) and stable document hashes.

RFC 8785 limits integers to the I-JSON domain (magnitude below 2^53). Huron's documents are not
so limited: a client may send any integer, and PostgreSQL's ``jsonb`` answers a large float such
as ``-1e31`` as the integer ``-10000000000000000000000000000000``. Every integer is therefore
written with its exact decimal digits, which is what RFC 8785 writes inside that domain, so the
bytes of every document RFC 8785 accepts are unchanged. Everything else follows RFC 8785.
"""

from __future__ import annotations

import hashlib
import math
from io import BytesIO
from typing import IO, Any

import rfc8785

__all__ = ["NotCanonicalizable", "canonical_bytes", "document_sha256"]


class NotCanonicalizable(ValueError):
    """A value JSON cannot hold: NaN or infinity, a key that is not a string, a lone surrogate."""


def canonical_bytes(document: Any) -> bytes:
    """Serialize ``document`` as RFC 8785 canonical JSON, integers of any size exactly.

    Raises :class:`NotCanonicalizable` for a value JSON cannot hold.
    """
    sink = BytesIO()
    _write(document, sink)
    return sink.getvalue()


def document_sha256(document: Any) -> str:
    """Return the lowercase hex sha256 of the canonical bytes of ``document``."""
    return hashlib.sha256(canonical_bytes(document)).hexdigest()


def _write(value: Any, sink: IO[bytes]) -> None:
    if isinstance(value, dict):
        _write_object(value, sink)
    elif isinstance(value, list | tuple):
        sink.write(b"[")
        for index, item in enumerate(value):
            if index:
                sink.write(b",")
            _write(item, sink)
        sink.write(b"]")
    elif isinstance(value, int) and not isinstance(value, bool):
        sink.write(_integer(value))
    else:
        sink.write(_scalar(value))


def _write_object(value: dict[Any, Any], sink: IO[bytes]) -> None:
    """Members ordered by the UTF-16 code units of their keys (RFC 8785 section 3.2.3)."""
    try:
        members = sorted(value.items(), key=lambda member: member[0].encode("utf-16be"))
    except AttributeError as error:
        raise NotCanonicalizable("object keys must be strings") from error
    except UnicodeEncodeError as error:
        raise NotCanonicalizable("an object key holds a lone surrogate") from error
    sink.write(b"{")
    for index, (key, item) in enumerate(members):
        if index:
            sink.write(b",")
        sink.write(_scalar(key))
        sink.write(b":")
        _write(item, sink)
    sink.write(b"}")


def _integer(value: int) -> bytes:
    try:
        return str(int(value)).encode("ascii")
    except ValueError as error:  # past sys.get_int_max_str_digits()
        raise NotCanonicalizable("an integer has too many digits") from error


def _scalar(value: Any) -> bytes:
    """A string, float, boolean or null, as RFC 8785 writes it."""
    if not isinstance(value, str | float | bool) and value is not None:
        raise NotCanonicalizable(f"{type(value).__name__} is not a JSON value")
    if isinstance(value, float) and not math.isfinite(value):
        raise NotCanonicalizable(f"{value} is not a JSON number")
    try:
        return bytes(rfc8785.dumps(value))
    except rfc8785.CanonicalizationError as error:
        raise NotCanonicalizable("a string holds a lone surrogate") from error
