"""A fixed starting instant for tests."""

from datetime import UTC, datetime

from huron.pkg.clock import FrozenClock

START = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)


def frozen() -> FrozenClock:
    """A clock frozen at :data:`START`."""
    return FrozenClock(START)
