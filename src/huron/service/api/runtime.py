"""What the composition root wired, and how a request reaches it.

``create_app`` builds an :class:`ApiRuntime` once, in the lifespan, and
publishes it as the application's only piece of mutable state. Path
operations and guards declare ``Repository``/``Settings`` rather than a
``Request``: ``api_runtime`` below is the one function in the tier that
reaches through the request to read what the app was wired with.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

import asyncpg
from fastapi import Depends, Request

from huron.pkg.auth import OidcClient, OidcResolver

from .repository import HierarchyRepository
from .settings import ApiSettings


@dataclass(frozen=True, slots=True)
class ApiRuntime:
    """Everything a request may need that outlives the request.

    Frozen because a handler must never re-wire the service, and
    ``settings`` is non-optional because a service with no configuration
    must not answer requests at all.
    """

    settings: ApiSettings
    repository: HierarchyRepository
    oidc_resolver: OidcResolver | None
    oidc_client: OidcClient | None
    database_pool: asyncpg.Pool | None


async def api_runtime(request: Request) -> ApiRuntime:
    """The wiring the lifespan published, or a refusal to serve.

    An application whose lifespan never started has no runtime, and every
    injected route fails here rather than falling through to a default:
    the cost of guessing at wiring is an unauthenticated request answered
    as though it were authenticated.
    """
    runtime: ApiRuntime | None = getattr(request.app.state, "runtime", None)
    if runtime is None:
        raise RuntimeError("the application lifespan has not started: app.state.runtime is unset")
    return runtime


Runtime = Annotated[ApiRuntime, Depends(api_runtime)]


async def api_repository(runtime: Runtime) -> HierarchyRepository:
    return runtime.repository


async def api_settings(runtime: Runtime) -> ApiSettings:
    return runtime.settings


Repository = Annotated[HierarchyRepository, Depends(api_repository)]
Settings = Annotated[ApiSettings, Depends(api_settings)]

__all__ = [
    "ApiRuntime",
    "Repository",
    "Runtime",
    "Settings",
    "api_repository",
    "api_runtime",
    "api_settings",
]
