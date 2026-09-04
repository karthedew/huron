"""Admin-provisioned password users: create, reset password, disable.

Provisioning a human is a platform act - every route here requires
``user.manage`` at SYSTEM scope, held only by ``platform_owner`` (org admins
manage service accounts, not people). A password is attached to a subject
exactly once, at creation: ``POST /users`` refuses a subject some principal
already holds rather than silently handing a password to an existing - and
possibly OIDC - identity. The other two routes act on a caller-supplied
``principal_id``, so ``_existing_user`` re-validates it is in fact a user
before either ever calls ``credentials.upsert`` - the same kind guard the
database trigger backstops, checked here so a service-account id gets an
honest refusal instead of the trigger's generic "does not exist".
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated
from uuid import UUID

from asyncer import asyncify
from fastapi import APIRouter, Depends

from huron.pkg.auth import Principal, PrincipalSubjectExists, make_credential
from huron.pkg.catalog.errors import ResourceNotFound
from huron.service.api.authorization import require_system
from huron.service.api.errors import PrincipalKindMismatch, UsernameTaken
from huron.service.api.problems import problem_response
from huron.service.api.routes.v1.schema.users import (
    CreateUser,
    PasswordReset,
    SetPassword,
    UserView,
)
from huron.service.api.runtime import ApiKeys, Credentials, Principals, Sessions

if TYPE_CHECKING:
    from huron.pkg.auth import PrincipalRecord, PrincipalStore

_manage_users = require_system("user.manage")
_Actor = Annotated[Principal, Depends(_manage_users)]
router = APIRouter(prefix="/users", tags=["users"], dependencies=[Depends(_manage_users)])


async def _existing_user(principals: PrincipalStore, principal_id: UUID) -> PrincipalRecord:
    """Return the principal, provided it exists and is a user.

    The id came from the caller, so it is re-validated here before any
    credential or session is touched: a service-account id gets an honest
    refusal rather than the database trigger's generic "does not exist".

    Args:
        principals: The wired principal store.
        principal_id: The id the route was addressed with.

    Returns:
        The user's principal record.

    Raises:
        ResourceNotFound: If no principal has this id.
        PrincipalKindMismatch: If the principal is a service account rather
            than a user.
    """
    principal = await principals.get_by_id(principal_id)
    if principal is None:
        raise ResourceNotFound(f"principal does not exist: {principal_id}")
    if principal.kind != "user":
        raise PrincipalKindMismatch(f"principal is not a user: {principal_id}")
    return principal


@router.post("", status_code=201, responses={409: problem_response("username is already taken")})
async def create_user(
    body: CreateUser, principals: Principals, credentials: Credentials, actor: _Actor
) -> UserView:
    """Provision a password user.

    Requires ``user.manage`` at SYSTEM scope. The username becomes the
    user's subject and must not be held by any existing principal - a
    password user, an OIDC identity or a service account, disabled or not -
    or the request is refused with 409: a password is attached to a subject
    exactly once, at creation, never silently handed to an existing
    identity.
    \f
    Args:
        body: The username, display name and initial password.
        principals: The wired principal store.
        credentials: The wired credential store.
        actor: The administrator provisioning the user, recorded as the
            credential's author.

    Returns:
        The user as the API renders it.

    Raises:
        UsernameTaken: If a principal already holds the username as its
            subject.
    """
    try:
        principal = await principals.create_user(
            subject=body.username, display_name=body.display_name
        )
    except PrincipalSubjectExists as exc:
        raise UsernameTaken(str(exc)) from exc
    credential = await asyncify(make_credential)(
        principal.id, body.password, updated_by=actor.subject
    )
    await credentials.upsert(credential)
    return UserView.model_validate(principal)


@router.put(
    "/{principal_id}/password",
    responses={
        404: problem_response("no such user"),
        409: problem_response("principal is not a user"),
    },
)
async def set_password(
    principal_id: UUID,
    body: SetPassword,
    principals: Principals,
    credentials: Credentials,
    sessions: Sessions,
    api_keys: ApiKeys,
    actor: _Actor,
) -> PasswordReset:
    """Replace a user's password.

    Requires ``user.manage`` at SYSTEM scope. Every session and every API
    key the user holds is revoked before the acknowledgement is returned -
    a reset logs the user out everywhere, and a key is a login that would
    otherwise outlive it. An unknown principal is 404; one that is a
    service account rather than a user is refused with 409.
    \f
    Args:
        principal_id: The user whose password to replace.
        body: The new password.
        principals: The wired principal store.
        credentials: The wired credential store.
        sessions: The wired session store.
        api_keys: The wired API-key store.
        actor: The administrator resetting the password, recorded as the
            credential's author.

    Returns:
        The acknowledgement that the password was replaced and the user's
        sessions and API keys revoked.
    """
    principal = await _existing_user(principals, principal_id)
    credential = await asyncify(make_credential)(
        principal_id, body.password, updated_by=actor.subject
    )
    await credentials.upsert(credential)
    reset_at = datetime.now(UTC)
    await sessions.revoke_all_for(principal.subject, reset_at)
    await api_keys.revoke_all_for(principal.subject, reset_at)
    return PasswordReset(status="password-reset")


@router.post(
    "/{principal_id}/disable",
    responses={
        404: problem_response("no such user"),
        409: problem_response("principal is not a user"),
    },
)
async def disable_user(
    principal_id: UUID, principals: Principals, sessions: Sessions, api_keys: ApiKeys
) -> UserView:
    """Disable a user, revoke every session they hold, and revoke every API key they hold.

    Requires ``user.manage`` at SYSTEM scope. A disabled user can no longer
    log in by any method - password, OIDC or a self-issued API key - and
    the API offers no way to re-enable them. An unknown principal is 404;
    one that is a service account rather than a user is refused with 409.
    \f
    Args:
        principal_id: The user to disable.
        principals: The wired principal store.
        sessions: The wired session store.
        api_keys: The wired API-key store.

    Returns:
        The user as the API renders it, with ``disabled_at`` set.

    Raises:
        ResourceNotFound: If no principal has this id by the time the
            disable is applied.
    """
    await _existing_user(principals, principal_id)
    disabled_at = datetime.now(UTC)
    updated = await principals.disable(principal_id, disabled_at=disabled_at)
    if updated is None:
        raise ResourceNotFound(f"principal does not exist: {principal_id}")
    await sessions.revoke_all_for(updated.subject, disabled_at)
    await api_keys.revoke_all_for(updated.subject, disabled_at)
    return UserView.model_validate(updated)
