"""The browser half of the OIDC code flow: redirect to the IdP, then land
back here with a code to exchange.

Pending-login state (state, nonce, PKCE verifier) rides in an HMAC-signed
``huron_login`` cookie between the two routes rather than server-side
storage - see :class:`~huron.pkg.auth.LoginFlow`.
"""

from __future__ import annotations

import hmac

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from huron.pkg.auth import AuthError, LoginFlow, OidcClient, code_challenge_s256, create_session
from huron.service.api.authorization import (
    LOGIN_FLOW_COOKIE_MAX_AGE,
    LOGIN_FLOW_COOKIE_NAME,
    clear_login_flow_cookie,
    get_repository,
    get_settings,
    set_login_flow_cookie,
    set_session_cookie,
)
from huron.service.api.settings import ApiSettings

router = APIRouter()


def _oidc_client(request: Request) -> OidcClient:
    client = getattr(request.app.state, "oidc_client", None)
    if client is None:
        raise HTTPException(status_code=404, detail="OIDC is not configured")
    return client


def _flow_secret(settings: ApiSettings) -> bytes:
    return settings.login_flow_secret.encode()


def _safe_return_path(return_to: str) -> str:
    """A caller-supplied redirect target that isn't a local path is dropped
    in favor of the app root rather than rejecting the login outright -
    ``LoginFlow`` itself still refuses one at decode time as a backstop."""
    if not return_to.startswith("/") or return_to.startswith("//"):
        return "/"
    return return_to


def _app_url(settings: ApiSettings, return_to: str) -> str:
    return settings.web_app_url.rstrip("/") + return_to


@router.get("/oidc/start")
async def oidc_start(request: Request, return_to: str = "/") -> RedirectResponse:
    client = _oidc_client(request)
    settings = get_settings(request)
    flow = LoginFlow.new(return_to=_safe_return_path(return_to))
    url = client.authorization_url(
        state=flow.state,
        nonce=flow.nonce,
        code_challenge=code_challenge_s256(flow.code_verifier),
    )
    response = RedirectResponse(url, status_code=302)
    set_login_flow_cookie(response, settings, flow.encode(_flow_secret(settings)))
    return response


@router.get("/oidc/callback")
async def oidc_callback(request: Request, code: str, state: str) -> RedirectResponse:
    settings = get_settings(request)
    flow = LoginFlow.decode(
        request.cookies.get(LOGIN_FLOW_COOKIE_NAME, ""),
        _flow_secret(settings),
        max_age=LOGIN_FLOW_COOKIE_MAX_AGE,
    )
    if not hmac.compare_digest(state, flow.state):
        raise AuthError("OIDC state mismatch")
    client = _oidc_client(request)
    user = await client.exchange_code(code=code, code_verifier=flow.code_verifier, nonce=flow.nonce)
    repository = get_repository(request)
    principal_row = await repository.principals.upsert_oidc_user(user)
    record, token = create_session(
        principal_row.subject, groups=user.groups, authentication_method="oidc"
    )
    await repository.sessions.add(record)
    response = RedirectResponse(_app_url(settings, flow.return_to), status_code=302)
    set_session_cookie(response, settings, token)
    clear_login_flow_cookie(response, settings)
    return response
