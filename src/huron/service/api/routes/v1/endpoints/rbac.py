"""Roles, role bindings, and service accounts.

Bindings are granted where they live: a project binding through the project
route by someone holding ``rbac.binding_manage`` there, and so on up to
 SYSTEM. Service accounts are roleless identities created only by holders of
 ``service_account.manage`` on the owning organization.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from huron.pkg.auth import Principal, create_api_key
from huron.pkg.rbac import Scope, ScopeType
from huron.pkg.rbac.roles import ROLES
from huron.service.api.authorization import (
    CurrentPrincipal,
    Forbidden,
    check,
    dataset_scope,
    get_repository,
    organization_scope,
    project_scope,
    require_dataset,
    require_organization,
    require_project,
    require_system,
)
from huron.service.api.routes.v1.common import jsonable
from huron.service.api.routes.v1.schema.auth import CreateApiKey
from huron.service.api.routes.v1.schema.rbac import CreateRoleBinding, CreateServiceAccount

router = APIRouter()


@router.get("/roles")
async def list_roles(request: Request) -> dict[str, object]:
    """The role catalog: what each role can do and who may hold it."""
    del request
    return {
        "items": [
            {
                "code": role.code,
                "title": role.title,
                "description": role.description,
                "capabilities": sorted(role.capabilities),
                "layer_grants": [
                    {
                        "capability": grant.capability,
                        "layers": sorted(grant.layers) if grant.layers is not None else None,
                    }
                    for grant in role.layer_grants
                ],
                "bindable_scopes": sorted(scope.value for scope in role.bindable_scopes),
                "allowed_principal_kinds": sorted(role.allowed_principal_kinds),
            }
            for role in ROLES.values()
        ]
    }


def _expires(body: CreateRoleBinding) -> datetime | None:
    if body.expires_in_days is None:
        return None
    return datetime.now(UTC) + timedelta(days=body.expires_in_days)


@router.post("/bindings", status_code=201)
async def create_system_binding(
    request: Request,
    body: CreateRoleBinding,
    actor: Annotated[Principal, Depends(require_system("rbac.binding_manage"))],
) -> dict[str, object]:
    record = await get_repository(request).grant_role(
        principal=body.principal,
        role_code=body.role,
        scope_type=ScopeType.SYSTEM,
        scope_id=None,
        created_by=actor.subject,
        expires_at=_expires(body),
    )
    return jsonable(record)


@router.post("/organizations/{organization_id}/bindings", status_code=201)
async def create_organization_binding(
    request: Request,
    organization_id: UUID,
    body: CreateRoleBinding,
    actor: Annotated[Principal, Depends(require_organization("rbac.binding_manage"))],
) -> dict[str, object]:
    record = await get_repository(request).grant_role(
        principal=body.principal,
        role_code=body.role,
        scope_type=ScopeType.ORGANIZATION,
        scope_id=organization_id,
        created_by=actor.subject,
        expires_at=_expires(body),
    )
    return jsonable(record)


@router.post("/projects/{project_id}/bindings", status_code=201)
async def create_project_binding(
    request: Request,
    project_id: UUID,
    body: CreateRoleBinding,
    actor: Annotated[Principal, Depends(require_project("rbac.binding_manage"))],
) -> dict[str, object]:
    record = await get_repository(request).grant_role(
        principal=body.principal,
        role_code=body.role,
        scope_type=ScopeType.PROJECT,
        scope_id=project_id,
        created_by=actor.subject,
        expires_at=_expires(body),
    )
    return jsonable(record)


@router.post("/datasets/{dataset_id}/bindings", status_code=201)
async def create_dataset_binding(
    request: Request,
    dataset_id: UUID,
    body: CreateRoleBinding,
    actor: Annotated[Principal, Depends(require_dataset("rbac.binding_manage"))],
) -> dict[str, object]:
    record = await get_repository(request).grant_role(
        principal=body.principal,
        role_code=body.role,
        scope_type=ScopeType.DATASET,
        scope_id=dataset_id,
        created_by=actor.subject,
        expires_at=_expires(body),
    )
    return jsonable(record)


@router.get("/organizations/{organization_id}/bindings")
async def list_organization_bindings(
    request: Request,
    organization_id: UUID,
    _actor: Annotated[Principal, Depends(require_organization("rbac.binding_manage"))],
) -> dict[str, object]:
    records = await get_repository(request).bindings_at(ScopeType.ORGANIZATION, organization_id)
    return {"items": [jsonable(item) for item in records]}


@router.get("/projects/{project_id}/bindings")
async def list_project_bindings(
    request: Request,
    project_id: UUID,
    _actor: Annotated[Principal, Depends(require_project("rbac.binding_manage"))],
) -> dict[str, object]:
    records = await get_repository(request).bindings_at(ScopeType.PROJECT, project_id)
    return {"items": [jsonable(item) for item in records]}


@router.delete("/bindings/{binding_id}", status_code=204)
async def revoke_binding(request: Request, binding_id: UUID, actor: CurrentPrincipal) -> None:
    """Revoking requires ``rbac.binding_manage`` at the binding's own scope."""
    repository = get_repository(request)
    record = await repository.get_role_binding(binding_id)
    scope_type = ScopeType(record.scope_type)
    if scope_type is ScopeType.SYSTEM:
        scope = Scope.system()
    elif scope_type is ScopeType.ORGANIZATION:
        scope = organization_scope(repository, record.scope_id)  # type: ignore[arg-type]
    elif scope_type is ScopeType.PROJECT:
        scope = project_scope(repository, record.scope_id)  # type: ignore[arg-type]
    else:
        scope = dataset_scope(repository, record.scope_id)  # type: ignore[arg-type]
    await check(request, actor, "rbac.binding_manage", scope)
    await repository.revoke_role(binding_id)


@router.post("/organizations/{organization_id}/service-accounts", status_code=201)
async def create_service_account(
    request: Request,
    organization_id: UUID,
    body: CreateServiceAccount,
    actor: Annotated[Principal, Depends(require_organization("service_account.manage"))],
) -> dict[str, object]:
    record = await get_repository(request).create_service_account(
        organization_id, name=body.name, created_by=actor.subject
    )
    return jsonable(record)


@router.get("/organizations/{organization_id}/service-accounts")
async def list_service_accounts(
    request: Request,
    organization_id: UUID,
    _actor: Annotated[Principal, Depends(require_organization("service_account.manage"))],
) -> dict[str, object]:
    items = await get_repository(request).list_service_accounts(organization_id)
    return {"items": [jsonable(item) for item in items]}


@router.post(
    "/organizations/{organization_id}/service-accounts/{principal_id}/api-keys",
    status_code=201,
)
async def issue_service_account_key(
    request: Request,
    organization_id: UUID,
    principal_id: UUID,
    body: CreateApiKey,
    _actor: Annotated[Principal, Depends(require_organization("service_account.manage"))],
) -> dict[str, object]:
    """Mint a key that authenticates AS the service account."""
    repository = get_repository(request)
    account = await repository.get_service_account(principal_id)
    if account.organization_id != organization_id:
        raise Forbidden("service account belongs to a different organization")
    if account.disabled_at is not None:
        raise Forbidden("service account is disabled")
    record, token = create_api_key(
        account.subject,
        name=body.name,
        scopes=frozenset(body.scopes),
        ttl=timedelta(days=body.expires_in_days),
        owner_kind="service_account",
    )
    await repository.api_keys.add(record)
    return {
        "id": record.key_id,
        "name": record.name,
        "subject": account.subject,
        "secret": token,
        "expires_at": record.expires_at,
    }


@router.post(
    "/organizations/{organization_id}/service-accounts/{principal_id}/disable",
)
async def disable_service_account(
    request: Request,
    organization_id: UUID,
    principal_id: UUID,
    _actor: Annotated[Principal, Depends(require_organization("service_account.manage"))],
) -> dict[str, object]:
    repository = get_repository(request)
    account = await repository.get_service_account(principal_id)
    if account.organization_id != organization_id:
        raise Forbidden("service account belongs to a different organization")
    disabled_at = datetime.now(UTC)
    account = await repository.disable_service_account(principal_id, disabled_at=disabled_at)
    await repository.api_keys.revoke_all_for(account.subject, disabled_at)
    return jsonable(account)
