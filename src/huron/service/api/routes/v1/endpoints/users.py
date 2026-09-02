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
    principal = await repository.principals.get_by_id(principal_id)
    if principal is None:
        raise ResourceNotFound(f"principal does not exist: {principal_id}")
    if principal.kind != "user":
        raise PrincipalKindMismatch(f"principal is not a user: {principal_id}")
    return principal


@router.post("", status_code=201, responses={409: problem_response("username is already taken")})
async def create_user(body: CreateUser, repository: Repository, actor: _Actor) -> UserView:
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
    await _existing_user(repository, principal_id)
    updated = await repository.principals.disable(principal_id, disabled_at=datetime.now(UTC))
    if updated is None:
        raise ResourceNotFound(f"principal does not exist: {principal_id}")
    await repository.sessions.revoke_all_for(updated.subject, datetime.now(UTC))
    return UserView.model_validate(updated)
