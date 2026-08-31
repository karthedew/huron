"""Request authorization for the HTTP surface.

The chain every guarded route goes through, all via FastAPI ``Depends``:

1. ``current_principal`` turns the request's credential into an
   ``auth.Principal`` - an ``hk_`` bearer token resolves as an API key,
   any other bearer token resolves as an OIDC JWT through the verifier the
   composition root injected, and (development only) ``X-Huron-*`` headers
   resolve directly.
2. A ``require_*`` dependency builds the request's scope (organization /
   project / dataset, with ancestry for inheritance) and asks the pure
   ``rbac.decide`` engine whether the principal's compiled role bindings
   allow the capability. Deny -> 403 before the route body runs.

Routes therefore never re-check permissions; holding a ``Principal`` returned
by one of these dependencies IS the proof the check passed.
"""

from __future__ import annotations

import hmac
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated
from uuid import UUID

from fastapi import Depends, Request

from huron.pkg.auth import (
    ABSOLUTE_TTL,
    ApiKeyResolver,
    AuthError,
    DevHeaderResolver,
    Principal,
    SessionResolver,
    parse_api_key,
)
from huron.pkg.catalog.errors import DomainError
from huron.pkg.catalog.layers import (
    Layer,
    LayerAction,
    ensure_layer_writable,
    parse_layer,
    required_capability,
)
from huron.pkg.rbac import Binding, Decision, Scope, ScopeType, decide
from huron.pkg.rbac import Principal as RbacPrincipal

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from fastapi import Response

    from huron.pkg.auth import SessionRecord

    from .repository import ApiKeyWriter, HierarchyRepository
    from .settings import ApiSettings

logger = logging.getLogger(__name__)

#: Matches ``ApiSettings.session_cookie_name``'s default; used whenever a
#: request carries no settings at all (a bare ASGI scope in a unit test).
DEFAULT_SESSION_COOKIE_NAME = "huron_session"

#: The transient OIDC pending-login cookie name and lifetime - unlike the
#: session cookie, this name isn't settings-configurable (it never leaves
#: the ``/auth`` path) and its lifetime doubles as ``LoginFlow.decode``'s
#: ``max_age``, so a flow the browser still holds a cookie for is never
#: rejected as stale, and a flow the browser has forgotten is never accepted.
LOGIN_FLOW_COOKIE_NAME = "huron_login"
LOGIN_FLOW_COOKIE_MAX_AGE = 600  # seconds


class Forbidden(DomainError):
    code, status_code = "FORBIDDEN", 403


def get_repository(request: Request) -> HierarchyRepository:
    repository: HierarchyRepository = request.app.state.repository
    return repository


def get_settings(request: Request) -> ApiSettings:
    """The composition root always sets ``app.state.settings`` - both the
    lifespan and the eager fallback for a directly-injected repository
    (``create_app``) do it unconditionally, so this is never optional the
    way ``oidc_resolver``/``oidc_client`` are."""
    settings: ApiSettings = request.app.state.settings
    return settings


async def current_principal(request: Request) -> Principal:
    """Resolve the request credential to a principal, or 401.

    Bearer credentials keep absolute priority: a programmatic caller that
    happens to carry a cookie jar must never be silently downgraded to a
    session principal. Only once there is no ``Authorization`` header at
    all does a session cookie get a look, and only after that does the
    development-only header fallback apply.
    """
    authorization = request.headers.get("authorization")
    if authorization:
        token = authorization.removeprefix("Bearer ").strip()
        if token.startswith("hk_"):
            store = get_repository(request).api_keys
            principal = await ApiKeyResolver(store).resolve(token)
            await _touch_api_key(store, token)
            return principal
        oidc_resolver = getattr(request.app.state, "oidc_resolver", None)
        if oidc_resolver is None:
            raise AuthError("bearer JWTs are not accepted: no OIDC verifier configured")
        principal = await oidc_resolver.resolve(token)
        return principal
    token = request.cookies.get(_cookie_name(request))
    if token:
        resolver = SessionResolver(get_repository(request).sessions)
        principal, session = await resolver.resolve(token)
        _enforce_csrf(request, session)
        request.state.session = session
        return principal
    settings = getattr(request.app.state, "settings", None)
    if settings is not None and settings.auth_mode != "dev-headers":
        raise AuthError("a bearer credential is required")
    return DevHeaderResolver("development").resolve_headers(request.headers)


async def _touch_api_key(store: ApiKeyWriter, credential: str) -> None:
    """Best-effort last-used bookkeeping; a write failure here must never
    turn a valid credential into a failed request."""
    try:
        key_id, _secret = parse_api_key(credential)
        await store.touch_last_used(key_id)
    except Exception:
        logger.warning("failed to record API key last-used timestamp", exc_info=True)


def _cookie_name(request: Request) -> str:
    settings = getattr(request.app.state, "settings", None)
    name = getattr(settings, "session_cookie_name", None)
    return name if name else DEFAULT_SESSION_COOKIE_NAME


def _enforce_csrf(request: Request, session: SessionRecord) -> None:
    """Cookie-authenticated state changes must echo the session's CSRF token.

    Bearer paths are exempt (headers cannot be set cross-site by an
    attacker's page, so a bearer caller needs no proof beyond the token
    itself); GET/HEAD/OPTIONS are exempt (they must stay side-effect-free
    anyway). The token reaches the browser in the login response and in
    ``GET /auth/session``.
    """
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    # Starlette decodes header bytes as latin-1, so this never raises even
    # for a header containing non-ASCII bytes; compare_digest itself would
    # (it refuses non-ASCII str), so both sides are compared as bytes.
    supplied = request.headers.get("x-huron-csrf", "").encode("latin-1")
    if not hmac.compare_digest(supplied, session.csrf_token.encode()):
        raise AuthError("missing or invalid X-Huron-CSRF header")


def set_session_cookie(response: Response, settings: ApiSettings, token: str) -> None:
    """Set the session cookie with the attributes every login path shares."""
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=int(ABSOLUTE_TTL.total_seconds()),
        path="/",
        httponly=True,
        samesite="lax",
        secure=settings.env != "development",
    )


def clear_session_cookie(response: Response, settings: ApiSettings) -> None:
    """Undo :func:`set_session_cookie`; attributes must match for the browser
    to recognize this as clearing the same cookie rather than setting an
    unrelated one it then leaves alone."""
    response.delete_cookie(
        settings.session_cookie_name,
        path="/",
        httponly=True,
        samesite="lax",
        secure=settings.env != "development",
    )


def set_login_flow_cookie(response: Response, settings: ApiSettings, value: str) -> None:
    """Set the pending-login cookie: the PKCE verifier, nonce and state ride
    here, HMAC-signed, between ``/auth/oidc/start`` and the callback. Same
    ``Secure``-outside-development rule as the session cookie - the flow
    cookie is short-lived, but it still carries the material that lets the
    callback trust an in-flight OIDC exchange."""
    response.set_cookie(
        LOGIN_FLOW_COOKIE_NAME,
        value,
        max_age=LOGIN_FLOW_COOKIE_MAX_AGE,
        path="/auth",
        httponly=True,
        samesite="lax",
        secure=settings.env != "development",
    )


def clear_login_flow_cookie(response: Response, settings: ApiSettings) -> None:
    """Undo :func:`set_login_flow_cookie`; attributes must match for the
    browser to recognize this as clearing the same cookie."""
    response.delete_cookie(
        LOGIN_FLOW_COOKIE_NAME,
        path="/auth",
        httponly=True,
        samesite="lax",
        secure=settings.env != "development",
    )


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]


def as_rbac_principal(principal: Principal) -> RbacPrincipal:
    return RbacPrincipal(subject=principal.subject, groups=principal.groups, kind=principal.kind)


async def cached_bindings_for(
    request: Request, repository: HierarchyRepository, identifiers: frozenset[str]
) -> tuple[Binding, ...]:
    """Memoize ``bindings_for`` by identifier set for the life of one request.

    A single route commonly needs the caller's bindings more than once (a
    ``require_*`` guard, then a layer-workflow listing that decides per
    layer) - without this, each of those would re-issue the same join query.
    The cache lives on ``request.state`` deliberately: it must not survive
    past the request, since a mid-request role change should never apply
    retroactively to bindings already fetched, and it must never leak
    between requests or principals.
    """
    cache: dict[frozenset[str], tuple[Binding, ...]] | None = getattr(
        request.state, "binding_cache", None
    )
    if cache is None:
        cache = {}
        request.state.binding_cache = cache
    if identifiers not in cache:
        cache[identifiers] = await repository.bindings_for(identifiers)
    return cache[identifiers]


async def check(
    request: Request,
    principal: Principal,
    capability: str,
    scope: Scope,
    *,
    layer: str | None = None,
) -> None:
    """403 unless the principal's role bindings allow ``capability`` here."""
    actor = as_rbac_principal(principal)
    bindings = await cached_bindings_for(request, get_repository(request), actor.identifiers)
    if decide(bindings, actor, capability, scope, layer=layer) is not Decision.ALLOW:
        suffix = f" on layer {layer}" if layer else ""
        raise Forbidden(
            f"{capability}{suffix} denied for {principal.subject} at {scope.scope_type.value} scope"
        )


def organization_scope(repository: HierarchyRepository, organization_id: UUID) -> Scope:
    repository.get_organization(organization_id)  # 404 before 403 for unknown ids
    return Scope(ScopeType.ORGANIZATION, organization_id, organization_id=organization_id)


def project_scope(repository: HierarchyRepository, project_id: UUID) -> Scope:
    project = repository.get_project(project_id)
    return Scope(
        ScopeType.PROJECT,
        project_id,
        organization_id=project.organization_id,
        project_id=project_id,
    )


def dataset_scope(repository: HierarchyRepository, dataset_id: UUID) -> Scope:
    dataset = repository.get_dataset(dataset_id)
    project = repository.get_project(dataset.project_id)
    return Scope(
        ScopeType.DATASET,
        dataset_id,
        organization_id=project.organization_id,
        project_id=project.id,
        dataset_id=dataset_id,
    )


def require_system(capability: str) -> Callable[..., Awaitable[Principal]]:
    """Guard a platform-scope route (e.g. ``organization.create``)."""

    async def dependency(request: Request, principal: CurrentPrincipal) -> Principal:
        await check(request, principal, capability, Scope.system())
        return principal

    return dependency


def require_organization(capability: str) -> Callable[..., Awaitable[Principal]]:
    """Guard a route addressing one organization (path: ``organization_id``)."""

    async def dependency(
        request: Request, organization_id: UUID, principal: CurrentPrincipal
    ) -> Principal:
        scope = organization_scope(get_repository(request), organization_id)
        await check(request, principal, capability, scope)
        return principal

    return dependency


def require_project(capability: str) -> Callable[..., Awaitable[Principal]]:
    """Guard a route addressing one project (path: ``project_id``)."""

    async def dependency(
        request: Request, project_id: UUID, principal: CurrentPrincipal
    ) -> Principal:
        scope = project_scope(get_repository(request), project_id)
        await check(request, principal, capability, scope)
        return principal

    return dependency


def require_dataset(capability: str) -> Callable[..., Awaitable[Principal]]:
    """Guard a route addressing one dataset (path: ``dataset_id``)."""

    async def dependency(
        request: Request, dataset_id: UUID, principal: CurrentPrincipal
    ) -> Principal:
        scope = dataset_scope(get_repository(request), dataset_id)
        await check(request, principal, capability, scope)
        return principal

    return dependency


@dataclass(frozen=True, slots=True)
class LayerWrite:
    principal: Principal
    layer: Layer


async def dataset_layer_writer(
    request: Request, dataset_id: UUID, layer: str, principal: CurrentPrincipal
) -> LayerWrite:
    """Guard a data-plane write: layer rule first, then the binding check.

    ``ensure_layer_writable`` refuses human principals on silver/gold no
    matter what bindings exist (defense in depth); ``check`` then requires a
    ``data.write`` binding covering this dataset and this layer.
    """
    parsed = parse_layer(layer)
    ensure_layer_writable(parsed, principal.kind)
    capability, layer_code = required_capability(LayerAction.WRITE, parsed)
    scope = dataset_scope(get_repository(request), dataset_id)
    await check(request, principal, capability, scope, layer=layer_code)
    return LayerWrite(principal=principal, layer=parsed)


__all__ = [
    "DEFAULT_SESSION_COOKIE_NAME",
    "LOGIN_FLOW_COOKIE_MAX_AGE",
    "LOGIN_FLOW_COOKIE_NAME",
    "CurrentPrincipal",
    "Forbidden",
    "LayerWrite",
    "as_rbac_principal",
    "cached_bindings_for",
    "check",
    "clear_login_flow_cookie",
    "clear_session_cookie",
    "current_principal",
    "dataset_layer_writer",
    "dataset_scope",
    "get_repository",
    "get_settings",
    "organization_scope",
    "project_scope",
    "require_dataset",
    "require_organization",
    "require_project",
    "require_system",
    "set_login_flow_cookie",
    "set_session_cookie",
]
