"""Organizations: creation is platform-scope; edits are organization-scope."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from huron.pkg.auth import Principal
from huron.service.api.authorization import (
    CurrentPrincipal,
    get_repository,
    require_organization,
    require_system,
)
from huron.service.api.routes.v1.common import (
    IdempotencyHeader,
    IfMatchHeader,
    expected_version,
    jsonable,
    page,
)
from huron.service.api.routes.v1.schema.organizations import CreateOrganization, PatchOrganization

router = APIRouter()


@router.post("/organizations", status_code=201)
async def create_organization(
    request: Request,
    body: CreateOrganization,
    idempotency_key: IdempotencyHeader,
    _actor: Annotated[Principal, Depends(require_system("organization.create"))],
) -> dict[str, object]:
    return jsonable(
        get_repository(request).create_organization(
            slug=body.slug,
            title=body.title,
            description=body.description,
            idempotency_key=idempotency_key,
        )
    )


@router.get("/organizations")
async def list_organizations(
    request: Request, _actor: CurrentPrincipal, limit: int = 50
) -> dict[str, object]:
    items = sorted(
        get_repository(request).organizations.values(), key=lambda item: (item.slug, item.id)
    )
    return page(items, limit)


@router.get("/organizations/{organization_id}")
async def get_organization(
    request: Request, organization_id: UUID, _actor: CurrentPrincipal
) -> dict[str, object]:
    return jsonable(get_repository(request).get_organization(organization_id))


@router.patch("/organizations/{organization_id}")
async def patch_organization(
    request: Request,
    organization_id: UUID,
    body: PatchOrganization,
    if_match: IfMatchHeader,
    _actor: Annotated[Principal, Depends(require_organization("organization.update"))],
) -> dict[str, object]:
    return jsonable(
        get_repository(request).patch_organization(
            organization_id,
            expected_version=expected_version(if_match),
            slug=body.slug,
            title=body.title,
            description=body.description,
        )
    )
