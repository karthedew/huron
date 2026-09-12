"""Disposable database lifecycle for complete catalog workflow integration tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from testcontainers.postgres import PostgresContainer

from tests.contract.test_hierarchy_store import _migrate

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(scope="module")
def catalog_database() -> Iterator[str]:
    """Supply a migrated PostgreSQL database isolated to one workflow test module."""
    with PostgresContainer("postgres:16") as postgres:
        _migrate(postgres.get_connection_url(driver="asyncpg"))
        yield postgres.get_connection_url(driver=None)
