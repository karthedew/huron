"""The browser half of the OIDC code flow: redirect to the IdP, then land
back here with a code to exchange.

Pending-login state (state, nonce, PKCE verifier) rides in an HMAC-signed
``huron_login`` cookie between the two routes rather than server-side
storage - see :class:`~huron.pkg.auth.LoginFlow`.
"""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from huron.pkg.auth import AuthError, LoginFlow, OidcClient, code_challenge_s256, create_session
from huron.service.api.authorization import login_flow_cookie, session_cookie
from huron.service.api.errors import OidcNotConfigured
from huron.service.api.problems import problem_response
from huron.service.api.runtime import Repository, Runtime, Settings
from huron.service.api.settings import ApiSettings

router = APIRouter(prefix="/oidc")


async def _configured_oidc_client(runtime: Runtime) -> OidcClient:
    if runtime.oidc_client is None:
        raise OidcNotConfigured("no identity provider is configured")
    return runtime.oidc_client


_Client = Annotated[OidcClient, Depends(_configured_oidc_client)]


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


@router.get(
    "/start",
    status_code=302,
    response_class=RedirectResponse,
    responses={404: problem_response("no identity provider is configured")},
)
async def oidc_start(client: _Client, settings: Settings, return_to: str = "/") -> RedirectResponse:
    flow = LoginFlow.new(return_to=_safe_return_path(return_to))
    url = client.authorization_url(
        state=flow.state,
        nonce=flow.nonce,
        code_challenge=code_challenge_s256(flow.code_verifier),
    )
    response = RedirectResponse(url, status_code=302)
    login_flow_cookie(settings).issue(response, flow.encode(_flow_secret(settings)))
    return response


@router.get(
    "/callback",
    status_code=302,
    response_class=RedirectResponse,
    responses={
        404: problem_response("no identity provider is configured"),
        401: problem_response("the login flow or the provider's response could not be trusted"),
    },
)
async def oidc_callback(
    request: Request,
    code: str,
    state: str,
    client: _Client,
    settings: Settings,
    repository: Repository,
) -> RedirectResponse:
    flow = login_flow_cookie(settings)
    login_flow = LoginFlow.decode(
        flow.read(request) or "",
        _flow_secret(settings),
        max_age=flow.max_age,
    )
    if not hmac.compare_digest(state, login_flow.state):
        raise AuthError("OIDC state mismatch")
    user = await client.exchange_code(
        code=code, code_verifier=login_flow.code_verifier, nonce=login_flow.nonce
    )
    principal_row = await repository.principals.upsert_oidc_user(user)
    record, token = create_session(
        principal_row.subject, groups=user.groups, authentication_method="oidc"
    )
    await repository.sessions.add(record)
    response = RedirectResponse(_app_url(settings, login_flow.return_to), status_code=302)
    session_cookie(settings).issue(response, token)
    flow.revoke(response)
    return response
