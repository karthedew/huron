"""Fixtures for the integration tier."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from tests.support.api import mark_lake
from tests.support.crash import ChildApi
from tests.support.postgres import truncate


@pytest.fixture
async def child_api(database_url: str, tmp_path: Path) -> AsyncIterator[ChildApi]:
    """The API in a child process over the emptied test database and a new marked lake.

    The child is stopped at teardown, also when the test fails.
    """
    await truncate(database_url)
    api = ChildApi(database_url, mark_lake(tmp_path / "lake"), tmp_path / "child")
    try:
        await api.start()
        yield api
    finally:
        await api.close()
