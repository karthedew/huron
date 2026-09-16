"""Injected time for deterministic domain operations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import datetime


class Clock(Protocol):
    """The source of the current time, injected so lease arithmetic is testable."""

    def now(self) -> datetime:
        """Return the current instant.

        Returns:
            A timezone-aware UTC datetime.
        """
        ...
