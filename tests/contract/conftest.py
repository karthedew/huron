"""PostgreSQL fixtures for the contract tier."""

from collections.abc import AsyncIterator

import pytest

from huron.core.metastore.postgres import PostgresStore
from tests.support.postgres import truncate


@pytest.fixture
async def uow(database_url: str) -> AsyncIterator[PostgresStore]:
    """An empty PostgreSQL store."""
    await truncate(database_url)
    store = PostgresStore(database_url, pool_size=4)
    await store.connect()
    yield store
    await store.close()
