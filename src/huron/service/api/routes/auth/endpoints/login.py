"""Password login and logout - the two routes a caller reaches with no
principal yet, besides OIDC's own start/callback pair."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Request, Response

from huron.pkg.auth import AuthError, create_session, verify_password
from huron.service.api.authorization import (
    CurrentPrincipal,
    clear_session_cookie,
    get_repository,
    get_settings,
    set_session_cookie,
)
from huron.service.api.routes.auth.schema.login import PasswordLogin

router = APIRouter()


@router.post("/login")
async def password_login(
    request: Request, response: Response, body: PasswordLogin
) -> dict[str, object]:
    """Verify username and password, then start a session.

    ``verify_password`` always runs its hash comparison, against a dummy
    hash when no credential exists - so an unknown username, a disabled
    account, a service-account subject, and a wrong password all cost the
    same wall-clock time and return the same message. The lookup's result is
    only dereferenced once ``verify_password`` has already said yes.
    """
    settings = get_settings(request)
    if not settings.password_login_enabled:
        raise AuthError("password login is disabled")
    repository = get_repository(request)
    principal_row = await repository.principals.get_user_by_subject(body.username)
    credential = (
        await repository.credentials.get(principal_row.id) if principal_row is not None else None
    )
    if not verify_password(credential, body.password) or principal_row is None:
        raise AuthError("invalid username or password")
    record, token = create_session(principal_row.subject, authentication_method="password")
    await repository.sessions.add(record)
    set_session_cookie(response, settings, token)
    return {
        "subject": principal_row.subject,
        "display_name": principal_row.display_name,
        "csrf_token": record.csrf_token,
    }


@router.post("/logout")
async def logout(request: Request, response: Response, _actor: CurrentPrincipal) -> dict[str, str]:
    """Revoke the session behind this request, if any, and clear the cookie.

    Any credential may sign out - a bearer caller simply has no session to
    revoke - so ``_actor`` is required only to keep this route consistent
    with the rest of the API (an unauthenticated logout is a no-op that
    would tell an attacker nothing, but is also pointless to allow).
    """
    session = getattr(request.state, "session", None)
    if session is not None:
        await get_repository(request).sessions.revoke(session.id, datetime.now(UTC))
    clear_session_cookie(response, get_settings(request))
    return {"status": "signed-out"}
