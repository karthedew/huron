"""Streaming sha256 for files."""

from __future__ import annotations

import hashlib
import os

__all__ = ["CHUNK_SIZE", "EMPTY_SHA256", "sha256_descriptor"]

CHUNK_SIZE = 8 * 1024 * 1024
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


def sha256_descriptor(descriptor: int, chunk: int = CHUNK_SIZE) -> str:
    """Return the sha256 of the bytes of the open file ``descriptor``, read from its start.

    The reads give their offsets, so the position of the descriptor does not change.
    """
    digest = hashlib.sha256()
    offset = 0
    while block := os.pread(descriptor, chunk, offset):
        digest.update(block)
        offset += len(block)
    return digest.hexdigest()
