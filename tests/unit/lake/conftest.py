"""Fixtures for domain tests."""

import uuid
from collections.abc import AsyncIterator

import pytest

from huron.core.metastore.store import MemoryStore
from tests.support.lake import CATALOG_ADMIN, World, make_world, seed, settled_collection
from tests.support.postgres import empty_store
from tests.support.publication import Publishing, publishing_over


@pytest.fixture
async def world() -> World:
    """A bootstrapped, empty lake."""
    return await make_world()


@pytest.fixture
async def seeded(world: World) -> World:
    """A lake with the helio organization, catalog, grants and namespace."""
    await seed(world)
    return world


@pytest.fixture
async def collection_id(seeded: World) -> uuid.UUID:
    """An active collection of the seeded lake, created by the contributor."""
    return await settled_collection(seeded.lake)


@pytest.fixture
async def nested_collection_id(seeded: World) -> uuid.UUID:
    """An active collection ``deep`` in the nested namespace ``solar-wind.inner``."""
    await seeded.lake.namespaces.create(CATALOG_ADMIN, "heliophysics", "solar-wind", "inner", True)
    return await settled_collection(seeded.lake, "deep", "solar-wind.inner")


@pytest.fixture(params=["memory", pytest.param("postgres", marks=pytest.mark.contract)])
def database(request: pytest.FixtureRequest) -> str | None:
    """``None`` for the in-memory store, the URL of a migrated database for PostgreSQL."""
    if request.param == "memory":
        return None
    url: str = request.getfixturevalue("database_url")
    return url


@pytest.fixture
async def publishing(database: str | None) -> AsyncIterator[Publishing]:
    """A seeded lake with an active collection, over the in-memory store and over PostgreSQL."""
    if database is None:
        yield await publishing_over(MemoryStore())
        return
    async with empty_store(database) as store:
        yield await publishing_over(store)
