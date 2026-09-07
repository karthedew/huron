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

from huron.pkg.auth import CredentialStore, OidcClient, OidcResolver, PrincipalStore, SessionStore
from huron.pkg.rbac import RoleBindingAuthorizer

from .ingest import IngestService
from .repository import HierarchyRepository
from .revisions import RevisionService
from .settings import ApiSettings
from .stores import ApiKeyWriter, HierarchyStore, RbacStore


@dataclass(frozen=True, slots=True)
class ApiStores:
    """The hierarchy, RBAC and authentication stores a deployment wires as one unit.

    Bundling all six together gives the composition root one shape to
    build - Postgres in production, process memory in a test - and gives a
    test exactly one object to inject in place of that wiring.

    Attributes:
        hierarchy: Durable storage for the organization/project/dataset/
            release hierarchy and its idempotency claims.
        rbac: Storage for role bindings, service accounts and policies.
        api_keys: Storage for API keys.
        credentials: Storage for password credentials.
        sessions: Storage for browser sessions.
        principals: Storage for user and service-account identities.
    """

    hierarchy: HierarchyStore
    rbac: RbacStore
    api_keys: ApiKeyWriter
    credentials: CredentialStore
    sessions: SessionStore
    principals: PrincipalStore


@dataclass(frozen=True, slots=True)
class ApiRuntime:
    """Everything a request may need that outlives the request.

    Frozen because a handler must never re-wire the service, and
    ``settings`` is non-optional because a service with no configuration
    must not answer requests at all. The optional members record what the
    deployment lacks rather than defaulting it: ``oidc_resolver`` and
    ``oidc_client`` are ``None`` when no identity provider is configured,
    so bearer JWTs are refused and the OIDC routes answer 404, and
    ``database_pool`` is ``None`` only when the stores were injected, so
    the readiness probe knows whether there is a database to check.
    """

    settings: ApiSettings
    repository: HierarchyRepository
    ingest: IngestService
    revisions: RevisionService
    authorizer: RoleBindingAuthorizer
    api_keys: ApiKeyWriter
    credentials: CredentialStore
    sessions: SessionStore
    principals: PrincipalStore
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


async def api_ingest(runtime: Runtime) -> IngestService:
    """Return the ingest service the service was wired with.

    Args:
        runtime: The published wiring, resolved by ``api_runtime``.

    Returns:
        The one ``IngestService`` every request in this process shares.
    """
    return runtime.ingest


async def api_revisions(runtime: Runtime) -> RevisionService:
    """Return the revision-read service the service was wired with.

    Args:
        runtime: The published wiring, resolved by ``api_runtime``.

    Returns:
        The one ``RevisionService`` every request in this process shares.
    """
    return runtime.revisions


async def api_settings(runtime: Runtime) -> ApiSettings:
    """Return the validated settings the service was wired with.

    Args:
        runtime: The published wiring, resolved by ``api_runtime``.

    Returns:
        The settings ``create_app`` was given; the same object for every
        request.
    """
    return runtime.settings


async def api_api_keys(runtime: Runtime) -> ApiKeyWriter:
    """Return the API-key store the service was wired with.

    Args:
        runtime: The published wiring, resolved by ``api_runtime``.

    Returns:
        The one API-key store every request in this process shares.
    """
    return runtime.api_keys


async def api_credentials(runtime: Runtime) -> CredentialStore:
    """Return the credential store the service was wired with.

    Args:
        runtime: The published wiring, resolved by ``api_runtime``.

    Returns:
        The one password-credential store every request in this process
        shares.
    """
    return runtime.credentials


async def api_sessions(runtime: Runtime) -> SessionStore:
    """Return the session store the service was wired with.

    Args:
        runtime: The published wiring, resolved by ``api_runtime``.

    Returns:
        The one browser-session store every request in this process shares.
    """
    return runtime.sessions


async def api_principals(runtime: Runtime) -> PrincipalStore:
    """Return the principal store the service was wired with.

    Args:
        runtime: The published wiring, resolved by ``api_runtime``.

    Returns:
        The one store of user and service-account identities every request
        in this process shares.
    """
    return runtime.principals


Repository = Annotated[HierarchyRepository, Depends(api_repository)]
Ingest = Annotated[IngestService, Depends(api_ingest)]
Revisions = Annotated[RevisionService, Depends(api_revisions)]
Settings = Annotated[ApiSettings, Depends(api_settings)]
ApiKeys = Annotated[ApiKeyWriter, Depends(api_api_keys)]
Credentials = Annotated[CredentialStore, Depends(api_credentials)]
Sessions = Annotated[SessionStore, Depends(api_sessions)]
Principals = Annotated[PrincipalStore, Depends(api_principals)]

__all__ = [
    "ApiKeys",
    "ApiRuntime",
    "ApiStores",
    "Credentials",
    "Ingest",
    "Principals",
    "Repository",
    "Revisions",
    "Runtime",
    "Sessions",
    "Settings",
    "api_api_keys",
    "api_credentials",
    "api_ingest",
    "api_principals",
    "api_repository",
    "api_revisions",
    "api_runtime",
    "api_sessions",
    "api_settings",
]
