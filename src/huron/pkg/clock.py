"""Clocks: the real one and a frozen one for tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol

__all__ = ["Clock", "FrozenClock", "SystemClock"]


class Clock(Protocol):
    """Anything that tells the current time as an aware UTC datetime."""

    def now(self) -> datetime:
        """Return the current time."""
        ...


class SystemClock:
    """The wall clock."""

    def now(self) -> datetime:
        """Return the current UTC time."""
        return datetime.now(UTC)


class FrozenClock:
    """A clock that only moves when told to."""

    def __init__(self, at: datetime) -> None:
        if at.tzinfo is None:
            raise ValueError("FrozenClock needs an aware datetime")
        self._at = at

    def now(self) -> datetime:
        """Return the frozen time."""
        return self._at

    def advance(self, delta: timedelta) -> None:
        """Move the clock forward by ``delta``."""
        self._at += delta
