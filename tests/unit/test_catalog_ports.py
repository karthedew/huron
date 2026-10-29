"""Runtime catalog contracts remain independent of structurally conforming adapters."""

from __future__ import annotations

import pytest

from huron.core.foundation.clock import Clock, SystemClock

pytestmark = pytest.mark.unit


def test_clock_conforms_without_inheriting_the_catalog_protocol() -> None:
    """The real clock supplies aware UTC instants through the catalog contract."""
    clock: Clock = SystemClock()
    assert Clock not in type(clock).__mro__
    assert clock.now().utcoffset().total_seconds() == 0
