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
    must not answer requests at all. The optional members record what the
    deployment lacks rather than defaulting it: ``oidc_resolver`` and
    ``oidc_client`` are ``None`` when no identity provider is configured,
    so bearer JWTs are refused and the OIDC routes answer 404, and
    ``database_pool`` is ``None`` unless ``store_backend`` chose Postgres,
    so the readiness probe knows whether there is a database to check.
    """

    settings: ApiSettings
    repository: HierarchyRepository
    oidc_resolver: OidcResolver | None
    oidc_client: OidcClient | None
    database_pool: asyncpg.Pool | None


async def api_runtime(request: Request) -> ApiRuntime:
    """Return the wiring the lifespan published, or refuse to serve.

    An application whose lifespan never started has no runtime, and every
    injected route fails here rather than falling through to a default:
    the cost of guessing at wiring is an unauthenticated request answered
    as though it were authenticated. The failure is a ``RuntimeError``, not
    a domain error, because it is a deployment bug and its honest answer is
    the 500 the unhandled-exception path produces.

    Args:
        request: The request being served; only its application's state is
            read.

    Returns:
        The runtime ``create_app``'s lifespan stored on ``app.state``.

    Raises:
        RuntimeError: If ``app.state.runtime`` is unset because the lifespan
            has not run.
    """
    runtime: ApiRuntime | None = getattr(request.app.state, "runtime", None)
    if runtime is None:
        raise RuntimeError("the application lifespan has not started: app.state.runtime is unset")
    return runtime


Runtime = Annotated[ApiRuntime, Depends(api_runtime)]


async def api_repository(runtime: Runtime) -> HierarchyRepository:
    """Return the repository the service was wired with.

    Args:
        runtime: The published wiring, resolved by ``api_runtime``.

    Returns:
        The one ``HierarchyRepository`` every request in this process
        shares.
    """
    return runtime.repository


async def api_settings(runtime: Runtime) -> ApiSettings:
    """Return the validated settings the service was wired with.

    Args:
        runtime: The published wiring, resolved by ``api_runtime``.

    Returns:
        The settings ``create_app`` was given; the same object for every
        request.
    """
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
