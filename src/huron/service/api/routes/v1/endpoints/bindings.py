"""Role bindings: grants of a role to a principal at a scope.

Bindings are granted, listed and revoked where they live: a project binding
through the project route by someone holding ``rbac.binding_manage`` there,
and so on up to SYSTEM. Every operation under a root therefore shares one
guard, declared once on the router; a route body never re-derives the scope
a binding belongs to, it only asks whether a named binding is a member of
the collection its root already proved the caller may administer.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from huron.pkg.auth import Principal
from huron.pkg.catalog.errors import ResourceNotFound
from huron.pkg.rbac import ScopeType
from huron.service.api.authorization import (
    require_dataset,
    require_organization,
    require_project,
    require_system,
)
from huron.service.api.problems import problem_response
from huron.service.api.records import RoleBindingRecord
from huron.service.api.routes.v1.pagination import Page, PageCursor, PageLimit, paginate
from huron.service.api.routes.v1.schema.bindings import CreateRoleBinding, RoleBindingView
from huron.service.api.runtime import Repository

_manage_system_bindings = require_system("rbac.binding_manage")
_manage_organization_bindings = require_organization("rbac.binding_manage")
_manage_project_bindings = require_project("rbac.binding_manage")
_manage_dataset_bindings = require_dataset("rbac.binding_manage")

router = APIRouter(
    prefix="/bindings", tags=["role-bindings"], dependencies=[Depends(_manage_system_bindings)]
)
organization_bindings = APIRouter(
    prefix="/organizations/{organization_id}/bindings",
    tags=["role-bindings"],
    dependencies=[Depends(_manage_organization_bindings)],
)
project_bindings = APIRouter(
    prefix="/projects/{project_id}/bindings",
    tags=["role-bindings"],
    dependencies=[Depends(_manage_project_bindings)],
)
dataset_bindings = APIRouter(
    prefix="/datasets/{dataset_id}/bindings",
    tags=["role-bindings"],
    dependencies=[Depends(_manage_dataset_bindings)],
)


def _expires(body: CreateRoleBinding) -> datetime | None:
    if body.expires_in_days is None:
        return None
    return datetime.now(UTC) + timedelta(days=body.expires_in_days)


def _key(item: RoleBindingRecord) -> tuple[str, str]:
    return (item.principal, item.role_code)


def _member(record: RoleBindingRecord, scope_type: ScopeType, scope_id: UUID | None) -> None:
    """Refuse a binding that is not in this collection, as if it did not exist.

    The guard proved the caller may administer bindings *here*; it proved
    nothing about a binding granted somewhere else, and naming one from the
    wrong root must not confirm that it exists.
    """
    if record.scope_type != scope_type.value or record.scope_id != scope_id:
        raise ResourceNotFound(f"role binding does not exist: {record.id}")


@router.get("", responses={400: problem_response("cursor is not a valid continuation")})
async def list_system_bindings(
    repository: Repository, limit: PageLimit = 50, after: PageCursor = None
) -> Page[RoleBindingView]:
    records = await repository.bindings_at(ScopeType.SYSTEM, None)
    return paginate(sorted(records, key=_key), RoleBindingView, key=_key, limit=limit, after=after)


@router.post(
    "", status_code=201, responses={409: problem_response("an identical role binding exists")}
)
async def create_system_binding(
    body: CreateRoleBinding,
    repository: Repository,
    actor: Annotated[Principal, Depends(_manage_system_bindings)],
) -> RoleBindingView:
    return RoleBindingView.model_validate(
        await repository.grant_role(
            principal=body.principal,
            role_code=body.role,
            scope_type=ScopeType.SYSTEM,
            scope_id=None,
            created_by=actor.subject,
            expires_at=_expires(body),
        )
    )


@organization_bindings.post(
    "",
    status_code=201,
    responses={
        404: problem_response("no such organization"),
        409: problem_response("an identical role binding exists"),
    },
)
async def create_organization_binding(
    organization_id: UUID,
    body: CreateRoleBinding,
    repository: Repository,
    actor: Annotated[Principal, Depends(_manage_organization_bindings)],
) -> RoleBindingView:
    return RoleBindingView.model_validate(
        await repository.grant_role(
            principal=body.principal,
            role_code=body.role,
            scope_type=ScopeType.ORGANIZATION,
            scope_id=organization_id,
            created_by=actor.subject,
            expires_at=_expires(body),
        )
    )


@project_bindings.post(
    "",
    status_code=201,
    responses={
        404: problem_response("no such project"),
        409: problem_response("an identical role binding exists"),
    },
)
async def create_project_binding(
    project_id: UUID,
    body: CreateRoleBinding,
    repository: Repository,
    actor: Annotated[Principal, Depends(_manage_project_bindings)],
) -> RoleBindingView:
    return RoleBindingView.model_validate(
        await repository.grant_role(
            principal=body.principal,
            role_code=body.role,
            scope_type=ScopeType.PROJECT,
            scope_id=project_id,
            created_by=actor.subject,
            expires_at=_expires(body),
        )
    )


@dataset_bindings.post(
    "",
    status_code=201,
    responses={
        404: problem_response("no such dataset"),
        409: problem_response("an identical role binding exists"),
    },
)
async def create_dataset_binding(
    dataset_id: UUID,
    body: CreateRoleBinding,
    repository: Repository,
    actor: Annotated[Principal, Depends(_manage_dataset_bindings)],
) -> RoleBindingView:
    return RoleBindingView.model_validate(
        await repository.grant_role(
            principal=body.principal,
            role_code=body.role,
            scope_type=ScopeType.DATASET,
            scope_id=dataset_id,
            created_by=actor.subject,
            expires_at=_expires(body),
        )
    )


@organization_bindings.get(
    "",
    responses={
        404: problem_response("no such organization"),
        400: problem_response("cursor is not a valid continuation"),
    },
)
async def list_organization_bindings(
    organization_id: UUID, repository: Repository, limit: PageLimit = 50, after: PageCursor = None
) -> Page[RoleBindingView]:
    records = await repository.bindings_at(ScopeType.ORGANIZATION, organization_id)
    return paginate(sorted(records, key=_key), RoleBindingView, key=_key, limit=limit, after=after)


@project_bindings.get(
    "",
    responses={
        404: problem_response("no such project"),
        400: problem_response("cursor is not a valid continuation"),
    },
)
async def list_project_bindings(
    project_id: UUID, repository: Repository, limit: PageLimit = 50, after: PageCursor = None
) -> Page[RoleBindingView]:
    records = await repository.bindings_at(ScopeType.PROJECT, project_id)
    return paginate(sorted(records, key=_key), RoleBindingView, key=_key, limit=limit, after=after)


@dataset_bindings.get(
    "",
    responses={
        404: problem_response("no such dataset"),
        400: problem_response("cursor is not a valid continuation"),
    },
)
async def list_dataset_bindings(
    dataset_id: UUID, repository: Repository, limit: PageLimit = 50, after: PageCursor = None
) -> Page[RoleBindingView]:
    records = await repository.bindings_at(ScopeType.DATASET, dataset_id)
    return paginate(sorted(records, key=_key), RoleBindingView, key=_key, limit=limit, after=after)


@router.delete(
    "/{binding_id}", status_code=204, responses={404: problem_response("no such role binding")}
)
async def revoke_system_binding(repository: Repository, binding_id: UUID) -> None:
    _member(await repository.get_role_binding(binding_id), ScopeType.SYSTEM, None)
    await repository.revoke_role(binding_id)


@organization_bindings.delete(
    "/{binding_id}", status_code=204, responses={404: problem_response("no such role binding")}
)
async def revoke_organization_binding(
    repository: Repository, organization_id: UUID, binding_id: UUID
) -> None:
    record = await repository.get_role_binding(binding_id)
    _member(record, ScopeType.ORGANIZATION, organization_id)
    await repository.revoke_role(binding_id)


@project_bindings.delete(
    "/{binding_id}", status_code=204, responses={404: problem_response("no such role binding")}
)
async def revoke_project_binding(
    repository: Repository, project_id: UUID, binding_id: UUID
) -> None:
    record = await repository.get_role_binding(binding_id)
    _member(record, ScopeType.PROJECT, project_id)
    await repository.revoke_role(binding_id)


@dataset_bindings.delete(
    "/{binding_id}", status_code=204, responses={404: problem_response("no such role binding")}
)
async def revoke_dataset_binding(
    repository: Repository, dataset_id: UUID, binding_id: UUID
) -> None:
    record = await repository.get_role_binding(binding_id)
    _member(record, ScopeType.DATASET, dataset_id)
    await repository.revoke_role(binding_id)
