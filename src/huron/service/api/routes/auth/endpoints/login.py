"""Password login and logout - the two routes a caller reaches with no
principal yet, besides OIDC's own start/callback pair."""

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

    ``verify_password`` always runs its hash comparison, against a dummy
    hash when no credential exists - so an unknown username, a disabled
    account, a service-account subject, and a wrong password all cost the
    same wall-clock time and return the same message. The lookup's result is
    only dereferenced once ``verify_password`` has already said yes.
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

    Any credential may sign out - a bearer caller simply has no session to
    revoke - so a credential is required only to keep this route consistent
    with the rest of the API (an unauthenticated logout is a no-op that
    would tell an attacker nothing, but is also pointless to allow).
    """
    if session is not None:
        await repository.sessions.revoke(session.id, datetime.now(UTC))
    session_cookie(settings).revoke(response)
    return SignOut(status="signed-out")
