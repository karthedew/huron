"""Fixtures for domain tests."""

import uuid

import pytest

from tests.support.lake import CATALOG_ADMIN, World, make_world, seed, settled_collection


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
