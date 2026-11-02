"""The store contract against the in-memory store."""

import pytest

from huron.core.metastore.store import MemoryStore
from tests.contract.suite import *  # noqa: F403


@pytest.fixture
def uow() -> MemoryStore:
    """An empty in-memory store."""
    return MemoryStore()


async def test_closing_the_memory_store_is_harmless(uow: MemoryStore) -> None:
    await uow.close()
