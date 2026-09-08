"""Organizations: creation is platform-scope; edits are organization-scope.

Creating an organization needs ``organization.create`` at SYSTEM scope,
editing one needs ``organization.update`` on that organization, and reading
needs only a credential and the caller's visibility. Slugs are chosen once,
at creation, and never change.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from huron.applications.api.authorization import (
    CurrentVisibility,
    require_organization,
    require_system,
)
from huron.applications.api.dependencies import Catalog as Repository
from huron.applications.api.problems import problem_response
from huron.applications.api.routes.v1.pagination import (
    Page,
    PageCursor,
    PageLimit,
    page,
    slug_cursor_key,
)
from huron.applications.api.routes.v1.preconditions import (
    IdempotencyHeader,
    IfMatchHeader,
    expected_version,
)
from huron.applications.api.routes.v1.schema.organizations import (
    CreateOrganization,
    OrganizationView,
    PatchOrganization,
)
from huron.core.idempotency import request_sha256
from huron.pkg.auth import Principal
from huron.pkg.catalog.records import Organization
from huron.pkg.metastore import IdempotencyClaim

router = APIRouter(prefix="/organizations", tags=["organizations"])


def _key(item: Organization) -> tuple[str, str]:
    return (item.slug, str(item.id))


@router.post(
    "",
    status_code=201,
    responses={409: problem_response("organization slug already exists")},
)
async def create_organization(
    body: CreateOrganization,
    idempotency_key: IdempotencyHeader,
    repository: Repository,
    actor: Annotated[Principal, Depends(require_system("organization.create"))],
) -> OrganizationView:
    """Create an organization.

    Requires ``organization.create`` at SYSTEM scope. The slug must be unique
    across the platform and can never change afterwards; a duplicate is
    refused with 409. Replaying the same ``Idempotency-Key`` with the same
    request returns the original organization instead of a 409; reusing the
    key for a different request is refused with 409.
    \f
    Args:
        body: The slug, title and description to store.
        idempotency_key: The caller's ``Idempotency-Key`` header.
        repository: The wired hierarchy repository.
        actor: The caller, whose subject scopes the idempotency claim.

    Returns:
        The organization as the API renders it.
    """
    claim = IdempotencyClaim(
        principal=actor.subject,
        key=idempotency_key,
        request_sha256=request_sha256("organization", body.slug, body.title, body.description),
    )
    return OrganizationView.model_validate(
        await repository.create_organization(
            slug=body.slug, title=body.title, description=body.description, claim=claim
        )
    )


@router.get("", responses={400: problem_response("cursor is not a valid continuation")})
async def list_organizations(
    repository: Repository,
    visibility: CurrentVisibility,
    limit: PageLimit = 50,
    after: PageCursor = None,
) -> Page[OrganizationView]:
    """List every organization the caller may discover.

    Organizations are ordered by slug. ``after`` continues from the cursor a
    previous page returned; a cursor that is not a valid continuation is
    refused with 400.
    \f
    Args:
        repository: The wired hierarchy repository.
        visibility: The caller's discovery rights.
        limit: The most organizations to return in this page.
        after: The ``next_cursor`` of the previous page, or None for the first.

    Returns:
        One page of organizations and the cursor to the next, if any.
    """
    window = await repository.organizations(limit=limit, after=slug_cursor_key(after))
    return page(window, OrganizationView, key=_key)


@router.get("/{organization_id}", responses={404: problem_response("no such organization")})
async def get_organization(
    organization_id: UUID, repository: Repository, visibility: CurrentVisibility
) -> OrganizationView:
    """Fetch one organization by id.

    An id that is absent or not discoverable by the caller is 404.
    \f
    Args:
        organization_id: The organization to fetch.
        repository: The wired hierarchy repository.
        visibility: The caller's discovery rights.

    Returns:
        The organization as the API renders it, including the ``version``
        that ``If-Match`` carries back on a PATCH.
    """
    organization = await repository.organization(organization_id)
    return OrganizationView.model_validate(organization)


@router.patch(
    "/{organization_id}",
    responses={
        404: problem_response("no such organization"),
        409: problem_response("the slug on an existing organization cannot change"),
        412: problem_response("If-Match does not match the current version"),
    },
)
async def patch_organization(
    organization_id: UUID,
    body: PatchOrganization,
    if_match: IfMatchHeader,
    repository: Repository,
    visibility: CurrentVisibility,
    _actor: Annotated[Principal, Depends(require_organization("organization.update"))],
) -> OrganizationView:
    """Update an organization's title or description.

    Requires ``organization.update`` on the organization. ``If-Match`` must
    carry the organization's current ``version``; a stale value is refused
    with 412 and nothing changes, and a header that does not name a version
    at all is refused with 422. Slugs are immutable: a ``slug`` that differs
    from the current one is refused with 409. Every successful update
    advances ``version`` by one. An id that is absent or not discoverable by
    the caller is 404.
    \f
    Args:
        organization_id: The organization to update.
        body: The fields to change; a field left out or null keeps its value.
        if_match: The caller's ``If-Match`` header.
        repository: The wired hierarchy repository.
        visibility: The caller's discovery rights.
        _actor: The caller, held only as proof the capability check passed.

    Returns:
        The updated organization as the API renders it.
    """
    return OrganizationView.model_validate(
        await repository.patch_organization(
            organization_id,
            expected_version=expected_version(if_match),
            slug=body.slug,
            title=body.title,
            description=body.description,
        )
    )
