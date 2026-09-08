"""The browser half of the OIDC code flow.

``/start`` redirects the browser to the identity provider; the provider
sends it back to ``/callback`` with a code to exchange for a session.
Pending-login state (state, nonce, PKCE verifier) rides in an HMAC-signed
``huron_login`` cookie between the two routes rather than server-side
storage - see :class:`~huron.pkg.auth.LoginFlow`. The cookie is signed with
the deployment's ``login_flow_secret``, and the callback lands the browser
on the web application at ``web_app_url``.
"""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from huron.applications.api.authorization import login_flow_cookie, session_cookie
from huron.applications.api.problems import problem_response
from huron.applications.api.runtime import Principals, Runtime, Sessions, Settings
from huron.applications.api.settings import ApiSettings
from huron.pkg.auth import (
    AuthError,
    LoginFlow,
    OidcClient,
    PrincipalSubjectExists,
    code_challenge_s256,
    create_session,
)
from huron.pkg.catalog.failures import OidcNotConfigured, UsernameTaken

router = APIRouter(prefix="/oidc")


async def _configured_oidc_client(runtime: Runtime) -> OidcClient:
    """Return the identity-provider client the composition root wired, or refuse.

    Both OIDC routes depend on this, so a deployment with no identity
    provider answers them with the ``OIDC_NOT_CONFIGURED`` 404 rather than
    reaching a handler that has no client to call.

    Args:
        runtime: The wiring the application lifespan published.

    Returns:
        The client for the configured identity provider.

    Raises:
        OidcNotConfigured: If the deployment has no identity provider.
    """
    if runtime.oidc_client is None:
        raise OidcNotConfigured("no identity provider is configured")
    return runtime.oidc_client


_Client = Annotated[OidcClient, Depends(_configured_oidc_client)]


def _flow_secret(settings: ApiSettings) -> bytes:
    """Return the key that signs and verifies the pending-login cookie.

    Args:
        settings: The API settings; ``login_flow_secret`` is required outside
            development, so a signed flow cannot be forged by anyone who
            has not read the deployment's configuration.

    Returns:
        The secret as HMAC key bytes.
    """
    return settings.login_flow_secret.encode()


def _safe_return_path(return_to: str) -> str:
    """Return ``return_to`` if it is a local path, else the application root.

    A caller-supplied redirect target that isn't a local path is dropped
    in favor of the app root rather than rejecting the login outright -
    ``LoginFlow`` itself still refuses one at decode time as a backstop.

    Args:
        return_to: The path the caller asked to land on after login.

    Returns:
        ``return_to`` when it starts with a single ``/``, otherwise ``/``.
    """
    if not return_to.startswith("/") or return_to.startswith("//"):
        return "/"
    return return_to


def _app_url(settings: ApiSettings, return_to: str) -> str:
    """Return the web-application URL the callback sends the browser to.

    Args:
        settings: The API settings; ``web_app_url`` is where the web
            application is served, with or without a trailing slash.
        return_to: The local path the login flow carried, starting with
            ``/``.

    Returns:
        ``web_app_url`` joined to ``return_to`` with exactly one slash.
    """
    return settings.web_app_url.rstrip("/") + return_to


@router.get(
    "/start",
    status_code=302,
    response_class=RedirectResponse,
    responses={404: problem_response("no identity provider is configured")},
)
async def oidc_start(client: _Client, settings: Settings, return_to: str = "/") -> RedirectResponse:
    """Begin a browser login with the configured identity provider.

    Needs no credential. Answers 302 to the provider's authorization
    endpoint, with PKCE, and sets the transient ``huron_login`` cookie that
    the callback needs to finish the flow; the cookie lives ten minutes and
    never leaves ``/auth``. ``return_to`` is the local path the browser lands
    on once login completes; a value that is not a local path is replaced
    by ``/`` rather than refused. Answers 404 when this deployment has no
    identity provider.
    \f
    Args:
        client: The client for the configured identity provider.
        settings: The wired API settings; supplies the flow-signing secret
            and the cookie attributes.
        return_to: The caller's requested landing path, sanitized by
            ``_safe_return_path`` before it enters the flow.

    Returns:
        The redirect to the provider, carrying the login-flow cookie.
    """
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
        401: problem_response(
            "the login flow or the provider's response could not be trusted, "
            "or the principal is disabled"
        ),
        409: problem_response("the subject is already held by a local account"),
    },
)
async def oidc_callback(
    request: Request,
    code: str,
    state: str,
    client: _Client,
    settings: Settings,
    principals: Principals,
    sessions: Sessions,
) -> RedirectResponse:
    """Finish a browser login: exchange the provider's code for a session.

    The identity provider sends the browser here with ``code`` and
    ``state``. The pending login is read from the ``huron_login`` cookie
    that ``/auth/oidc/start`` set; ``state`` must match it, and the code is
    exchanged and the resulting ID token verified against the provider. A
    first login provisions the user, a later one refreshes the display
    name. A local account is never auto-linked to an identity provider: if
    this is a first-ever login for the provider's subject and that subject
    is already a local account's username, the login is refused rather
    than the two identities merged. A disabled principal never gets a
    session, no matter how it was provisioned - the same refusal a
    disabled password login answers. On success the session cookie is set,
    the login cookie is cleared and the browser is sent, 302, to the web
    application at the path the flow was started with. Answers 401 when
    the login cookie is missing, expired or forged, when ``state`` does
    not match, when the provider's response cannot be trusted, or when the
    principal is disabled; 404 when this deployment has no identity
    provider; 409 when the provider's subject collides with an existing
    local account's username.
    \f
    Args:
        request: The incoming request; the login-flow cookie is read from it.
        code: The authorization code the provider issued.
        state: The provider's echo of the ``state`` the flow was started with.
        client: The client for the configured identity provider.
        settings: The wired API settings; supplies the flow-signing secret,
            the cookie attributes and the web application URL.
        principals: The wired principal store.
        sessions: The wired session store.

    Returns:
        The redirect into the web application, carrying the session cookie
        and clearing the login-flow cookie.

    Raises:
        AuthError: If ``state`` does not match the pending login the cookie
            describes, or if the resolved principal is disabled.
        UsernameTaken: If this is a first-ever login for the provider's
            subject and some local account already holds it as its
            username.
    """
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
    try:
        principal_row = await principals.upsert_oidc_user(user)
    except PrincipalSubjectExists as exc:
        raise UsernameTaken(str(exc)) from exc
    if principal_row.disabled_at is not None:
        raise AuthError(f"principal is disabled: {principal_row.subject}")
    record, token = create_session(
        principal_row.subject, groups=user.groups, authentication_method="oidc"
    )
    await sessions.add(record)
    response = RedirectResponse(_app_url(settings, login_flow.return_to), status_code=302)
    session_cookie(settings).issue(response, token)
    flow.revoke(response)
    return response
