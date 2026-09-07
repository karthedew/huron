"""The background task that reaps every replica's abandoned ingest leases.

Every API replica runs one of these, entered by the lifespan once the
runtime is published: a lapsed session's dataset lock is released from
whichever replica's own clock and pass happens to notice it first, with no
coordination between replicas beyond the optimistic-concurrency fence the
store's write already enforces.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from .ingest import IngestService

logger = logging.getLogger(__name__)


class ExpirySweep:
    """Owns this process's one background task reaping lapsed ingest leases.

    Entered by the lifespan once the runtime is published; leaving it
    cancels and awaits the task, so no pass outlives the pool it runs on.
    """

    def __init__(self, ingest: IngestService, *, interval_seconds: float, limit: int) -> None:
        """Bind the sweep to the facade it drives and the cadence it runs at.

        Args:
            ingest: The facade whose ``expire_lapsed`` this task calls.
            interval_seconds: How long to sleep between two passes.
            limit: The most sessions one pass may flip.
        """
        self._ingest = ingest
        self._interval_seconds = interval_seconds
        self._limit = limit

    async def run(self) -> None:
        """Sweep immediately, then every ``interval_seconds``, forever.

        A failing pass is logged with its traceback and the next pass
        runs on schedule; only cancellation ends the loop.
        """
        while True:
            try:
                report = await self._ingest.expire_lapsed(limit=self._limit)
            except Exception:
                logger.exception("ingest expiry sweep failed; the next pass runs on schedule")
            else:
                if report.expired or report.skipped:
                    logger.info(
                        "ingest expiry sweep: expired %d, skipped %d, listed %d",
                        report.expired,
                        report.skipped,
                        report.listed,
                    )
            await asyncio.sleep(self._interval_seconds)

    async def __aenter__(self) -> Self:
        """Start the sweep's task, named so it is identifiable in a task dump.

        Returns:
            This sweep, with its task now running.
        """
        self._task = asyncio.create_task(self.run(), name="ingest-expiry-sweep")
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Cancel the task and await it.

        ``CancelledError`` is the expected outcome of that cancellation and
        is swallowed here only; any other exception a pass raised was
        already caught and logged inside :meth:`run`, so nothing escapes
        this exit either way.

        Args:
            *exc: The exception type, value and traceback the context
                manager protocol passes when the block is left by an
                exception; unused, since the task is cancelled the same
                way regardless of why the block is being left.
        """
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
