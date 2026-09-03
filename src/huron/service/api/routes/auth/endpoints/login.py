"""Password login, and the logout that ends the session it started.

Login is the one route, besides OIDC's own start/callback pair, that a
caller reaches with no principal yet: it is where a password becomes a
session cookie. Logout is its counterpart and, like every other route,
requires a credential.
"""

from __future__ import annotations

from datetime import UTC, datetime

from anyio import CapacityLimiter
from asyncer import asyncify
from fastapi import APIRouter, Depends, Response

from huron.pkg.auth import AuthError, create_session, verify_password
from huron.service.api.authorization import CurrentSession, current_principal, session_cookie
from huron.service.api.problems import problem_response
from huron.service.api.routes.auth.schema.login import LoginResult, PasswordLogin, SignOut
from huron.service.api.runtime import Repository, Settings

router = APIRouter()

# Argon2id hashing is CPU- and memory-amplifying and this route is
# unauthenticated, so it gets its own queue instead of sharing the 40-token
# default threadpool limiter with every other blocking call in the service -
# bounding the worst case to 4 concurrent hashes rather than a service-wide
# memory spike.
_password_hash_limiter = CapacityLimiter(4)


@router.post(
    "/login",
    responses={401: problem_response("password login is disabled, or the credential is wrong")},
)
async def password_login(
    response: Response, body: PasswordLogin, settings: Settings, repository: Repository
) -> LoginResult:
    """Verify username and password, then start a session.

    Needs no credential. A successful login sets the session cookie and
    returns the subject, its display name and the session's CSRF token,
    which cookie-authenticated state-changing requests must echo in the
    ``X-Huron-CSRF`` header. Answers 401 when password login is disabled
    for this deployment, and 401 with one identical message - after the
    same amount of work - whether the username is unknown, the account is
    disabled, the name belongs to a service account, or the password is
    wrong, so the response reveals nothing about which it was.
    \f
    ``verify_password`` always runs its hash comparison, against a dummy
    hash when no credential exists - so an unknown username, a disabled
    account, a service-account subject, and a wrong password all cost the
    same wall-clock time and return the same message. The lookup's result is
    only dereferenced once ``verify_password`` has already said yes. The
    Argon2 comparison runs off the event loop, in a worker pool bounded to
    a handful of concurrent hashes.

    Args:
        response: The response the session cookie is set on.
        body: The username and password to verify.
        settings: The wired API settings; supplies the password-login
            switch and the cookie attributes.
        repository: The wired repository; supplies the principal,
            credential and session stores.

    Returns:
        The subject, display name and CSRF token of the session just started.

    Raises:
        AuthError: If password login is disabled, or the username and
            password do not name an enabled user with that password.
    """
    if not settings.password_login_enabled:
        raise AuthError("password login is disabled")
    principal_row = await repository.principals.get_user_by_subject(body.username)
    credential = (
        await repository.credentials.get(principal_row.id) if principal_row is not None else None
    )
    verified = await asyncify(verify_password, limiter=_password_hash_limiter)(
        credential, body.password
    )
    if not verified or principal_row is None:
        raise AuthError("invalid username or password")
    record, token = create_session(principal_row.subject, authentication_method="password")
    await repository.sessions.add(record)
    session_cookie(settings).issue(response, token)
    return LoginResult(
        subject=principal_row.subject,
        display_name=principal_row.display_name,
        csrf_token=record.csrf_token,
    )


@router.post(
    "/logout",
    dependencies=[Depends(current_principal)],
    responses={401: problem_response("no usable credential")},
)
async def logout(
    response: Response,
    settings: Settings,
    repository: Repository,
    session: CurrentSession,
) -> SignOut:
    """Revoke the session behind this request, if any, and clear the cookie.

    Requires a credential (401 without one) but no particular role. A
    cookie-authenticated caller must send the ``X-Huron-CSRF`` header, as
    on every state-changing request; its session is revoked and takes
    effect on the next request. A bearer caller has no session to revoke
    and is simply acknowledged. The cookie is cleared either way.
    \f
    Any credential may sign out - a bearer caller simply has no session to
    revoke - so a credential is required only to keep this route consistent
    with the rest of the API (an unauthenticated logout is a no-op that
    would tell an attacker nothing, but is also pointless to allow).

    Args:
        response: The response the session cookie is cleared on.
        settings: The wired API settings; supplies the cookie attributes.
        repository: The wired repository; supplies the session store.
        session: The session the credential resolved to, or ``None`` for a
            bearer caller.

    Returns:
        The ``signed-out`` acknowledgement.
    """
    if session is not None:
        await repository.sessions.revoke(session.id, datetime.now(UTC))
    session_cookie(settings).revoke(response)
    return SignOut(status="signed-out")
