"""Canonical JSON bytes, content identities and persistence-value conversion."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

import rfc8785

if TYPE_CHECKING:
    from _typeshed import DataclassInstance

MAX_SAFE_INT = 2**53 - 1
type JsonScalar = bool | int | float | str | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]


def _assert_ints_safe(value: object, path: str = "$") -> None:
    """Refuse integers outside the exact JCS range, including nested values.

    Args:
        value: The document or node being walked.
        path: Its JSONPath-style location for diagnostics.

    Raises:
        ValueError: If an integer exceeds the exact IEEE 754 range.
    """
    if isinstance(value, bool):
        return
    if isinstance(value, int):
        if abs(value) > MAX_SAFE_INT:
            raise ValueError(f"integer outside the JCS safe range at {path}: {value}")
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            _assert_ints_safe(child, f"{path}.{key}")
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, child in enumerate(value):
            _assert_ints_safe(child, f"{path}[{index}]")


def canonical_bytes(doc: Mapping[str, object]) -> bytes:
    """Return RFC 8785 bytes after checking every integer for exact representation.

    Args:
        doc: The JSON-compatible document.

    Returns:
        Canonical UTF-8 bytes, independent of key order and whitespace.
    """
    _assert_ints_safe(doc)
    return rfc8785.dumps(cast("Any", dict(doc)))


def content_identity(doc: Mapping[str, object]) -> str:
    """Hash a document's canonical bytes.

    Args:
        doc: The JSON-compatible document.

    Returns:
        Its lower-case hexadecimal SHA-256 identity.
    """
    return hashlib.sha256(canonical_bytes(doc)).hexdigest()


def jsonable_value(value: object) -> object:
    """Convert UUID and datetime fields to their persisted JSON representation.

    Args:
        value: The field value.

    Returns:
        A string for UUIDs and datetimes, otherwise the original value.
    """
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    return value


def jsonable(item: DataclassInstance) -> dict[str, object]:
    """Render a record using the stored UUID and UTC datetime encodings.

    Args:
        item: The dataclass record to render.

    Returns:
        Its fields in declaration order, with UUID and datetime values converted.
    """
    return {key: jsonable_value(value) for key, value in asdict(item).items()}
