"""Policies and their attachment to organizations, projects, and datasets."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from huron.pkg.auth import Principal
from huron.pkg.rbac import ScopeType
from huron.service.api.authorization import (
    CurrentPrincipal,
    get_repository,
    require_dataset,
    require_organization,
    require_project,
)
from huron.service.api.routes.v1.common import jsonable
from huron.service.api.routes.v1.schema.policies import AttachPolicy, CreatePolicy

router = APIRouter()


@router.post("/policies", status_code=201)
async def create_policy(
    request: Request, body: CreatePolicy, actor: CurrentPrincipal
) -> dict[str, object]:
    """Creating a policy grants nothing - attachment is the guarded act."""
    record = await get_repository(request).create_policy(
        policy_type=body.policy_type,
        name=body.name,
        spec=body.spec,
        created_by=actor.subject,
    )
    return jsonable(record)


@router.get("/policies")
async def list_policies(request: Request, _actor: CurrentPrincipal) -> dict[str, object]:
    items = await get_repository(request).list_policies()
    return {"items": [jsonable(item) for item in items]}


@router.post("/organizations/{organization_id}/policy-attachments", status_code=201)
async def attach_to_organization(
    request: Request,
    organization_id: UUID,
    body: AttachPolicy,
    actor: Annotated[Principal, Depends(require_organization("organization.policy_attach"))],
) -> dict[str, object]:
    attachment = await get_repository(request).attach_policy(
        UUID(body.policy_id),
        scope_type=ScopeType.ORGANIZATION,
        scope_id=organization_id,
        attached_by=actor.subject,
    )
    return jsonable(attachment)


@router.post("/projects/{project_id}/policy-attachments", status_code=201)
async def attach_to_project(
    request: Request,
    project_id: UUID,
    body: AttachPolicy,
    actor: Annotated[Principal, Depends(require_project("project.policy_attach"))],
) -> dict[str, object]:
    attachment = await get_repository(request).attach_policy(
        UUID(body.policy_id),
        scope_type=ScopeType.PROJECT,
        scope_id=project_id,
        attached_by=actor.subject,
    )
    return jsonable(attachment)


@router.post("/datasets/{dataset_id}/policy-attachments", status_code=201)
async def attach_to_dataset(
    request: Request,
    dataset_id: UUID,
    body: AttachPolicy,
    actor: Annotated[Principal, Depends(require_dataset("dataset.policy_attach"))],
) -> dict[str, object]:
    attachment = await get_repository(request).attach_policy(
        UUID(body.policy_id),
        scope_type=ScopeType.DATASET,
        scope_id=dataset_id,
        attached_by=actor.subject,
    )
    return jsonable(attachment)
