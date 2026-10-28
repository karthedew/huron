"""Injected time for deterministic domain operations."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    """The source of the current time, injected so lease arithmetic is testable."""

    def now(self) -> datetime:
        """Return the current instant.

        Returns:
            A timezone-aware UTC datetime.
        """
        ...


class SystemClock:
    """The default clock: the operating system's UTC time."""

    def now(self) -> datetime:
        """Return the current instant.

        Returns:
            The current time, timezone-aware in UTC.
        """
        return datetime.now(UTC)
