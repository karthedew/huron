"""The one writer of the lake: a lock that one API process at a time holds.

The deployment runs one API replica. A second process that starts while the first still runs
finds the lock held and serves reads only. When the writer loses its lock, it starts no new
filesystem step and stops, so that the platform starts it again. The lock is not a fence
against a delayed NFS call from a process that died: the deployment must never run two
writable processes.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, Protocol

import structlog

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["WRITER_CHECK_INTERVAL", "Ownership", "WriterLock"]

#: Seconds between two checks that the writer still holds its lock.
WRITER_CHECK_INTERVAL = 10.0

_log = structlog.get_logger(__name__)


class WriterLock(Protocol):
    """A lock that at most one process holds, and that ends with the process or its
    connection."""

    async def acquire(self) -> bool:
        """Take the lock without a wait; ``False`` when another process holds it."""
        ...

    async def held(self) -> bool:
        """Whether this process still holds the lock; ``False`` when its connection dropped."""
        ...

    async def release(self) -> None:
        """Give the lock back; nothing happens when this process does not hold it."""
        ...


class Ownership:
    """Whether this process writes the lake, from ``lock``.

    ``on_lost`` runs one time when the writer loses its lock. The service stops the process
    there. Every ``interval`` seconds a watch task checks the lock.
    """

    def __init__(
        self,
        lock: WriterLock,
        on_lost: Callable[[], None],
        *,
        interval: float = WRITER_CHECK_INTERVAL,
    ) -> None:
        self._lock = lock
        self._on_lost = on_lost
        self._interval = interval
        self._held = False
        self._lost = False
        self._watch: asyncio.Task[None] | None = None

    @property
    def writable(self) -> bool:
        """Whether this process holds the lock, so that it can start a filesystem step."""
        return self._held

    @property
    def lost(self) -> bool:
        """Whether this process held the lock and lost it: it is no longer ready."""
        return self._lost

    async def start(self) -> bool:
        """Take the lock, and start the watch when this process got it.

        ``False`` when another process holds the lock: this process then serves reads only.
        """
        self._held = await self._lock.acquire()
        if self._held:
            self._watch = asyncio.create_task(self._watching(), name="huron-writer-lock")
        else:
            _log.warning("ownership.reader")
        return self._held

    async def check(self) -> bool:
        """Whether this process still holds the lock.

        The first check that finds the lock gone ends the writes of this process, logs the
        loss and calls ``on_lost``.
        """
        if self._held and not await self._lock.held():
            self._held = False
            self._lost = True
            _log.error("ownership.lost")
            self._on_lost()
        return self._held

    async def close(self) -> None:
        """Stop the watch and give the lock back."""
        if self._watch is not None:
            self._watch.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._watch
        self._held = False
        await self._lock.release()

    async def _watching(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            if not await self.check():
                return
