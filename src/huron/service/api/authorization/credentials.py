"""Request credential -> Principal, or 401.

Bearer credentials keep absolute priority: a programmatic caller carrying a
cookie jar is never silently downgraded to a session principal. Only once
there is no ``Authorization`` header at all does the session cookie get a
look, and only after that does the development-only header fallback apply.
CSRF is enforced in the cookie branch and only there.
"""

from __future__ import annotations

import hmac
import logging
from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Request

from huron.pkg.auth import (
    ApiKeyResolver,
    AuthError,
    DevHeaderResolver,
    Principal,
    SessionRecord,
    SessionResolver,
    parse_api_key,
)

from ..runtime import Runtime
from .cookies import session_cookie

if TYPE_CHECKING:
    from ..stores import ApiKeyWriter

logger = logging.getLogger(__name__)


async def current_principal(request: Request, runtime: Runtime) -> Principal:
    """Resolve the request credential to a principal, or 401.

    Bearer credentials keep absolute priority: a programmatic caller that
    happens to carry a cookie jar must never be silently downgraded to a
    session principal. Only once there is no ``Authorization`` header at
    all does a session cookie get a look, and only after that does the
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

    Raises:
        AuthError: If a JWT is presented but no OIDC verifier is
            configured, or if no credential of any kind is present outside
            ``dev-headers`` mode.
    """
    authorization = request.headers.get("authorization")
    if authorization:
        token = authorization.removeprefix("Bearer ").strip()
        if token.startswith("hk_"):
            store = runtime.api_keys
            principal = await ApiKeyResolver(store).resolve(token)
            await _touch_api_key(store, token)
            return principal
        if runtime.oidc_resolver is None:
            raise AuthError("bearer JWTs are not accepted: no OIDC verifier configured")
        return await runtime.oidc_resolver.resolve(token)
    session_token = session_cookie(runtime.settings).read(request)
    if session_token:
        resolver = SessionResolver(runtime.sessions)
        principal, session = await resolver.resolve(session_token)
        _enforce_csrf(request, session)
        request.state.session = session
        return principal
    if runtime.settings.auth_mode != "dev-headers":
        raise AuthError("a bearer credential is required")
    return DevHeaderResolver("development").resolve_headers(request.headers)


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


async def _touch_api_key(store: ApiKeyWriter, credential: str) -> None:
    """Record that an API key was just used, without ever failing the request.

    Best-effort last-used bookkeeping; a write failure here must never
    turn a valid credential into a failed request. Any exception is logged
    with its traceback and swallowed, so the caller sees the same outcome
    whether or not the timestamp landed.

    Args:
        store: The key store whose ``touch_last_used`` records the moment.
        credential: The full ``hk_`` token, already accepted by the
            resolver; only its key id is used.
    """
    try:
        key_id, _secret = parse_api_key(credential)
        await store.touch_last_used(key_id)
    except Exception:
        logger.warning("failed to record API key last-used timestamp", exc_info=True)


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
