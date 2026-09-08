"""Password login, and the logout that ends the session it started.

Login is the one route, besides OIDC's own start/callback pair, that a
caller reaches with no principal yet: it is where a password becomes a
session cookie. Logout is its counterpart and, like every other route,
requires a credential.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import UTC, datetime

from anyio import CapacityLimiter
from asyncer import asyncify
from fastapi import APIRouter, Depends, Response

from huron.applications.api.authorization import CurrentSession, current_principal, session_cookie
from huron.applications.api.problems import problem_response
from huron.applications.api.routes.auth.schema.login import LoginResult, PasswordLogin, SignOut
from huron.applications.api.runtime import Credentials, Principals, Sessions, Settings
from huron.pkg.auth import (
    AuthError,
    CredentialRecord,
    create_session,
    hash_password,
    needs_rehash,
    verify_password,
)

router = APIRouter()
logger = logging.getLogger(__name__)

# Argon2id hashing is CPU- and memory-amplifying and this route is
# unauthenticated, so it gets its own queue instead of sharing the 40-token
# default threadpool limiter with every other blocking call in the service -
# bounding the worst case to 4 concurrent hashes rather than a service-wide
# memory spike.
_password_hash_limiter = CapacityLimiter(4)


async def _rehash_credential(
    credentials: Credentials, credential: CredentialRecord, password: str, *, subject: str
) -> None:
    """Replace an outdated stored hash with a fresh one of the same password, best-effort.

    Called only once :func:`verify_password` has already confirmed
    ``password`` against the outdated hash, so failing to store the
    replacement costs nothing but the next login's chance to upgrade it -
    it is logged rather than raised, on the same worker pool the
    verification itself ran on. Only ``password_hash`` changes:
    ``updated_at`` and ``updated_by`` are carried over unchanged from
    ``credential``, since logging in is never the administrative act that
    set the password - a rehash must not reassign who is credited with
    setting it, or when.

    Args:
        credentials: The wired credential store.
        credential: The outdated credential a fresh hash replaces.
        password: The plaintext already verified against the old hash.
        subject: The principal's own subject, used only to identify the
            credential in the failure log.
    """
    try:
        refreshed = replace(
            credential,
            password_hash=await asyncify(hash_password, limiter=_password_hash_limiter)(password),
        )
        await credentials.upsert(refreshed)
    except Exception:
        logger.warning("failed to rehash the password credential for %s", subject, exc_info=True)


@router.post(
    "/login",
    responses={401: problem_response("password login is disabled, or the credential is wrong")},
)
async def password_login(
    response: Response,
    body: PasswordLogin,
    settings: Settings,
    principals: Principals,
    credentials: Credentials,
    sessions: Sessions,
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
        principals: The wired principal store.
        credentials: The wired credential store.
        sessions: The wired session store.

    Returns:
        The subject, display name and CSRF token of the session just started.

    Raises:
        AuthError: If password login is disabled, or the username and
            password do not name an enabled user with that password.
    """
    if not settings.password_login_enabled:
        raise AuthError("password login is disabled")
    principal_row = await principals.get_user_by_subject(body.username)
    credential = await credentials.get(principal_row.id) if principal_row is not None else None
    verified = await asyncify(verify_password, limiter=_password_hash_limiter)(
        credential, body.password
    )
    # verify_password only returns True once it has compared against a
    # stored hash, so a verified login always has one; the redundant
    # credential check here is what lets the type checker see that too.
    if not verified or principal_row is None or credential is None:
        raise AuthError("invalid username or password")
    if needs_rehash(credential):
        await _rehash_credential(
            credentials, credential, body.password, subject=principal_row.subject
        )
    record, token = create_session(principal_row.subject, authentication_method="password")
    await sessions.add(record)
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
    sessions: Sessions,
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
        sessions: The wired session store.
        session: The session the credential resolved to, or ``None`` for a
            bearer caller.

    Returns:
        The ``signed-out`` acknowledgement.
    """
    if session is not None:
        await sessions.revoke(session.id, datetime.now(UTC))
    session_cookie(settings).revoke(response)
    return SignOut(status="signed-out")
