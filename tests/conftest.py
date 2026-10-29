"""Shared pytest configuration: the PostgreSQL database for the contract and integration tiers."""

from collections.abc import Iterator

import pytest

from tests.support.postgres import migrated_database, server_url


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    """A database migrated to head, created once per session."""
    with server_url() as server, migrated_database(server) as url:
        yield url
