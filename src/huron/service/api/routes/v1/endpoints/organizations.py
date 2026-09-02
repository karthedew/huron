"""Organizations: creation is platform-scope; edits are organization-scope."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from huron.service.api.authorization import require_organization, require_system
from huron.service.api.problems import problem_response
from huron.service.api.records import Organization
from huron.service.api.routes.v1.pagination import Page, PageCursor, PageLimit, paginate
from huron.service.api.routes.v1.preconditions import (
    IdempotencyHeader,
    IfMatchHeader,
    expected_version,
)
from huron.service.api.routes.v1.schema.organizations import (
    CreateOrganization,
    OrganizationView,
    PatchOrganization,
)
from huron.service.api.runtime import Repository

router = APIRouter(prefix="/organizations", tags=["organizations"])


def _key(item: Organization) -> tuple[str, str]:
    return (item.slug, str(item.id))


@router.post(
    "",
    status_code=201,
    dependencies=[Depends(require_system("organization.create"))],
    responses={409: problem_response("organization slug already exists")},
)
def create_organization(
    body: CreateOrganization,
    idempotency_key: IdempotencyHeader,
    repository: Repository,
) -> OrganizationView:
    """Persist one organization; the durable write runs in the threadpool."""
    return OrganizationView.model_validate(
        repository.create_organization(
            slug=body.slug,
            title=body.title,
            description=body.description,
            idempotency_key=idempotency_key,
        )
    )


@router.get("", responses={400: problem_response("cursor is not a valid continuation")})
async def list_organizations(
    repository: Repository, limit: PageLimit = 50, after: PageCursor = None
) -> Page[OrganizationView]:
    return paginate(
        repository.list_organizations(), OrganizationView, key=_key, limit=limit, after=after
    )


@router.get("/{organization_id}", responses={404: problem_response("no such organization")})
async def get_organization(organization_id: UUID, repository: Repository) -> OrganizationView:
    return OrganizationView.model_validate(repository.get_organization(organization_id))


@router.patch(
    "/{organization_id}",
    dependencies=[Depends(require_organization("organization.update"))],
    responses={
        404: problem_response("no such organization"),
        409: problem_response("the slug on an existing organization cannot change"),
        412: problem_response("If-Match does not match the current version"),
    },
)
def patch_organization(
    organization_id: UUID,
    body: PatchOrganization,
    if_match: IfMatchHeader,
    repository: Repository,
) -> OrganizationView:
    """Persist the patch; the durable rewrite runs in the threadpool."""
    return OrganizationView.model_validate(
        repository.patch_organization(
            organization_id,
            expected_version=expected_version(if_match),
            slug=body.slug,
            title=body.title,
            description=body.description,
        )
    )
