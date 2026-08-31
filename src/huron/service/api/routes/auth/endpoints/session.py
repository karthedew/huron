"""Identity introspection and login-method discovery.

``GET /providers`` is deliberately unauthenticated - the login page has no
principal yet when it needs to know what to render.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from huron.service.api.authorization import CurrentPrincipal, get_settings
from huron.service.api.routes.auth.schema.session import ProviderInfo, SessionInfo

router = APIRouter()


@router.get("/session")
async def session_info(request: Request, actor: CurrentPrincipal) -> SessionInfo:
    session = getattr(request.state, "session", None)
    return SessionInfo(
        subject=actor.subject,
        kind=actor.kind,
        groups=sorted(actor.groups),
        authentication_method=actor.authentication_method,
        csrf_token=session.csrf_token if session is not None else None,
        expires_at=session.absolute_expires_at if session is not None else None,
    )


@router.get("/providers")
async def providers(request: Request) -> ProviderInfo:
    settings = get_settings(request)
    return ProviderInfo(
        password=settings.password_login_enabled,
        oidc=settings.oidc is not None,
        oidc_start_url="/auth/oidc/start" if settings.oidc is not None else None,
    )
