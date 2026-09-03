"""Organizations: creation is platform-scope; edits are organization-scope.

Creating an organization needs ``organization.create`` at SYSTEM scope,
editing one needs ``organization.update`` on that organization, and reading
needs only a credential. Slugs are chosen once, at creation, and never change.
"""

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
    """Create an organization.

    Requires ``organization.create`` at SYSTEM scope. The slug must be unique
    across the platform and can never change afterwards; a duplicate is
    refused with 409. Replaying the same ``Idempotency-Key`` with the same
    request returns the original organization instead of a 409; reusing the
    key for a different request is refused with 409.
    \f
    The durable write is blocking, so the operation runs in the threadpool
    rather than on the event loop.

    Args:
        body: The slug, title and description to store.
        idempotency_key: The caller's ``Idempotency-Key`` header.
        repository: The wired hierarchy repository.

    Returns:
        The organization as the API renders it.
    """
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
    """List every organization.

    Organizations are ordered by slug. ``after`` continues from the cursor a
    previous page returned; a cursor that is not a valid continuation is
    refused with 400.
    \f
    Args:
        repository: The wired hierarchy repository.
        limit: The most organizations to return in this page.
        after: The ``next_cursor`` of the previous page, or None for the first.

    Returns:
        One page of organizations and the cursor to the next, if any.
    """
    return paginate(
        repository.list_organizations(), OrganizationView, key=_key, limit=limit, after=after
    )


@router.get("/{organization_id}", responses={404: problem_response("no such organization")})
async def get_organization(organization_id: UUID, repository: Repository) -> OrganizationView:
    """Fetch one organization by id.

    An unknown id is 404.
    \f
    Args:
        organization_id: The organization to fetch.
        repository: The wired hierarchy repository.

    Returns:
        The organization as the API renders it, including the ``version``
        that ``If-Match`` carries back on a PATCH.
    """
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
    """Update an organization's title or description.

    Requires ``organization.update`` on the organization. ``If-Match`` must
    carry the organization's current ``version``; a stale or malformed value
    is refused with 412 and nothing changes. Slugs are immutable: a ``slug``
    that differs from the current one is refused with 409. Every successful
    update advances ``version`` by one. An unknown organization is 404.
    \f
    The durable rewrite is blocking, so the operation runs in the threadpool
    rather than on the event loop.

    Args:
        organization_id: The organization to update.
        body: The fields to change; a field left out or null keeps its value.
        if_match: The caller's ``If-Match`` header.
        repository: The wired hierarchy repository.

    Returns:
        The updated organization as the API renders it.
    """
    return OrganizationView.model_validate(
        repository.patch_organization(
            organization_id,
            expected_version=expected_version(if_match),
            slug=body.slug,
            title=body.title,
            description=body.description,
        )
    )
