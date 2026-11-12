"""A fixed starting instant for tests, clocks that move only when told, and turns of the event
loop that let due timers fire."""

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime

from huron.pkg.clock import FrozenClock

START = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)

#: How many turns :func:`run_ready` gives the event loop: many more than an in-process HTTP answer
#: needs after the timer that ends its wait fires.
READY_TURNS = 100


def frozen() -> FrozenClock:
    """A clock frozen at :data:`START`."""
    return FrozenClock(START)


async def run_ready(turns: int = READY_TURNS) -> None:
    """Give the event loop ``turns`` turns: the due timers fire and the work they release runs.

    Work that waits for a thread goes on only when the thread ends. After this, a task that a due
    timer can end is done, so ``assert not task.done()`` shows that no timer ended it.
    """
    for _ in range(turns):
        await asyncio.sleep(0)


class LoopClock:
    """An event loop's clock, stopped: the loop's timers fire only when :meth:`advance` moves it.

    A timeout then expires when the test says so, never because a thread was slow.
    """

    def __init__(self, start: float) -> None:
        self._now = start

    def time(self) -> float:
        """The loop's time, in seconds."""
        return self._now

    def advance(self, seconds: float) -> None:
        """Move the loop's time forward by ``seconds``."""
        self._now += seconds


class MonotonicClock:
    """A monotonic clock that moves only when ``sleep`` or ``advance`` is called.

    ``slept`` lists the seconds of each sleep. ``on_sleep`` runs after each sleep.
    """

    def __init__(self) -> None:
        self.now = 100.0
        self.slept: list[float] = []
        self.on_sleep: Callable[[], None] = lambda: None

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        """Record a sleep of ``seconds`` and move the clock forward by them."""
        self.slept.append(seconds)
        self.advance(seconds)
        self.on_sleep()

    def advance(self, seconds: float) -> None:
        """Move the clock forward by ``seconds``, as a request that takes them does."""
        self.now += seconds
