"""What the composition root wired, and how a request reaches it.

``create_app`` builds an :class:`ApiRuntime` once, in the lifespan, and
publishes it as the application's only piece of mutable state. Path
operations and guards declare ``Runtime``/``Settings`` rather than a
``Request``: ``api_runtime`` below is the one function in the tier that
reaches through the request to read what the app was wired with.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

import asyncpg
from fastapi import Depends, Request

from huron.core.foundation.clock import Clock
from huron.core.raw import RawRuntime
from huron.core.security import CredentialAuthentication, OidcAuthentication, PasswordAuthentication
from huron.core.security.dev import DevHeaderResolver
from huron.core.security.facts import BindingFacts, CatalogFacts
from huron.core.security.oidc import OidcClient, OidcResolver
from huron.core.security.password import CredentialStore
from huron.core.security.ports import ApiKeyWriter, RbacStore
from huron.core.security.principals import PrincipalStore
from huron.core.security.rules import RoleBindingAuthorizer
from huron.core.security.sessions import SessionStore

from .capabilities import HierarchyStore, Storage
from .settings import ApiSettings


@dataclass(frozen=True, slots=True)
class ApiStores:
    """The hierarchy, RBAC and authentication stores a deployment wires as one unit.

    Bundling all six together gives the composition root one shape to
    build - Postgres in production, process memory in a test - and gives a
    test exactly one object to inject in place of that wiring.

    Attributes:
        hierarchy: Durable storage for the organization/project/dataset
            hierarchy and its idempotency claims.
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
    raw_store: Storage
    hierarchy: HierarchyStore
    rbac: RbacStore
    raw: RawRuntime
    authorizer: RoleBindingAuthorizer
    api_keys: ApiKeyWriter
    credentials: CredentialStore
    sessions: SessionStore
    principals: PrincipalStore
    oidc_resolver: OidcResolver | None
    oidc_client: OidcClient | None
    database_pool: asyncpg.Pool | None
    clock: Clock


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


async def api_settings(runtime: Runtime) -> ApiSettings:
    """Return the validated settings the service was wired with.

    Args:
        runtime: The published wiring, resolved by ``api_runtime``.

    Returns:
        The settings ``create_app`` was given; the same object for every
        request.
    """
    return runtime.settings


def credential_authentication(runtime: Runtime) -> CredentialAuthentication:
    """Wire credential resolution from plain deployment choices and persistence ports.

    Args:
        runtime: The published wiring, resolved by ``api_runtime``.

    Returns:
        The reusable credential resolution operation.
    """
    return CredentialAuthentication(
        runtime.api_keys,
        runtime.sessions,
        clock=runtime.clock,
        oidc=runtime.oidc_resolver,
        development=(
            DevHeaderResolver("development")
            if runtime.settings.auth_mode == "dev-headers"
            else None
        ),
    )


def password_authentication(runtime: Runtime) -> PasswordAuthentication:
    """Wire password login without exposing settings to Security.

    Args:
        runtime: The published wiring, resolved by ``api_runtime``.

    Returns:
        The reusable password login operation.
    """
    return PasswordAuthentication(
        runtime.principals,
        runtime.credentials,
        runtime.sessions,
        clock=runtime.clock,
        enabled=runtime.settings.password_login_enabled,
    )


def oidc_authentication(runtime: Runtime) -> OidcAuthentication:
    """Wire provider login and the transport's pending-state lifetime.

    Args:
        runtime: The published wiring, resolved by ``api_runtime``.

    Returns:
        The reusable OIDC begin/finish operation.
    """
    # Authorization dependencies consume Runtime; import its public cookie contract
    # at composition time, after both modules have initialized.
    from .authorization import login_flow_cookie

    return OidcAuthentication(
        runtime.oidc_client,
        runtime.principals,
        runtime.sessions,
        clock=runtime.clock,
        flow_secret=runtime.settings.login_flow_secret.encode(),
        flow_max_age=login_flow_cookie(runtime.settings).max_age,
    )


Settings = Annotated[ApiSettings, Depends(api_settings)]
PasswordAuth = Annotated[PasswordAuthentication, Depends(password_authentication)]
OidcAuth = Annotated[OidcAuthentication, Depends(oidc_authentication)]

__all__ = [
    "ApiRuntime",
    "ApiStores",
    "OidcAuth",
    "PasswordAuth",
    "Runtime",
    "Settings",
    "api_runtime",
    "api_settings",
    "credential_authentication",
    "oidc_authentication",
    "password_authentication",
]


async def api_hierarchy(runtime: Runtime) -> CatalogFacts:
    """Return committed catalog facts and typed readers.

    Args:
        runtime: The process wiring.

    Returns:
        The actual hierarchy adapter.
    """
    return runtime.hierarchy


async def api_binding_facts(runtime: Runtime) -> BindingFacts:
    """Return current binding and service-account facts.

    Args:
        runtime: The process wiring.

    Returns:
        The actual RBAC adapter.
    """
    return runtime.rbac


Hierarchy = Annotated[CatalogFacts, Depends(api_hierarchy)]
Bindings = Annotated[BindingFacts, Depends(api_binding_facts)]
