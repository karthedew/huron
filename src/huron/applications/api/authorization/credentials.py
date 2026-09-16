"""Request credential -> Principal, or 401.

Bearer credentials keep absolute priority: a programmatic caller carrying a
cookie jar is never silently downgraded to a session principal. Only once
there is no nonempty ``Authorization`` header does the session cookie get a
look, and only after that does the development-only header fallback apply.
CSRF is enforced in the cookie branch and only there.
"""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Depends, Request

from huron.core.security.authentication_errors import AuthError
from huron.core.security.principal import Principal
from huron.core.security.sessions import SessionRecord

from ..runtime import Runtime, credential_authentication
from .cookies import session_cookie


async def current_principal(request: Request, runtime: Runtime) -> Principal:
    """Resolve the request credential to a principal, or 401.

    Bearer credentials keep absolute priority: a programmatic caller that
    happens to carry a cookie jar must never be silently downgraded to a
    session principal. Only once there is no nonempty ``Authorization`` header
    does a session cookie get a look, and only after that does the
    development-only header fallback apply. Within the bearer branch an
    ``hk_`` token is an API key and anything else is an OIDC JWT, which is
    refused outright when no verifier is configured rather than guessed
    at. A session principal additionally passes the CSRF check, and the
    session is left on ``request.state`` for ``current_session``.

    Args:
        request: The request whose ``Authorization`` header, cookies and -
            in development - ``X-Huron-*`` headers are read.
        runtime: The published wiring: the key and session stores, the
            optional OIDC resolver and the settings that name the session
            cookie and the auth mode.

    Returns:
        The authenticated principal, with ``authentication_method`` saying
        which branch produced it.

    """
    authorization = request.headers.get("authorization")
    bearer_token = authorization.removeprefix("Bearer ").strip() if authorization else None
    resolved = await credential_authentication(runtime).resolve(
        bearer_token=bearer_token,
        session_token=session_cookie(runtime.settings).read(request),
        development_headers={
            "x-huron-subject": request.headers.get("x-huron-subject", ""),
            "x-huron-groups": request.headers.get("x-huron-groups", ""),
        },
    )
    if resolved.session is not None:
        _enforce_csrf(request, resolved.session)
        request.state.session = resolved.session
    return resolved.actor


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]


async def current_session(request: Request, _actor: CurrentPrincipal) -> SessionRecord | None:
    """Return the session behind this request, if the caller authenticated with one.

    Set by ``current_principal``'s cookie branch, which is why this depends
    on it: a bearer caller has no session and correctly gets ``None``.

    Args:
        request: The request whose ``state.session`` the cookie branch may
            have set.
        _actor: The resolved principal; unused except to order this
            dependency after credential resolution.

    Returns:
        The session record for a cookie-authenticated caller, or ``None``
        for a bearer or dev-header one.
    """
    session: SessionRecord | None = getattr(request.state, "session", None)
    return session


CurrentSession = Annotated[SessionRecord | None, Depends(current_session)]


def _enforce_csrf(request: Request, session: SessionRecord) -> None:
    """Require a cookie-authenticated state change to echo the session's CSRF token.

    Cookie-authenticated state changes must echo the session's CSRF token.
    Bearer paths are exempt (headers cannot be set cross-site by an
    attacker's page, so a bearer caller needs no proof beyond the token
    itself); GET/HEAD/OPTIONS are exempt (they must stay side-effect-free
    anyway). The token reaches the browser in the login response and in
    ``GET /auth/session``. The comparison is constant-time and made on
    bytes, so a header holding non-ASCII bytes is a mismatch rather than
    an exception.

    Args:
        request: The request whose method and ``X-Huron-CSRF`` header are
            checked.
        session: The session the cookie resolved to, holding the expected
            token.

    Raises:
        AuthError: If a mutating request's ``X-Huron-CSRF`` header is
            missing or does not equal the session's token.
    """
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    # Starlette decodes header bytes as latin-1, so this never raises even
    # for a header containing non-ASCII bytes; compare_digest itself would
    # (it refuses non-ASCII str), so both sides are compared as bytes.
    supplied = request.headers.get("x-huron-csrf", "").encode("latin-1")
    if not hmac.compare_digest(supplied, session.csrf_token.encode()):
        raise AuthError("missing or invalid X-Huron-CSRF header")
