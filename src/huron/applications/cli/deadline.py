"""One limit in time for a wait of the CLI, on a monotonic clock.

A wait reads a state on the service again and again until the state is final or the deadline
passes. Each sleep and each request timeout of the wait is limited by the time that remains, so
the time of the requests counts too.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx

__all__ = ["Deadline", "DeadlinePassed", "poll"]


class Deadline:
    """The end of a wait, ``seconds`` after its creation on ``clock``; ``sleep`` waits."""

    def __init__(
        self, seconds: float, clock: Callable[[], float], sleep: Callable[[float], None]
    ) -> None:
        self._clock = clock
        self._sleep = sleep
        self._end = clock() + seconds

    def remaining(self) -> float:
        """The seconds until the deadline; 0 when it passed."""
        return max(0.0, self._end - self._clock())

    def pause(self, seconds: float) -> bool:
        """Sleep ``seconds``, or less when less time remains; whether time remains after it."""
        remaining = self.remaining()
        if remaining <= 0:
            return False
        self._sleep(min(seconds, remaining))
        return self.remaining() > 0

    def limit(self, timeout: httpx.Timeout) -> httpx.Timeout:
        """``timeout`` with each of its parts limited by the time that remains."""
        remaining = self.remaining()

        def least(part: float | None) -> float:
            return remaining if part is None else min(part, remaining)

        return httpx.Timeout(
            connect=least(timeout.connect),
            read=least(timeout.read),
            write=least(timeout.write),
            pool=least(timeout.pool),
        )


class DeadlinePassed(Exception):
    """A request of a wait timed out, and no time of the deadline of the wait remains."""


def poll[T](
    first: T,
    read: Callable[[], T],
    waiting: Callable[[T], bool],
    deadline: Deadline,
    interval: float,
) -> T:
    """``read`` every ``interval`` seconds while the last value is ``waiting`` and time remains.

    ``first`` is the value before the first read. A read that raises :class:`DeadlinePassed`
    ends the wait. Returns the last value.
    """
    value = first
    while waiting(value) and deadline.pause(interval):
        try:
            value = read()
        except DeadlinePassed:
            break
    return value
