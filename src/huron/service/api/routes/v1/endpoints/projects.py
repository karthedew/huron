"""Projects: created by organization admins, edited by project admins."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from huron.service.api.authorization import require_organization, require_project
from huron.service.api.problems import problem_response
from huron.service.api.records import Project
from huron.service.api.routes.v1.pagination import Page, PageCursor, PageLimit, paginate
from huron.service.api.routes.v1.preconditions import (
    IdempotencyHeader,
    IfMatchHeader,
    expected_version,
)
from huron.service.api.routes.v1.schema.projects import CreateProject, PatchProject, ProjectView
from huron.service.api.runtime import Repository

organization_projects = APIRouter(
    prefix="/organizations/{organization_id}/projects", tags=["projects"]
)
router = APIRouter(prefix="/projects", tags=["projects"])


def _key(item: Project) -> tuple[str, str]:
    return (item.slug, str(item.id))


@organization_projects.post(
    "",
    status_code=201,
    dependencies=[Depends(require_organization("project.create"))],
    responses={
        404: problem_response("no such organization"),
        409: problem_response("project slug already exists"),
    },
)
def create_project(
    organization_id: UUID,
    body: CreateProject,
    idempotency_key: IdempotencyHeader,
    repository: Repository,
) -> ProjectView:
    """Persist one project; the durable write runs in the threadpool."""
    return ProjectView.model_validate(
        repository.create_project(
            organization_id,
            slug=body.slug,
            title=body.title,
            description=body.description,
            data_classification=body.data_classification,
            idempotency_key=idempotency_key,
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
    organization_id: UUID, repository: Repository, limit: PageLimit = 50, after: PageCursor = None
) -> Page[ProjectView]:
    return paginate(
        repository.list_projects(organization_id), ProjectView, key=_key, limit=limit, after=after
    )


@router.get("/{project_id}", responses={404: problem_response("no such project")})
async def get_project(project_id: UUID, repository: Repository) -> ProjectView:
    return ProjectView.model_validate(repository.get_project(project_id))


@router.patch(
    "/{project_id}",
    dependencies=[Depends(require_project("project.update"))],
    responses={
        404: problem_response("no such project"),
        409: problem_response("the slug on an existing project cannot change"),
        412: problem_response("If-Match does not match the current version"),
    },
)
def patch_project(
    project_id: UUID,
    body: PatchProject,
    if_match: IfMatchHeader,
    repository: Repository,
) -> ProjectView:
    """Persist the patch; the durable rewrite runs in the threadpool."""
    return ProjectView.model_validate(
        repository.patch_project(
            project_id,
            expected_version=expected_version(if_match),
            slug=body.slug,
            title=body.title,
            description=body.description,
        )
    )
