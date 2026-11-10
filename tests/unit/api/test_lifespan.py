"""The application builds and closes its own runtime when not given one."""

import os
from pathlib import Path

import httpx
import pytest

from huron.applications.api import runtime as runtime_module
from huron.applications.api.app import create_app
from huron.applications.api.runtime import SERVICE_UMASK
from tests.support.api import settings


async def test_lifespan_builds_a_memory_runtime_and_closes_it() -> None:
    app = create_app(settings())
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            assert (await client.get("/healthz")).status_code == 200
        runtime = app.state.runtime
        assert runtime.owns_http
    assert runtime.http.is_closed


async def test_lifespan_needs_settings_or_a_runtime() -> None:
    app = create_app()
    with pytest.raises(RuntimeError):
        async with app.router.lifespan_context(app):
            pass  # pragma: no cover


async def test_lifespan_uses_a_given_runtime_without_closing_it() -> None:
    from tests.support.api import service

    async with service() as running:
        app = create_app(runtime=running.runtime)
        async with app.router.lifespan_context(app):
            assert app.state.runtime is running.runtime
        assert (await running.client.get("/healthz")).status_code == 200


class StopBuild(Exception):
    """Ends a runtime build at the lake's disk."""


async def test_the_runtime_sets_the_service_umask_before_the_disk_pools_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[int] = []

    def disk(*args: object, **kwargs: object) -> None:
        current = os.umask(0)
        os.umask(current)
        seen.append(current)
        raise StopBuild

    monkeypatch.setattr(runtime_module, "LakeDisk", disk)
    os.umask(0o077)
    app = create_app(settings(lake_path=tmp_path))
    starting = app.router.lifespan_context(app)
    with pytest.raises(StopBuild):
        await starting.__aenter__()
    assert seen == [SERVICE_UMASK] == [0o022]
