"""Projects: created by organization admins, edited by project admins.

Creating a project needs ``project.create`` on the owning organization and
hangs under it; editing needs ``project.update`` on the project itself, and
reading needs only a credential and the caller's visibility. Slugs are
chosen once, at creation, and never change.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from huron.pkg.auth import Principal
from huron.service.api.authorization import CurrentVisibility, require_organization, require_project
from huron.service.api.problems import problem_response
from huron.service.api.records import Project
from huron.service.api.repository import request_sha256
from huron.service.api.routes.v1.pagination import (
    Page,
    PageCursor,
    PageLimit,
    page,
    slug_cursor_key,
)
from huron.service.api.routes.v1.preconditions import (
    IdempotencyHeader,
    IfMatchHeader,
    expected_version,
)
from huron.service.api.routes.v1.schema.projects import CreateProject, PatchProject, ProjectView
from huron.service.api.runtime import Repository
from huron.service.api.stores import IdempotencyClaim

organization_projects = APIRouter(
    prefix="/organizations/{organization_id}/projects", tags=["projects"]
)
router = APIRouter(prefix="/projects", tags=["projects"])


def _key(item: Project) -> tuple[str, str]:
    return (item.slug, str(item.id))


@organization_projects.post(
    "",
    status_code=201,
    responses={
        404: problem_response("no such organization"),
        409: problem_response("project slug already exists"),
    },
)
async def create_project(
    organization_id: UUID,
    body: CreateProject,
    idempotency_key: IdempotencyHeader,
    repository: Repository,
    visibility: CurrentVisibility,
    actor: Annotated[Principal, Depends(require_organization("project.create"))],
) -> ProjectView:
    """Create a project in an organization.

    Requires ``project.create`` on the organization. The slug must be unique
    within the organization and can never change afterwards; a duplicate is
    refused with 409. ``data_classification`` must be one of the platform's
    configured classifications, or the request is refused with 400. An
    organization id that is absent or not discoverable by the caller is
    404. Replaying the same ``Idempotency-Key`` with the same request
    returns the original project instead of a 409; reusing the key for a
    different request is refused with 409.
    \f
    Args:
        organization_id: The organization the project belongs to.
        body: The slug, title, description and data classification to store.
        idempotency_key: The caller's ``Idempotency-Key`` header.
        repository: The wired hierarchy repository.
        visibility: The caller's discovery rights, used to resolve
            ``organization_id``.
        actor: The caller, whose subject scopes the idempotency claim.

    Returns:
        The project as the API renders it.
    """
    claim = IdempotencyClaim(
        principal=actor.subject,
        key=idempotency_key,
        request_sha256=request_sha256(
            "project",
            str(organization_id),
            body.slug,
            body.title,
            body.description,
            body.data_classification,
        ),
    )
    return ProjectView.model_validate(
        await repository.create_project(
            organization_id,
            visibility,
            slug=body.slug,
            title=body.title,
            description=body.description,
            data_classification=body.data_classification,
            claim=claim,
        )
    )


@organization_projects.get(
    "",
    responses={
        404: problem_response("no such organization"),
        400: problem_response("cursor is not a valid continuation"),
    },
)
async def list_projects(
    organization_id: UUID,
    repository: Repository,
    visibility: CurrentVisibility,
    limit: PageLimit = 50,
    after: PageCursor = None,
) -> Page[ProjectView]:
    """List the projects of an organization that the caller may discover.

    Projects are ordered by slug. ``after`` continues from the cursor a
    previous page returned; a cursor that is not a valid continuation is
    refused with 400. An organization id that is absent or not discoverable
    by the caller is 404, never an empty page.
    \f
    Args:
        organization_id: The organization whose projects to list.
        repository: The wired hierarchy repository.
        visibility: The caller's discovery rights.
        limit: The most projects to return in this page.
        after: The ``next_cursor`` of the previous page, or None for the first.

    Returns:
        One page of projects and the cursor to the next, if any.
    """
    window = await repository.projects(
        organization_id, visibility, limit=limit, after=slug_cursor_key(after)
    )
    return page(window, ProjectView, key=_key)


@router.get("/{project_id}", responses={404: problem_response("no such project")})
async def get_project(
    project_id: UUID, repository: Repository, visibility: CurrentVisibility
) -> ProjectView:
    """Fetch one project by id.

    An id that is absent or not discoverable by the caller is 404.
    \f
    Args:
        project_id: The project to fetch.
        repository: The wired hierarchy repository.
        visibility: The caller's discovery rights.

    Returns:
        The project as the API renders it, including the ``version`` that
        ``If-Match`` carries back on a PATCH.
    """
    project = await repository.project(project_id, visibility)
    return ProjectView.model_validate(project)


@router.patch(
    "/{project_id}",
    responses={
        404: problem_response("no such project"),
        409: problem_response("the slug on an existing project cannot change"),
        412: problem_response("If-Match does not match the current version"),
    },
)
async def patch_project(
    project_id: UUID,
    body: PatchProject,
    if_match: IfMatchHeader,
    repository: Repository,
    visibility: CurrentVisibility,
    _actor: Annotated[Principal, Depends(require_project("project.update"))],
) -> ProjectView:
    """Update a project's title or description.

    Requires ``project.update`` on the project. ``If-Match`` must carry the
    project's current ``version``; a stale value is refused with 412 and
    nothing changes, and a header that does not name a version at all is
    refused with 422. Slugs are immutable: a ``slug`` that differs from the
    current one is refused with 409. Every successful update advances
    ``version`` by one. An id that is absent or not discoverable by the
    caller is 404.
    \f
    Args:
        project_id: The project to update.
        body: The fields to change; a field left out or null keeps its value.
        if_match: The caller's ``If-Match`` header.
        repository: The wired hierarchy repository.
        visibility: The caller's discovery rights.
        _actor: The caller, held only as proof the capability check passed.

    Returns:
        The updated project as the API renders it.
    """
    return ProjectView.model_validate(
        await repository.patch_project(
            project_id,
            visibility,
            expected_version=expected_version(if_match),
            slug=body.slug,
            title=body.title,
            description=body.description,
        )
    )
