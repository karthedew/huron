"""Shared public-store scenarios for lake persistence adapters."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from huron.core.lake.ports import LakeStore


async def store_root_scenario(store: LakeStore) -> None:
    """Readiness answers None and a transaction may exit without writes."""
    assert await store.ping() is None
    async with store.transaction():
        pass


async def transaction_error_scenario(store: LakeStore) -> None:
    """A transaction propagates the original exception, leaving the store usable."""
    failure = ValueError("transaction failed")
    with pytest.raises(ValueError) as caught:
        async with store.transaction():
            raise failure
    assert caught.value is failure
    async with store.transaction():
        pass
