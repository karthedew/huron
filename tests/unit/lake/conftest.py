"""Fixtures for domain tests."""

import pytest

from tests.support.lake import World, make_world, seed


@pytest.fixture
async def world() -> World:
    """A bootstrapped, empty lake."""
    return await make_world()


@pytest.fixture
async def seeded(world: World) -> World:
    """A lake with the helio organization, catalog, grants and namespace."""
    await seed(world)
    return world
