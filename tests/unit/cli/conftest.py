"""Fixtures for CLI tests: the CLI over an in-process service and an in-memory share.

The CLI writes nothing to the share. The helpers here make the directories and the
``metadata.json`` files that the status, push and check tests need, as the API will make them.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest

from huron.core.storage import DIRECTORY_MODE, FILE_MODE, MARKER_FILE, ORGANIZATION_MODE, LakePath
from huron.core.storage.memory import MemoryStorage
from tests.fakes.storage import rooted
from tests.support.api import ROOT_MARKER
from tests.support.cli import Cli
from tests.support.lake import PLATFORM_ADMIN, World, seed

PREFIX = Path("/projects/huron")
ORGANIZATION = LakePath.of("helio")
CATALOG = ORGANIZATION.joinpath("heliophysics")


@pytest.fixture
def share() -> MemoryStorage:
    """An in-memory share rooted at the default prefix, marked for the test service.

    Its root belongs to the service user and group, as ``huron adm provision-orgs`` leaves it.
    """
    storage = MemoryStorage(PREFIX)
    root = storage.nodes[LakePath()]
    root.uid, root.gid = storage.uid, storage.gid
    storage.write_bytes(LakePath.of(MARKER_FILE), ROOT_MARKER, FILE_MODE)
    return storage


@pytest.fixture
def cli(tmp_path: Path, share: MemoryStorage) -> Iterator[Cli]:
    """A CLI with an in-memory share, which the service holds as its lake; nobody logged in."""
    running = Cli(tmp_path, rooted(share), PREFIX, lake=share)
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


def make_directory(cli: Cli, relative: str, organization: LakePath = ORGANIZATION) -> LakePath:
    """Make ``<organization>/<relative>`` with the directory mode, as the API makes it."""
    assert cli.lake is not None
    location = organization.joinpath(*relative.split("/"))
    cli.lake.make_directory(location, DIRECTORY_MODE)
    return location


def make_collection(
    cli: Cli, name: str = "run7", organization: LakePath = ORGANIZATION
) -> LakePath:
    """Make the directory and ``metadata.json`` of ``heliophysics.solar-wind.<name>``."""
    lake = cli.runtime.lake
    view = cli.loop.call(
        lake.collections.get(PLATFORM_ADMIN, identifier=f"heliophysics.solar-wind.{name}")
    )
    location = make_directory(cli, f"heliophysics/solar-wind/{name}", organization)
    sidecar = cli.loop.call(lake.collections.sidecar(PLATFORM_ADMIN, view.collection.id))
    assert cli.lake is not None
    cli.lake.write_bytes(location.joinpath("metadata.json"), sidecar, FILE_MODE)
    return location
