"""Application-generated RFC 9562 UUIDv7 identifiers.

Identifiers are minted by the application, not the database, so a record's
id is known before anything is written and can be embedded in the storage
path that is created alongside it. UUIDv7 puts a millisecond timestamp in
the high bits, so ids sort by creation time and index inserts stay
append-mostly rather than scattering across the tree as random UUIDs do.
"""

import os
import time
import uuid


def uuid7() -> uuid.UUID:
    """Return a UUIDv7 with a 48-bit Unix-millisecond timestamp.

    The layout follows RFC 9562: 48 bits of Unix time in milliseconds, the
    version nibble, 12 random bits, the two variant bits, then 62 random
    bits, with every random bit drawn from ``os.urandom``. Two ids minted
    in the same millisecond carry no ordering between them.

    Returns:
        A fresh version-7 UUID whose leading bits encode the current time.

    Raises:
        OverflowError: If the current time no longer fits in 48 bits of
            milliseconds, which is not until the year 10889.
    """
    unix_ms = time.time_ns() // 1_000_000
    if unix_ms >= 1 << 48:
        raise OverflowError("current timestamp does not fit in UUIDv7")
    rand_a = int.from_bytes(os.urandom(2)) & 0x0FFF
    rand_b = int.from_bytes(os.urandom(8)) & 0x3FFF_FFFF_FFFF_FFFF
    value = (unix_ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    return uuid.UUID(int=value)


def id_for_path(value: uuid.UUID) -> str:
    """Return the lowercase, dash-free representation used in storage paths.

    This is the 32-character form that follows the ``--`` separator in every
    ``{slug}--{id}`` path component, and the form the path parser in
    :mod:`huron.pkg.catalog.paths` requires when it reads an id back.

    Args:
        value: The identifier to render.

    Returns:
        The UUID's 32 hexadecimal digits, lower case, with no dashes.
    """
    return value.hex
