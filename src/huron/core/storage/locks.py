"""In-process locks per lake path, so two requests of one process never change one entry at once."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from huron.core.storage.lakepath import LakePath

__all__ = ["PathLocks"]


class PathLocks:
    """One ``asyncio`` lock per :class:`LakePath`, kept only while somebody holds or awaits it.

    The locks serialize the requests of one process. They do not reach other processes or
    other replicas.
    """

    def __init__(self) -> None:
        self._locks: dict[LakePath, _Entry] = {}

    def __len__(self) -> int:
        """How many paths are held or awaited now."""
        return len(self._locks)

    @asynccontextmanager
    async def hold(self, path: LakePath) -> AsyncGenerator[None]:
        """Hold the lock of ``path`` for the body of the ``async with``."""
        entry = self._locks.setdefault(path, _Entry())
        entry.users += 1
        try:
            async with entry.lock:
                yield
        finally:
            entry.users -= 1
            if entry.users == 0:
                del self._locks[path]


@dataclass
class _Entry:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    users: int = 0
