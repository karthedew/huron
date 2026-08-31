"""Projects: created by organization admins, edited by project admins."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from huron.pkg.auth import Principal
from huron.service.api.authorization import (
    CurrentPrincipal,
    get_repository,
    require_organization,
    require_project,
)
from huron.service.api.routes.v1.common import (
    IdempotencyHeader,
    IfMatchHeader,
    expected_version,
    jsonable,
    page,
)
from huron.service.api.routes.v1.schema.projects import CreateProject, PatchProject

router = APIRouter()


@router.post("/organizations/{organization_id}/projects", status_code=201)
async def create_project(
    request: Request,
    organization_id: UUID,
    body: CreateProject,
    idempotency_key: IdempotencyHeader,
    _actor: Annotated[Principal, Depends(require_organization("project.create"))],
) -> dict[str, object]:
    return jsonable(
        get_repository(request).create_project(
            organization_id,
            slug=body.slug,
            title=body.title,
            description=body.description,
            data_classification=body.data_classification,
            idempotency_key=idempotency_key,
        )
    )


@router.get("/organizations/{organization_id}/projects")
async def list_projects(
    request: Request, organization_id: UUID, _actor: CurrentPrincipal, limit: int = 50
) -> dict[str, object]:
    repository = get_repository(request)
    repository.get_organization(organization_id)
    items = [
        item for item in repository.projects.values() if item.organization_id == organization_id
    ]
    return page(sorted(items, key=lambda item: (item.slug, item.id)), limit)


@router.get("/projects/{project_id}")
async def get_project(
    request: Request, project_id: UUID, _actor: CurrentPrincipal
) -> dict[str, object]:
    return jsonable(get_repository(request).get_project(project_id))


@router.patch("/projects/{project_id}")
async def patch_project(
    request: Request,
    project_id: UUID,
    body: PatchProject,
    if_match: IfMatchHeader,
    _actor: Annotated[Principal, Depends(require_project("project.update"))],
) -> dict[str, object]:
    return jsonable(
        get_repository(request).patch_project(
            project_id,
            expected_version=expected_version(if_match),
            slug=body.slug,
            title=body.title,
            description=body.description,
        )
    )
