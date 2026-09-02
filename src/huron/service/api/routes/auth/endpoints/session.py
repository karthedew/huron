"""Identity introspection and login-method discovery.

``GET /providers`` is deliberately unauthenticated - the login page has no
principal yet when it needs to know what to render.
"""

from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from fastapi import APIRouter

from huron.service.api.authorization import (
    BindingCache,
    CurrentPrincipal,
    CurrentSession,
    as_rbac_principal,
    bindings_for_principal,
)
from huron.service.api.problems import problem_response
from huron.service.api.routes.auth.schema.session import ProviderInfo, ScopeRoles, SessionInfo
from huron.service.api.runtime import Repository, Settings

router = APIRouter()


@router.get("/session", responses={401: problem_response("no usable credential")})
async def session_info(
    actor: CurrentPrincipal,
    session: CurrentSession,
    repository: Repository,
    cache: BindingCache,
) -> SessionInfo:
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
    return ProviderInfo(
        password=settings.password_login_enabled,
        oidc=settings.oidc is not None,
        oidc_start_url="/auth/oidc/start" if settings.oidc is not None else None,
    )
