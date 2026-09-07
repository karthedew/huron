"""``ExpirySweep``: the lifecycle object owning the ingest expiry sweep's one task.

Driven with ``interval_seconds=0`` and ``await asyncio.sleep(0)`` ticks, so
every test is deterministic and never waits on the wall clock. The
sweep's collaborator is a recording double at the facade boundary,
rather than a real ``IngestService``.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

import pytest

from huron.service.api.expiry import ExpirySweep
from huron.service.api.ingest import ExpiryReport

pytestmark = pytest.mark.unit


@dataclass(slots=True)
class _RecordingIngest:
    """A minimal ``IngestService`` double recording every ``expire_lapsed`` call.

    Attributes:
        calls: The ``limit`` forwarded by each call, in call order.
        raise_on: The 1-based call number that should raise, or None.
        delay_seconds: How long a call should sleep before returning, or
            None for an instant return.
    """

    calls: list[int] = field(default_factory=list)
    raise_on: int | None = None
    delay_seconds: float | None = None

    async def expire_lapsed(self, *, limit: int) -> ExpiryReport:
        """Record the call, then raise, sleep or return, as configured.

        Args:
            limit: The bound the caller passed, recorded verbatim.

        Returns:
            An empty report, once this call neither raises nor is still
            sleeping.

        Raises:
            RuntimeError: On the call numbered ``raise_on``.
        """
        self.calls.append(limit)
        if self.delay_seconds is not None:
            await asyncio.sleep(self.delay_seconds)
        if self.raise_on == len(self.calls):
            raise RuntimeError("ingest facade unavailable")
        return ExpiryReport(listed=0, expired=0, skipped=0)


async def test_the_sweep_runs_a_pass_as_soon_as_it_starts() -> None:
    """The first pass runs on the task's first tick, forwarding the configured limit."""
    ingest = _RecordingIngest()
    async with ExpirySweep(ingest, interval_seconds=0, limit=7):
        await asyncio.sleep(0)
        assert ingest.calls == [7]


async def test_a_failing_pass_is_logged_and_the_next_pass_runs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A pass that raises is logged with its traceback, and the loop keeps running afterward."""
    caplog.set_level(logging.ERROR, logger="huron.service.api.expiry")
    ingest = _RecordingIngest(raise_on=1)
    async with ExpirySweep(ingest, interval_seconds=0, limit=1):
        for _ in range(6):
            await asyncio.sleep(0)
        assert len(ingest.calls) >= 2

    errors = [record for record in caplog.records if record.levelno == logging.ERROR]
    assert len(errors) == 1
    assert errors[0].name == "huron.service.api.expiry"
    assert errors[0].exc_info is not None


async def test_leaving_the_context_cancels_and_awaits_the_task() -> None:
    """Leaving the sweep cancels its task, and no further pass runs after that."""
    ingest = _RecordingIngest()
    sweep = ExpirySweep(ingest, interval_seconds=0, limit=1)
    async with sweep:
        await asyncio.sleep(0)
    calls_at_exit = list(ingest.calls)

    assert "ingest-expiry-sweep" not in {task.get_name() for task in asyncio.all_tasks()}
    for _ in range(3):
        await asyncio.sleep(0)
    assert ingest.calls == calls_at_exit


async def test_cancellation_during_a_pass_does_not_wait_for_it() -> None:
    """Leaving the sweep mid-pass cancels it promptly instead of waiting for it to finish."""
    ingest = _RecordingIngest(delay_seconds=3600)
    sweep = ExpirySweep(ingest, interval_seconds=0, limit=1)
    async with sweep:
        await asyncio.sleep(0)

    assert sweep._task.cancelled()
