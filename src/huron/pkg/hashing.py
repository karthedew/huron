"""Streaming sha256 for files."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["CHUNK_SIZE", "EMPTY_SHA256", "sha256_file"]

CHUNK_SIZE = 8 * 1024 * 1024
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


def sha256_file(path: Path, chunk: int = CHUNK_SIZE) -> tuple[int, str]:
    """Return ``(size, sha256)`` of the file at ``path``."""
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while block := handle.read(chunk):
            digest.update(block)
            size += len(block)
    return size, digest.hexdigest()
