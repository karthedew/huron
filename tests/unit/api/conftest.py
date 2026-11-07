"""Fixtures for API tests."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from tests.support.api import Service, mark_lake, seed_service, service
from tests.support.tusd import UploadTarget, upload_target


@pytest.fixture
async def api() -> AsyncIterator[Service]:
    """An in-process service over an empty in-memory store."""
    async with service() as running:
        yield running


@pytest.fixture
async def seeded_api(api: Service) -> Service:
    """The helio organization, catalog, grants and the solar-wind namespace, through the API."""
    return await seed_service(api)


@pytest.fixture
def lake(tmp_path: Path) -> Path:
    """A temporary lake directory, marked for the test service."""
    return mark_lake(tmp_path / "lake")


@pytest.fixture
async def lake_api(lake: Path) -> AsyncIterator[Service]:
    """An in-process service that mounts the temporary lake at ``lake_path``."""
    async with service(lake_path=lake) as running:
        yield running


@pytest.fixture
async def seeded_lake_api(lake_api: Service) -> Service:
    """The seeded data of :func:`seeded_api`, in a service with a lake."""
    return await seed_service(lake_api)


@pytest.fixture
async def target(seeded_lake_api: Service, lake: Path) -> UploadTarget:
    """Collection ``run7`` of the service with the temporary lake, ready for uploads."""
    return await upload_target(seeded_lake_api, lake)
