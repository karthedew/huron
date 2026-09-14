"""Bounded-memory, non-sparse random payload preparation and streaming."""

from __future__ import annotations

import hashlib
import os
from typing import TYPE_CHECKING

from minihuron.rawdatastore import BUFFER_SIZE, FileSpec, finish_thread

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path


def prepare_payload(root: Path, size_bytes: int, file_count: int) -> tuple[FileSpec, ...]:
    """Generate and hash independent random blocks before measurement starts.

    Args:
        root: Existing scratch directory, preferably on local SSD.
        size_bytes: Total bytes per submission, including zero.
        file_count: Number of files over which to distribute the bytes.

    Returns:
        A manifest with exact sizes, nested paths, and SHA-256 digests.
    """
    specs = []
    quotient, remainder = divmod(size_bytes, file_count)
    for index in range(file_count):
        path = f"payload/{index // 1000:06d}/{index:08d}.bin"
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        size = quotient + (index < remainder)
        digest = hashlib.sha256()
        remaining = size
        with target.open("xb") as output:
            while remaining:
                block = os.urandom(min(remaining, BUFFER_SIZE))
                output.write(block)
                digest.update(block)
                remaining -= len(block)
            output.flush()
            os.fsync(output.fileno())
        specs.append(FileSpec(path, size, digest.hexdigest()))
    return tuple(specs)


async def stream_file(path: Path) -> AsyncIterator[bytes]:
    """Read bounded blocks off the event loop, draining reads on cancellation.

    Args:
        path: Prepared payload file.

    Yields:
        At most one service-sized buffer per iteration.
    """
    with path.open("rb") as source:
        while block := await finish_thread(source.read, BUFFER_SIZE):
            yield block
