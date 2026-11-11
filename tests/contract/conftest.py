"""PostgreSQL fixtures for the contract tier."""

from collections.abc import AsyncIterator

import pytest

from huron.core.metastore.postgres import PostgresStore
from tests.support.postgres import empty_store


@pytest.fixture
async def uow(database_url: str) -> AsyncIterator[PostgresStore]:
    """An empty PostgreSQL store."""
    async with empty_store(database_url) as store:
        yield store
