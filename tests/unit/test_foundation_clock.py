"""The system clock that every store and service uses when no clock is injected."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from huron.core.foundation.clock import SystemClock

pytestmark = pytest.mark.unit


def test_system_clock_reads_the_current_utc_time() -> None:
    """The instant is timezone-aware UTC and falls between two surrounding wall readings."""
    before = datetime.now(UTC)
    now = SystemClock().now()
    after = datetime.now(UTC)
    assert now.tzinfo is UTC
    assert before <= now <= after
