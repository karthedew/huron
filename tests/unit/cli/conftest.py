"""Fixtures for CLI tests: the CLI over an in-process service and an in-memory share."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from huron.core.storage import (
    MARKER_FILE,
    DirectoryKind,
    EffectiveGroups,
    Marker,
    plan,
    render_marker,
)
from huron.core.storage.memory import MemoryStorage
from tests.support.api import INSTANCE_ID
from tests.support.cli import Cli
from tests.support.lake import World, seed

PREFIX = Path("/projects/huron")


@pytest.fixture
def share() -> MemoryStorage:
    """An in-memory share rooted at the default prefix, marked for the test service."""
    storage = MemoryStorage(PREFIX, user="dave")
    marker = Marker(1, "http://huron.test", str(INSTANCE_ID))
    storage.write_bytes(PREFIX / MARKER_FILE, render_marker(marker))
    return storage


@pytest.fixture
def cli(tmp_path: Path, share: MemoryStorage) -> Iterator[Cli]:
    """A CLI with an in-memory share; nobody logged in."""
    running = Cli(tmp_path, lambda config: share, PREFIX)
    yield running
    running.close()


@pytest.fixture
def seeded_cli(cli: Cli, share: MemoryStorage) -> Cli:
    """The helio organization, catalog, grants and namespace, created through the domain.

    The share holds the organization and catalog directories; namespace directories are left
    for the test to create.
    """
    runtime = cli.runtime
    cli.loop.call(seed(World(runtime.lake, runtime.store, cli.clock)))  # type: ignore[arg-type]
    groups = EffectiveGroups(platform_admin=("huron-platform-admins",))
    for relative in ("helio", "helio/heliophysics"):
        share.ensure_directory(PREFIX / relative, plan(DirectoryKind.CATALOG, groups))
    return cli
