"""Fixtures for CLI tests: the CLI over an in-process service and an in-memory share.

The CLI writes nothing to the share. The helpers here make the directories and the
``metadata.json`` files that the status, push and check tests need, as the API will make them.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest

from huron.core.storage import DIRECTORY_MODE, MARKER_FILE, ORGANIZATION_MODE
from huron.core.storage.memory import MemoryStorage
from tests.support.api import ROOT_MARKER
from tests.support.cli import Cli
from tests.support.lake import PLATFORM_ADMIN, World, seed

PREFIX = Path("/projects/huron")
ORGANIZATION = PREFIX / "helio"
CATALOG = ORGANIZATION / "heliophysics"


@pytest.fixture
def share() -> MemoryStorage:
    """An in-memory share rooted at the default prefix, marked for the test service."""
    storage = MemoryStorage(PREFIX)
    storage.write_bytes(PREFIX / MARKER_FILE, ROOT_MARKER)
    return storage


@pytest.fixture
def cli(tmp_path: Path, share: MemoryStorage) -> Iterator[Cli]:
    """A CLI with an in-memory share, which the service holds as its lake; nobody logged in."""
    running = Cli(tmp_path, lambda config: share, PREFIX, lake=share)
    yield running
    running.close()


@pytest.fixture
def seeded_cli(cli: Cli, share: MemoryStorage) -> Cli:
    """helio, heliophysics with its grants and solar-wind, from the domain, with directories."""
    runtime = cli.runtime
    cli.loop.call(seed(World(runtime.lake, runtime.store, cli.clock)))  # type: ignore[arg-type]
    share.make_directory(ORGANIZATION, ORGANIZATION_MODE)
    make_directory(cli, "heliophysics")
    make_directory(cli, "heliophysics/solar-wind")
    return cli


def make_directory(cli: Cli, relative: str, organization: Path = ORGANIZATION) -> Path:
    """Make ``<organization>/<relative>`` with the directory mode, as the API makes it."""
    assert cli.lake is not None
    path = organization / relative
    cli.lake.make_directory(path, DIRECTORY_MODE)
    return path


def make_collection(cli: Cli, name: str = "run7", organization: Path = ORGANIZATION) -> Path:
    """Make the directory and ``metadata.json`` of ``heliophysics.solar-wind.<name>``."""
    lake = cli.runtime.lake
    view = cli.loop.call(
        lake.collections.get(PLATFORM_ADMIN, identifier=f"heliophysics.solar-wind.{name}")
    )
    relative = f"heliophysics/solar-wind/{name}"
    path = make_directory(cli, relative, organization)
    sidecar = cli.loop.call(lake.collections.sidecar(PLATFORM_ADMIN, view.collection.id))
    assert cli.lake is not None
    cli.lake.write_bytes(path / "metadata.json", sidecar)
    return path
