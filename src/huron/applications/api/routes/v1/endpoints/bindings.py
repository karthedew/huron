"""Role bindings: grants of a role to a principal at a scope.

Bindings are granted, listed and revoked where they live: a project binding
through the project route by someone holding ``rbac.binding_manage`` there,
and so on up to SYSTEM. Every operation under a root therefore shares one
guard, declared once on the router; a route body never re-derives the scope
a binding belongs to, it only asks whether a named binding is a member of
the collection its root already proved the caller may administer.

Four routers serve the four scope levels: ``router`` for SYSTEM scope under
``/bindings``, and one each hanging under an organization, a project and a
dataset.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from huron.applications.api.authorization import (
    require_dataset,
    require_organization,
    require_project,
    require_system,
)
from huron.applications.api.dependencies import Catalog as Repository
from huron.applications.api.problems import problem_response
from huron.applications.api.routes.v1.pagination import Page, PageCursor, PageLimit, paginate
from huron.applications.api.routes.v1.schema.bindings import CreateRoleBinding, RoleBindingView
from huron.pkg.auth import Principal
from huron.pkg.catalog.errors import ResourceNotFound
from huron.pkg.catalog.records import RoleBindingRecord
from huron.pkg.rbac import ScopeType

_manage_system_bindings = require_system("rbac.binding_manage")
_manage_organization_bindings = require_organization("rbac.binding_manage")
_manage_project_bindings = require_project("rbac.binding_manage")
_manage_dataset_bindings = require_dataset("rbac.binding_manage")

router = APIRouter(
    prefix="/bindings", tags=["role-bindings"], dependencies=[Depends(_manage_system_bindings)]
)
organization_bindings = APIRouter(
    prefix="/organizations/{organization_id}/bindings",
    tags=["role-bindings"],
    dependencies=[Depends(_manage_organization_bindings)],
)
project_bindings = APIRouter(
    prefix="/projects/{project_id}/bindings",
    tags=["role-bindings"],
    dependencies=[Depends(_manage_project_bindings)],
)
dataset_bindings = APIRouter(
    prefix="/datasets/{dataset_id}/bindings",
    tags=["role-bindings"],
    dependencies=[Depends(_manage_dataset_bindings)],
)


def _expires(body: CreateRoleBinding) -> datetime | None:
    if body.expires_in_days is None:
        return None
    return datetime.now(UTC) + timedelta(days=body.expires_in_days)


def _key(item: RoleBindingRecord) -> tuple[str, str]:
    return (item.principal, item.role_code)


async def _binding_page(
    repository: Repository,
    scope_type: ScopeType,
    scope_id: UUID | None,
    limit: int,
    after: str | None,
) -> Page[RoleBindingView]:
    """Sort and serialize the binding roster of one authorized collection.

    Args:
        repository: The caller's authorized catalog operations.
        scope_type: The collection's scope level.
        scope_id: Its identifier, absent for SYSTEM scope.
        limit: The maximum number of bindings to return.
        after: The continuation cursor, absent for the first page.

    Returns:
        A page ordered by principal then role, including expired grants.
    """
    records = await repository.bindings_at(scope_type, scope_id)
    return paginate(sorted(records, key=_key), RoleBindingView, key=_key, limit=limit, after=after)


async def _grant_binding(
    body: CreateRoleBinding,
    repository: Repository,
    actor: Principal,
    scope_type: ScopeType,
    scope_id: UUID | None,
) -> RoleBindingView:
    """Translate a grant request into an authorized catalog operation and response.

    Args:
        body: The grantee, role and optional lifetime.
        repository: The caller's authorized catalog operations.
        actor: The authenticated administrator recorded as the creator.
        scope_type: The collection's scope level.
        scope_id: Its identifier, absent for SYSTEM scope.

    Returns:
        The stored grant serialized for the HTTP response.
    """
    return RoleBindingView.model_validate(
        await repository.grant_role(
            principal=body.principal,
            role_code=body.role,
            scope_type=scope_type,
            scope_id=scope_id,
            created_by=actor.subject,
            expires_at=_expires(body),
        )
    )


async def _revoke_binding(
    repository: Repository, binding_id: UUID, scope_type: ScopeType, scope_id: UUID | None
) -> None:
    """Revoke a binding only when it belongs to the route's authorized collection.

    The guard proved the caller may administer bindings here; it proved
    nothing about a binding granted elsewhere. A wrong-root request must
    not confirm that the binding exists or remove it from another collection.

    Args:
        repository: The caller's authorized catalog operations.
        binding_id: The requested binding identifier.
        scope_type: The collection's scope level.
        scope_id: Its identifier, absent for SYSTEM scope.

    Raises:
        ResourceNotFound: If the binding was granted at any other scope.
    """
    record = await repository.get_role_binding(binding_id)
    if record.scope_type != scope_type.value or record.scope_id != scope_id:
        raise ResourceNotFound(f"role binding does not exist: {record.id}")
    await repository.revoke_role(binding_id)


@router.get("", responses={400: problem_response("cursor is not a valid continuation")})
async def list_system_bindings(
    repository: Repository, limit: PageLimit = 50, after: PageCursor = None
) -> Page[RoleBindingView]:
    """List the role bindings granted at SYSTEM scope.

    Requires ``rbac.binding_manage`` at SYSTEM scope. Bindings are ordered
    by principal, then role. ``after`` continues from the cursor a previous
    page returned; a cursor that is not a valid continuation is refused
    with 400.
    \f
    Args:
        repository: The wired hierarchy repository.
        limit: The most bindings to return in this page.
        after: The ``next_cursor`` of the previous page, or None for the first.

    Returns:
        One page of bindings and the cursor to the next, if any.
    """
    return await _binding_page(repository, ScopeType.SYSTEM, None, limit, after)


@router.post(
    "", status_code=201, responses={409: problem_response("an identical role binding exists")}
)
async def create_system_binding(
    body: CreateRoleBinding,
    repository: Repository,
    actor: Annotated[Principal, Depends(_manage_system_bindings)],
) -> RoleBindingView:
    """Grant a role to a principal at SYSTEM scope.

    Requires ``rbac.binding_manage`` at SYSTEM scope. A grant identical to
    an existing one (same principal, role and scope) is refused with 409; a
    role the catalog does not define, one this kind of principal may not
    hold, or one that cannot be bound at SYSTEM scope is refused with 422.
    With ``expires_in_days`` the grant lapses on its own; without it, the
    grant stands until revoked.
    \f
    Args:
        body: The principal, the role code and the optional lifetime in days.
        repository: The wired hierarchy repository.
        actor: The administrator making the grant, recorded as its creator.

    Returns:
        The stored binding, with its generated id and timestamps.
    """
    return await _grant_binding(body, repository, actor, ScopeType.SYSTEM, None)


@organization_bindings.post(
    "",
    status_code=201,
    responses={
        404: problem_response("no such organization"),
        409: problem_response("an identical role binding exists"),
    },
)
async def create_organization_binding(
    organization_id: UUID,
    body: CreateRoleBinding,
    repository: Repository,
    actor: Annotated[Principal, Depends(_manage_organization_bindings)],
) -> RoleBindingView:
    """Grant a role to a principal on an organization.

    Requires ``rbac.binding_manage`` on the organization. An unknown
    organization is 404. A grant identical to an existing one (same
    principal, role and scope) is refused with 409; a role the catalog does
    not define, one this kind of principal may not hold, or one that cannot
    be bound at organization scope is refused with 422. With
    ``expires_in_days`` the grant lapses on its own; without it, the grant
    stands until revoked.
    \f
    Args:
        organization_id: The organization the role is granted on.
        body: The principal, the role code and the optional lifetime in days.
        repository: The wired hierarchy repository.
        actor: The administrator making the grant, recorded as its creator.

    Returns:
        The stored binding, with its generated id and timestamps.
    """
    return await _grant_binding(body, repository, actor, ScopeType.ORGANIZATION, organization_id)


@project_bindings.post(
    "",
    status_code=201,
    responses={
        404: problem_response("no such project"),
        409: problem_response("an identical role binding exists"),
    },
)
async def create_project_binding(
    project_id: UUID,
    body: CreateRoleBinding,
    repository: Repository,
    actor: Annotated[Principal, Depends(_manage_project_bindings)],
) -> RoleBindingView:
    """Grant a role to a principal on a project.

    Requires ``rbac.binding_manage`` on the project. An unknown project is
    404. A grant identical to an existing one (same principal, role and
    scope) is refused with 409; a role the catalog does not define, one
    this kind of principal may not hold, or one that cannot be bound at
    project scope is refused with 422. With ``expires_in_days`` the grant
    lapses on its own; without it, the grant stands until revoked.
    \f
    Args:
        project_id: The project the role is granted on.
        body: The principal, the role code and the optional lifetime in days.
        repository: The wired hierarchy repository.
        actor: The administrator making the grant, recorded as its creator.

    Returns:
        The stored binding, with its generated id and timestamps.
    """
    return await _grant_binding(body, repository, actor, ScopeType.PROJECT, project_id)


@dataset_bindings.post(
    "",
    status_code=201,
    responses={
        404: problem_response("no such dataset"),
        409: problem_response("an identical role binding exists"),
    },
)
async def create_dataset_binding(
    dataset_id: UUID,
    body: CreateRoleBinding,
    repository: Repository,
    actor: Annotated[Principal, Depends(_manage_dataset_bindings)],
) -> RoleBindingView:
    """Grant a role to a principal on a dataset.

    Requires ``rbac.binding_manage`` on the dataset. An unknown dataset is
    404. A grant identical to an existing one (same principal, role and
    scope) is refused with 409; a role the catalog does not define, one
    this kind of principal may not hold, or one that cannot be bound at
    dataset scope is refused with 422. With ``expires_in_days`` the grant
    lapses on its own; without it, the grant stands until revoked.
    \f
    Args:
        dataset_id: The dataset the role is granted on.
        body: The principal, the role code and the optional lifetime in days.
        repository: The wired hierarchy repository.
        actor: The administrator making the grant, recorded as its creator.

    Returns:
        The stored binding, with its generated id and timestamps.
    """
    return await _grant_binding(body, repository, actor, ScopeType.DATASET, dataset_id)


@organization_bindings.get(
    "",
    responses={
        404: problem_response("no such organization"),
        400: problem_response("cursor is not a valid continuation"),
    },
)
async def list_organization_bindings(
    organization_id: UUID, repository: Repository, limit: PageLimit = 50, after: PageCursor = None
) -> Page[RoleBindingView]:
    """List the role bindings granted on an organization.

    Requires ``rbac.binding_manage`` on the organization. Only grants made
    at this organization are listed, not those inherited from SYSTEM scope.
    Bindings are ordered by principal, then role. ``after`` continues from
    the cursor a previous page returned; a cursor that is not a valid
    continuation is refused with 400. An unknown organization is 404.
    \f
    Args:
        organization_id: The organization whose bindings to list.
        repository: The wired hierarchy repository.
        limit: The most bindings to return in this page.
        after: The ``next_cursor`` of the previous page, or None for the first.

    Returns:
        One page of bindings and the cursor to the next, if any.
    """
    return await _binding_page(repository, ScopeType.ORGANIZATION, organization_id, limit, after)


@project_bindings.get(
    "",
    responses={
        404: problem_response("no such project"),
        400: problem_response("cursor is not a valid continuation"),
    },
)
async def list_project_bindings(
    project_id: UUID, repository: Repository, limit: PageLimit = 50, after: PageCursor = None
) -> Page[RoleBindingView]:
    """List the role bindings granted on a project.

    Requires ``rbac.binding_manage`` on the project. Only grants made at
    this project are listed, not those inherited from its organization or
    from SYSTEM scope. Bindings are ordered by principal, then role.
    ``after`` continues from the cursor a previous page returned; a cursor
    that is not a valid continuation is refused with 400. An unknown
    project is 404.
    \f
    Args:
        project_id: The project whose bindings to list.
        repository: The wired hierarchy repository.
        limit: The most bindings to return in this page.
        after: The ``next_cursor`` of the previous page, or None for the first.

    Returns:
        One page of bindings and the cursor to the next, if any.
    """
    return await _binding_page(repository, ScopeType.PROJECT, project_id, limit, after)


@dataset_bindings.get(
    "",
    responses={
        404: problem_response("no such dataset"),
        400: problem_response("cursor is not a valid continuation"),
    },
)
async def list_dataset_bindings(
    dataset_id: UUID, repository: Repository, limit: PageLimit = 50, after: PageCursor = None
) -> Page[RoleBindingView]:
    """List the role bindings granted on a dataset.

    Requires ``rbac.binding_manage`` on the dataset. Only grants made at
    this dataset are listed, not those inherited from its project, its
    organization or SYSTEM scope. Bindings are ordered by principal, then
    role. ``after`` continues from the cursor a previous page returned; a
    cursor that is not a valid continuation is refused with 400. An unknown
    dataset is 404.
    \f
    Args:
        dataset_id: The dataset whose bindings to list.
        repository: The wired hierarchy repository.
        limit: The most bindings to return in this page.
        after: The ``next_cursor`` of the previous page, or None for the first.

    Returns:
        One page of bindings and the cursor to the next, if any.
    """
    return await _binding_page(repository, ScopeType.DATASET, dataset_id, limit, after)


@router.delete(
    "/{binding_id}", status_code=204, responses={404: problem_response("no such role binding")}
)
async def revoke_system_binding(repository: Repository, binding_id: UUID) -> None:
    """Revoke a role binding granted at SYSTEM scope.

    Requires ``rbac.binding_manage`` at SYSTEM scope. A binding that does
    not exist, or that was granted at some other scope, is 404 either way:
    this collection never confirms what was granted elsewhere. Success is
    204 with no body.
    \f
    Args:
        repository: The wired hierarchy repository.
        binding_id: The binding to revoke.
    """
    await _revoke_binding(repository, binding_id, ScopeType.SYSTEM, None)


@organization_bindings.delete(
    "/{binding_id}", status_code=204, responses={404: problem_response("no such role binding")}
)
async def revoke_organization_binding(
    repository: Repository, organization_id: UUID, binding_id: UUID
) -> None:
    """Revoke a role binding granted on an organization.

    Requires ``rbac.binding_manage`` on the organization. A binding that
    does not exist, or that was granted at some other scope, is 404 either
    way: this collection never confirms what was granted elsewhere. An
    unknown organization is also 404. Success is 204 with no body.
    \f
    Args:
        repository: The wired hierarchy repository.
        organization_id: The organization the binding was granted on.
        binding_id: The binding to revoke.
    """
    await _revoke_binding(repository, binding_id, ScopeType.ORGANIZATION, organization_id)


@project_bindings.delete(
    "/{binding_id}", status_code=204, responses={404: problem_response("no such role binding")}
)
async def revoke_project_binding(
    repository: Repository, project_id: UUID, binding_id: UUID
) -> None:
    """Revoke a role binding granted on a project.

    Requires ``rbac.binding_manage`` on the project. A binding that does
    not exist, or that was granted at some other scope, is 404 either way:
    this collection never confirms what was granted elsewhere. An unknown
    project is also 404. Success is 204 with no body.
    \f
    Args:
        repository: The wired hierarchy repository.
        project_id: The project the binding was granted on.
        binding_id: The binding to revoke.
    """
    await _revoke_binding(repository, binding_id, ScopeType.PROJECT, project_id)


@dataset_bindings.delete(
    "/{binding_id}", status_code=204, responses={404: problem_response("no such role binding")}
)
async def revoke_dataset_binding(
    repository: Repository, dataset_id: UUID, binding_id: UUID
) -> None:
    """Revoke a role binding granted on a dataset.

    Requires ``rbac.binding_manage`` on the dataset. A binding that does
    not exist, or that was granted at some other scope, is 404 either way:
    this collection never confirms what was granted elsewhere. An unknown
    dataset is also 404. Success is 204 with no body.
    \f
    Args:
        repository: The wired hierarchy repository.
        dataset_id: The dataset the binding was granted on.
        binding_id: The binding to revoke.
    """
    await _revoke_binding(repository, binding_id, ScopeType.DATASET, dataset_id)
