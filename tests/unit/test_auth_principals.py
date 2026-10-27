"""Principal identity lookup and disablement."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from huron.core.metastore import MemoryPrincipalStore
from huron.core.security.principals import (
    PrincipalRecord,
)

pytestmark = pytest.mark.unit


async def test_get_by_id_returns_none_for_an_unknown_id() -> None:
    """``get_by_id`` returns None for an id no principal has."""
    store = MemoryPrincipalStore()
    assert await store.get_by_id(uuid4()) is None


async def test_get_by_id_returns_the_matching_record_regardless_of_kind_or_disabled_state() -> None:
    """``get_by_id`` returns the exact record stored for a principal's id."""
    record = PrincipalRecord(
        uuid4(), "user", "dana", "Dana", None, None, datetime(2026, 1, 1, tzinfo=UTC)
    )
    store = MemoryPrincipalStore({record.id: record})
    assert await store.get_by_id(record.id) == record


async def test_disable_sets_disabled_at_and_returns_the_updated_record() -> None:
    """``disable`` stamps disabled_at and returns the updated identity."""
    record = PrincipalRecord(
        uuid4(), "user", "dana", "Dana", None, None, datetime(2026, 1, 1, tzinfo=UTC)
    )
    store = MemoryPrincipalStore({record.id: record})
    moment = datetime(2026, 1, 2, tzinfo=UTC)
    updated = await store.disable(record.id, disabled_at=moment)
    assert updated is not None
    assert updated.disabled_at == moment
    assert (await store.get_by_id(record.id)) == updated


async def test_disable_returns_none_for_an_unknown_id() -> None:
    """``disable`` returns None for an id no principal has."""
    store = MemoryPrincipalStore()
    assert await store.disable(uuid4(), disabled_at=datetime(2026, 1, 2, tzinfo=UTC)) is None
