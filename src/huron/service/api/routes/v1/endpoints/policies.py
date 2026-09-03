"""Policies and their attachment to organizations, projects, and datasets.

A policy definition is a platform-wide resource that any credential may
create or list, because creating one grants nothing; attaching it to a
scope is the guarded act, needing ``organization.policy_attach``,
``project.policy_attach`` or ``dataset.policy_attach`` on the organization,
project or dataset it is attached to. Policies never attach at SYSTEM scope.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from huron.pkg.auth import Principal
from huron.pkg.rbac import ScopeType
from huron.service.api.authorization import (
    CurrentPrincipal,
    require_dataset,
    require_organization,
    require_project,
)
from huron.service.api.problems import problem_response
from huron.service.api.records import Policy
from huron.service.api.routes.v1.pagination import Page, PageCursor, PageLimit, paginate
from huron.service.api.routes.v1.schema.policies import (
    AttachPolicy,
    CreatePolicy,
    PolicyAttachmentView,
    PolicyView,
)
from huron.service.api.runtime import Repository

router = APIRouter(prefix="/policies", tags=["policies"])
organization_attachments = APIRouter(
    prefix="/organizations/{organization_id}/policy-attachments", tags=["policy-attachments"]
)
project_attachments = APIRouter(
    prefix="/projects/{project_id}/policy-attachments", tags=["policy-attachments"]
)
dataset_attachments = APIRouter(
    prefix="/datasets/{dataset_id}/policy-attachments", tags=["policy-attachments"]
)


def _key(item: Policy) -> tuple[str, str]:
    return (item.name, str(item.id))


@router.post("", status_code=201)
async def create_policy(
    body: CreatePolicy, repository: Repository, actor: CurrentPrincipal
) -> PolicyView:
    """Create a policy definition.

    Creating a policy grants nothing - attachment is the guarded act - so
    no capability beyond a credential is needed here. ``spec`` is the
    caller's own JSON, stored and returned verbatim and never interpreted
    by the service; a spec over 1 MiB in canonical form is refused with 422.
    \f
    Args:
        body: The policy type, a display name and the spec to store.
        repository: The wired hierarchy repository.
        actor: The caller, recorded as the policy's creator.

    Returns:
        The policy as the API renders it.
    """
    record = await repository.create_policy(
        policy_type=body.policy_type,
        name=body.name,
        spec=body.spec,
        created_by=actor.subject,
    )
    return PolicyView.model_validate(record)


@router.get("", responses={400: problem_response("cursor is not a valid continuation")})
async def list_policies(
    repository: Repository, limit: PageLimit = 50, after: PageCursor = None
) -> Page[PolicyView]:
    """List every policy definition.

    Policies are ordered by name, then id, since names are not unique.
    ``after`` continues from the cursor a previous page returned; a cursor
    that is not a valid continuation is refused with 400.
    \f
    Args:
        repository: The wired hierarchy repository.
        limit: The most policies to return in this page.
        after: The ``next_cursor`` of the previous page, or None for the first.

    Returns:
        One page of policies and the cursor to the next, if any.
    """
    records = await repository.list_policies()
    return paginate(sorted(records, key=_key), PolicyView, key=_key, limit=limit, after=after)


@organization_attachments.post(
    "",
    status_code=201,
    responses={
        404: problem_response("no such organization or policy"),
        409: problem_response("policy is already attached at this scope"),
    },
)
async def attach_to_organization(
    organization_id: UUID,
    body: AttachPolicy,
    repository: Repository,
    actor: Annotated[Principal, Depends(require_organization("organization.policy_attach"))],
) -> PolicyAttachmentView:
    """Attach a policy to an organization.

    Requires ``organization.policy_attach`` on the organization. An unknown
    organization or policy is 404; a policy already attached to this
    organization is refused with 409.
    \f
    Args:
        organization_id: The organization the policy is attached to.
        body: The id of the policy to attach.
        repository: The wired hierarchy repository.
        actor: The caller, recorded as the attachment's author.

    Returns:
        The attachment: the policy, the scope it now applies to, who
        attached it and when.
    """
    attachment = await repository.attach_policy(
        UUID(body.policy_id),
        scope_type=ScopeType.ORGANIZATION,
        scope_id=organization_id,
        attached_by=actor.subject,
    )
    return PolicyAttachmentView.model_validate(attachment)


@project_attachments.post(
    "",
    status_code=201,
    responses={
        404: problem_response("no such project or policy"),
        409: problem_response("policy is already attached at this scope"),
    },
)
async def attach_to_project(
    project_id: UUID,
    body: AttachPolicy,
    repository: Repository,
    actor: Annotated[Principal, Depends(require_project("project.policy_attach"))],
) -> PolicyAttachmentView:
    """Attach a policy to a project.

    Requires ``project.policy_attach`` on the project. An unknown project
    or policy is 404; a policy already attached to this project is refused
    with 409.
    \f
    Args:
        project_id: The project the policy is attached to.
        body: The id of the policy to attach.
        repository: The wired hierarchy repository.
        actor: The caller, recorded as the attachment's author.

    Returns:
        The attachment: the policy, the scope it now applies to, who
        attached it and when.
    """
    attachment = await repository.attach_policy(
        UUID(body.policy_id),
        scope_type=ScopeType.PROJECT,
        scope_id=project_id,
        attached_by=actor.subject,
    )
    return PolicyAttachmentView.model_validate(attachment)


@dataset_attachments.post(
    "",
    status_code=201,
    responses={
        404: problem_response("no such dataset or policy"),
        409: problem_response("policy is already attached at this scope"),
    },
)
async def attach_to_dataset(
    dataset_id: UUID,
    body: AttachPolicy,
    repository: Repository,
    actor: Annotated[Principal, Depends(require_dataset("dataset.policy_attach"))],
) -> PolicyAttachmentView:
    """Attach a policy to a dataset.

    Requires ``dataset.policy_attach`` on the dataset. An unknown dataset
    or policy is 404; a policy already attached to this dataset is refused
    with 409.
    \f
    Args:
        dataset_id: The dataset the policy is attached to.
        body: The id of the policy to attach.
        repository: The wired hierarchy repository.
        actor: The caller, recorded as the attachment's author.

    Returns:
        The attachment: the policy, the scope it now applies to, who
        attached it and when.
    """
    attachment = await repository.attach_policy(
        UUID(body.policy_id),
        scope_type=ScopeType.DATASET,
        scope_id=dataset_id,
        attached_by=actor.subject,
    )
    return PolicyAttachmentView.model_validate(attachment)
