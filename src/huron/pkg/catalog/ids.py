"""Application-generated RFC 9562 UUIDv7 identifiers."""

import os
import time
import uuid


def uuid7() -> uuid.UUID:
    """Return a UUIDv7 with a 48-bit Unix-millisecond timestamp."""
    unix_ms = time.time_ns() // 1_000_000
    if unix_ms >= 1 << 48:
        raise OverflowError("current timestamp does not fit in UUIDv7")
    rand_a = int.from_bytes(os.urandom(2)) & 0x0FFF
    rand_b = int.from_bytes(os.urandom(8)) & 0x3FFF_FFFF_FFFF_FFFF
    value = (unix_ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    return uuid.UUID(int=value)


def id_for_path(value: uuid.UUID) -> str:
    """Return the lowercase, dash-free representation used in storage paths."""
    return value.hex
