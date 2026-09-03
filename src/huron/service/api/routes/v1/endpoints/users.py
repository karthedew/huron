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
from huron.service.api.runtime import Repository

if TYPE_CHECKING:
    from huron.pkg.auth import PrincipalRecord
    from huron.service.api.repository import HierarchyRepository

_manage_users = require_system("user.manage")
_Actor = Annotated[Principal, Depends(_manage_users)]
router = APIRouter(prefix="/users", tags=["users"], dependencies=[Depends(_manage_users)])


async def _existing_user(repository: HierarchyRepository, principal_id: UUID) -> PrincipalRecord:
    """Return the principal, provided it exists and is a user.

    The id came from the caller, so it is re-validated here before any
    credential or session is touched: a service-account id gets an honest
    refusal rather than the database trigger's generic "does not exist".

    Args:
        repository: The wired hierarchy repository.
        principal_id: The id the route was addressed with.

    Returns:
        The user's principal record.

    Raises:
        ResourceNotFound: If no principal has this id.
        PrincipalKindMismatch: If the principal is a service account rather
            than a user.
    """
    principal = await repository.principals.get_by_id(principal_id)
    if principal is None:
        raise ResourceNotFound(f"principal does not exist: {principal_id}")
    if principal.kind != "user":
        raise PrincipalKindMismatch(f"principal is not a user: {principal_id}")
    return principal


@router.post("", status_code=201, responses={409: problem_response("username is already taken")})
async def create_user(body: CreateUser, repository: Repository, actor: _Actor) -> UserView:
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
        repository: The wired hierarchy repository.
        actor: The administrator provisioning the user, recorded as the
            credential's author.

    Returns:
        The user as the API renders it.

    Raises:
        UsernameTaken: If a principal already holds the username as its
            subject.
    """
    try:
        principal = await repository.principals.create_user(
            subject=body.username, display_name=body.display_name
        )
    except PrincipalSubjectExists as exc:
        raise UsernameTaken(str(exc)) from exc
    credential = await asyncify(make_credential)(
        principal.id, body.password, updated_by=actor.subject
    )
    await repository.credentials.upsert(credential)
    return UserView.model_validate(principal)


@router.put(
    "/{principal_id}/password",
    responses={
        404: problem_response("no such user"),
        409: problem_response("principal is not a user"),
    },
)
async def set_password(
    principal_id: UUID, body: SetPassword, repository: Repository, actor: _Actor
) -> PasswordReset:
    """Replace a user's password.

    Requires ``user.manage`` at SYSTEM scope. Every session the user holds
    is revoked before the acknowledgement is returned. An unknown principal
    is 404; one that is a service account rather than a user is refused
    with 409.
    \f
    Args:
        principal_id: The user whose password to replace.
        body: The new password.
        repository: The wired hierarchy repository.
        actor: The administrator resetting the password, recorded as the
            credential's author.

    Returns:
        The acknowledgement that the password was replaced and the user's
        sessions revoked.
    """
    principal = await _existing_user(repository, principal_id)
    credential = await asyncify(make_credential)(
        principal_id, body.password, updated_by=actor.subject
    )
    await repository.credentials.upsert(credential)
    await repository.sessions.revoke_all_for(principal.subject, datetime.now(UTC))
    return PasswordReset(status="password-reset")


@router.post(
    "/{principal_id}/disable",
    responses={
        404: problem_response("no such user"),
        409: problem_response("principal is not a user"),
    },
)
async def disable_user(principal_id: UUID, repository: Repository) -> UserView:
    """Disable a user and revoke every session they hold.

    Requires ``user.manage`` at SYSTEM scope. A disabled user can no longer
    log in with a password, and the API offers no way to re-enable them. An
    unknown principal is 404; one that is a service account rather than a
    user is refused with 409.
    \f
    Args:
        principal_id: The user to disable.
        repository: The wired hierarchy repository.

    Returns:
        The user as the API renders it, with ``disabled_at`` set.

    Raises:
        ResourceNotFound: If no principal has this id by the time the
            disable is applied.
    """
    await _existing_user(repository, principal_id)
    updated = await repository.principals.disable(principal_id, disabled_at=datetime.now(UTC))
    if updated is None:
        raise ResourceNotFound(f"principal does not exist: {principal_id}")
    await repository.sessions.revoke_all_for(updated.subject, datetime.now(UTC))
    return UserView.model_validate(updated)
