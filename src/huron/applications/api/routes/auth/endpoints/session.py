"""Identity introspection and login-method discovery.

``GET /providers`` is deliberately unauthenticated - the login page has no
principal yet when it needs to know what to render.
"""

from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from fastapi import APIRouter

from huron.applications.api.authorization import (
    BindingCache,
    CurrentPrincipal,
    CurrentSession,
    as_rbac_principal,
    bindings_for_principal,
)
from huron.applications.api.problems import problem_response
from huron.applications.api.routes.auth.schema.session import ProviderInfo, ScopeRoles, SessionInfo
from huron.applications.api.runtime import Bindings, Settings

router = APIRouter()


@router.get("/session", responses={401: problem_response("no usable credential")})
async def session_info(
    actor: CurrentPrincipal,
    session: CurrentSession,
    repository: Bindings,
    cache: BindingCache,
) -> SessionInfo:
    """Describe the caller: who they are, how they authenticated, what they may do.

    Requires a credential (401 without one) but no particular role - every
    principal may ask about itself. ``effective_roles`` lists, per scope,
    the capabilities the caller's role bindings grant there, resolved from
    the same bindings every guarded route consults, so it cannot disagree
    with what the API will actually allow. ``csrf_token`` and
    ``expires_at`` are set only for a cookie session; a bearer credential
    has no server-side session and reports ``null`` for both.
    \f
    Args:
        actor: The principal the request credential resolved to.
        session: The session behind the credential, or ``None`` for a
            bearer caller.
        repository: The wired repository; supplies the role bindings.
        cache: The per-request binding cache shared with the guards.

    Returns:
        The caller's identity, groups, per-scope capabilities and, for a
        cookie session, its CSRF token and absolute expiry.
    """
    bindings = await bindings_for_principal(cache, repository, as_rbac_principal(actor))
    capabilities_by_scope: dict[tuple[str, UUID | None], set[str]] = defaultdict(set)
    for binding in bindings:
        capabilities_by_scope[(binding.scope_type.value, binding.scope_id)].update(
            binding.capabilities
        )
    return SessionInfo(
        subject=actor.subject,
        kind=actor.kind,
        groups=sorted(actor.groups),
        authentication_method=actor.authentication_method,
        effective_roles=[
            ScopeRoles(scope_type=scope_type, scope_id=scope_id, roles=sorted(capabilities))
            for (scope_type, scope_id), capabilities in sorted(
                capabilities_by_scope.items(),
                key=lambda entry: (entry[0][0], str(entry[0][1] or "")),
            )
        ],
        csrf_token=session.csrf_token if session is not None else None,
        expires_at=session.absolute_expires_at if session is not None else None,
    )


@router.get("/providers")
async def providers(settings: Settings) -> ProviderInfo:
    """List the login methods this deployment accepts.

    Needs no credential: the login page asks this before anyone is signed
    in. ``password`` says whether ``POST /auth/login`` is enabled; ``oidc``
    whether an identity provider is configured, in which case
    ``oidc_start_url`` is the path that begins a browser login and is
    ``null`` otherwise. It reveals nothing beyond what the login page must
    render.
    \f
    Args:
        settings: The wired API settings; supplies the password-login
            switch and the identity-provider configuration.

    Returns:
        Which login methods are available and where the OIDC flow starts.
    """
    return ProviderInfo(
        password=settings.password_login_enabled,
        oidc=settings.oidc is not None,
        oidc_start_url="/auth/oidc/start" if settings.oidc is not None else None,
    )
