"""Fixtures for API tests."""

import threading
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from huron.core.storage.posix import PosixStorage
from tests.support.api import Service, mark_lake, seed_service, service
from tests.support.disk import SIGNAL_TIMEOUT
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


@pytest.fixture
async def paused_copy(
    target: UploadTarget, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[tuple[threading.Event, threading.Event]]:
    """The copy of each seal waits until the second event is set; the first is set then.

    The second event is set at the end of the test, before the service of ``target`` stops.
    """
    copying, release = threading.Event(), threading.Event()
    real = PosixStorage.copy_sealed

    def paused(self: PosixStorage, *args: Any, **kwargs: Any) -> Any:
        copying.set()
        assert release.wait(SIGNAL_TIMEOUT)
        return real(self, *args, **kwargs)

    monkeypatch.setattr(PosixStorage, "copy_sealed", paused)
    yield copying, release
    release.set()
