"""A fixed starting instant for tests, and an event loop clock that moves only when told."""

from datetime import UTC, datetime

from huron.pkg.clock import FrozenClock

START = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)


def frozen() -> FrozenClock:
    """A clock frozen at :data:`START`."""
    return FrozenClock(START)


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
