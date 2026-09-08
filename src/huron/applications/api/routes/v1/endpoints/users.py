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

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from huron.applications.api.authorization import require_system
from huron.applications.api.dependencies import Identity
from huron.applications.api.problems import problem_response
from huron.applications.api.routes.v1.schema.users import (
    CreateUser,
    PasswordReset,
    SetPassword,
    UserView,
)
from huron.pkg.auth import Principal

_manage_users = require_system("user.manage")
_Actor = Annotated[Principal, Depends(_manage_users)]
router = APIRouter(prefix="/users", tags=["users"], dependencies=[Depends(_manage_users)])


@router.post("", status_code=201, responses={409: problem_response("username is already taken")})
async def create_user(body: CreateUser, identity: Identity, actor: _Actor) -> UserView:
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
        identity: The actor-bound identity service.
        actor: The administrator provisioning the user, recorded as the
            credential's author.

    Returns:
        The user as the API renders it.

    """
    principal = await identity.create_user(body.username, body.display_name, body.password)
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
    identity: Identity,
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
        identity: The actor-bound identity service.
        actor: The administrator resetting the password, recorded as the
            credential's author.

    Returns:
        The acknowledgement that the password was replaced and the user's
        sessions and API keys revoked.
    """
    await identity.set_password(principal_id, body.password)
    return PasswordReset(status="password-reset")


@router.post(
    "/{principal_id}/disable",
    responses={
        404: problem_response("no such user"),
        409: problem_response("principal is not a user"),
    },
)
async def disable_user(principal_id: UUID, identity: Identity) -> UserView:
    """Disable a user, revoke every session they hold, and revoke every API key they hold.

    Requires ``user.manage`` at SYSTEM scope. A disabled user can no longer
    log in by any method - password, OIDC or a self-issued API key - and
    the API offers no way to re-enable them. An unknown principal is 404;
    one that is a service account rather than a user is refused with 409.
    \f
    Args:
        principal_id: The user to disable.
        identity: The actor-bound identity service.

    Returns:
        The user as the API renders it, with ``disabled_at`` set.

    """
    return UserView.model_validate(await identity.disable_user(principal_id))
