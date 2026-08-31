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

from fastapi import APIRouter, Depends, Request

from huron.pkg.auth import Principal, PrincipalSubjectExists, make_credential
from huron.pkg.catalog.errors import DomainError
from huron.service.api.authorization import get_repository, require_system
from huron.service.api.repository import ResourceNotFound
from huron.service.api.routes.v1.common import jsonable
from huron.service.api.routes.v1.schema.users import CreateUser, SetPassword

if TYPE_CHECKING:
    from huron.pkg.auth import PrincipalRecord
    from huron.service.api.repository import HierarchyRepository

router = APIRouter()

_Actor = Annotated[Principal, Depends(require_system("user.manage"))]


async def _existing_user(repository: HierarchyRepository, principal_id: UUID) -> PrincipalRecord:
    principal = await repository.principals.get_by_id(principal_id)
    if principal is None:
        raise ResourceNotFound(f"principal does not exist: {principal_id}")
    if principal.kind != "user":
        raise DomainError(f"principal is not a user: {principal_id}")
    return principal


@router.post("/users", status_code=201)
async def create_user(request: Request, body: CreateUser, actor: _Actor) -> dict[str, object]:
    repository = get_repository(request)
    try:
        principal = await repository.principals.create_user(
            subject=body.username, display_name=body.display_name
        )
    except PrincipalSubjectExists as exc:
        raise DomainError(str(exc)) from exc
    credential = make_credential(principal.id, body.password, updated_by=actor.subject)
    await repository.credentials.upsert(credential)
    return jsonable(principal)


@router.put("/users/{principal_id}/password")
async def set_password(
    request: Request, principal_id: UUID, body: SetPassword, actor: _Actor
) -> dict[str, str]:
    repository = get_repository(request)
    principal = await _existing_user(repository, principal_id)
    credential = make_credential(principal_id, body.password, updated_by=actor.subject)
    await repository.credentials.upsert(credential)
    await repository.sessions.revoke_all_for(principal.subject, datetime.now(UTC))
    return {"status": "password-reset"}


@router.post("/users/{principal_id}/disable")
async def disable_user(request: Request, principal_id: UUID, _actor: _Actor) -> dict[str, object]:
    repository = get_repository(request)
    await _existing_user(repository, principal_id)
    updated = await repository.principals.disable(principal_id, disabled_at=datetime.now(UTC))
    if updated is None:
        raise ResourceNotFound(f"principal does not exist: {principal_id}")
    await repository.sessions.revoke_all_for(updated.subject, datetime.now(UTC))
    return jsonable(updated)
