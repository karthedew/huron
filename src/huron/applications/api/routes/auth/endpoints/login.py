"""Password login, and the logout that ends the session it started.

Login is the one route, besides OIDC's own start/callback pair, that a
caller reaches with no principal yet: it is where a password becomes a
session cookie. Logout is its counterpart and, like every other route,
requires a credential.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from huron.applications.api.authorization import (
    CurrentPrincipal,
    CurrentSession,
    current_principal,
    session_cookie,
)
from huron.applications.api.problems import problem_response
from huron.applications.api.routes.auth.schema.login import LoginResult, PasswordLogin, SignOut
from huron.applications.api.runtime import PasswordAuth, Runtime, Settings
from huron.core.security import terminate_session

router = APIRouter()


@router.post(
    "/login",
    responses={401: problem_response("password login is disabled, or the credential is wrong")},
)
async def password_login(
    response: Response,
    body: PasswordLogin,
    settings: Settings,
    authentication: PasswordAuth,
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
    a handful of concurrent hashes. Once verified, a hash left over from a
    weaker Argon2 cost is replaced with a fresh one of the same password, on
    the same worker pool; the write is best-effort and its failure is logged,
    never raised, because the caller already proved they hold the password
    and a housekeeping write is not a reason to refuse the login it follows.

    Args:
        response: The response the session cookie is set on.
        body: The username and password to verify.
        settings: The wired API settings; supplies the password-login
            switch and the cookie attributes.
        authentication: The reusable password authentication operation.

    Returns:
        The subject, display name and CSRF token of the session just started.

    """
    login = await authentication.login(body.username, body.password)
    session_cookie(settings).issue(response, login.token)
    return LoginResult(
        subject=login.session.subject,
        display_name=login.display_name,
        csrf_token=login.session.csrf_token,
    )


@router.post(
    "/logout",
    dependencies=[Depends(current_principal)],
    responses={401: problem_response("no usable credential")},
)
async def logout(
    response: Response,
    settings: Settings,
    runtime: Runtime,
    actor: CurrentPrincipal,
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
        runtime: Session persistence and clock wiring.
        actor: The authenticated caller whose session may be terminated.
        session: The session the credential resolved to, or ``None`` for a
            bearer caller.

    Returns:
        The ``signed-out`` acknowledgement.
    """
    await terminate_session(actor, session, runtime.sessions, clock=runtime.clock)
    session_cookie(settings).revoke(response)
    return SignOut(status="signed-out")
