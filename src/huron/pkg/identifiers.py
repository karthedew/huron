"""Time-ordered identifiers."""

from __future__ import annotations

import uuid

import uuid_utils

__all__ = ["new_id", "parse_id"]


def new_id() -> uuid.UUID:
    """Return a new UUIDv7."""
    return uuid.UUID(str(uuid_utils.uuid7()))


def parse_id(text: str) -> uuid.UUID:
    """Parse a UUID; raises ``ValueError`` for anything else."""
    return uuid.UUID(text)
