"""The FastAPI application."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from huron.applications.api.problems import install_problem_handlers
from huron.applications.api.routes import discovery, health
from huron.applications.api.routes.v1.router import router as v1
from huron.applications.api.runtime import VERSION, Runtime, build_runtime
from huron.applications.api.settings import Settings

__all__ = ["create_app"]


def create_app(settings: Settings | None = None, runtime: Runtime | None = None) -> FastAPI:
    """Build the application.

    With ``runtime`` the caller owns startup and shutdown; otherwise the lifespan builds the
    runtime from ``settings`` and closes it on shutdown.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        if runtime is not None:
            app.state.runtime = runtime
            yield
            return
        if settings is None:
            raise RuntimeError("create_app needs settings or a runtime")
        built = await build_runtime(settings)
        app.state.runtime = built
        try:
            yield
        finally:
            await built.close()

    app = FastAPI(
        title="Huron",
        version=VERSION,
        summary="Catalog and access control for raw scientific data on NFS.",
        lifespan=lifespan,
    )
    if runtime is not None:
        app.state.runtime = runtime
    install_problem_handlers(app)
    app.include_router(health.router)
    app.include_router(discovery.router)
    app.include_router(v1)
    return app
