"""Path identifiers -> rbac.Scope, 404 before 403.

Each function resolves the path identifier through the repository, with the
caller's ``Visibility``, before any binding is consulted, so an id the
caller cannot discover - absent or simply not theirs to see - never leaks
its existence through a permission error. The returned scope always carries
its full ancestry, because ``rbac.decide``'s inheritance walk reads those
fields.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from huron.pkg.rbac import Scope, ScopeType, Visibility

if TYPE_CHECKING:
    from uuid import UUID

    from huron.core._catalog import HierarchyRepository


async def resource_scope(
    repository: HierarchyRepository,
    kind: ScopeType,
    resource_id: UUID,
    visibility: Visibility,
) -> Scope:
    """Resolve a catalog resource's scope through its own discovery check.

    Args:
        repository: Source of authoritative resource ancestry.
        kind: The organization, project or dataset scope to resolve.
        resource_id: The addressed resource's identifier.
        visibility: The caller's discovery rights.

    Returns:
        The scope including every ancestor used for inherited permissions.

    Raises:
        ValueError: If system scope is requested instead of a catalog resource.
    """
    if kind is ScopeType.ORGANIZATION:
        return await organization_scope(repository, resource_id, visibility)
    if kind is ScopeType.PROJECT:
        return await project_scope(repository, resource_id, visibility)
    if kind is ScopeType.DATASET:
        return await dataset_scope(repository, resource_id, visibility)
    raise ValueError("system scope has no catalog resource")


async def organization_scope(
    repository: HierarchyRepository, organization_id: UUID, visibility: Visibility
) -> Scope:
    """Resolve an organization id to its RBAC scope, 404 before 403.

    The organization is read purely for its existence: an id ``visibility``
    does not admit fails with the repository's not-found error before any
    binding is read, so a caller without access cannot distinguish an
    organization that exists from one that does not, or from one that is
    simply not theirs to discover.

    Args:
        repository: Where the organization is looked up.
        organization_id: The path identifier of the organization.
        visibility: The caller's discovery rights.

    Returns:
        An ORGANIZATION scope whose ancestry is the organization itself.
    """
    await repository.organization(organization_id, visibility)  # 404 before 403
    return Scope(ScopeType.ORGANIZATION, organization_id, organization_id=organization_id)


async def project_scope(
    repository: HierarchyRepository, project_id: UUID, visibility: Visibility
) -> Scope:
    """Resolve a project id to its RBAC scope, 404 before 403.

    Args:
        repository: Where the project is looked up; an id ``visibility``
            does not admit raises the repository's not-found error before
            any binding is read.
        project_id: The path identifier of the project.
        visibility: The caller's discovery rights.

    Returns:
        A PROJECT scope carrying the owning organization, so an
        organization-level binding covers it.
    """
    project = await repository.project(project_id, visibility)
    return Scope(
        ScopeType.PROJECT,
        project_id,
        organization_id=project.organization_id,
        project_id=project_id,
    )


async def dataset_scope(
    repository: HierarchyRepository, dataset_id: UUID, visibility: Visibility
) -> Scope:
    """Resolve a dataset id to its RBAC scope, 404 before 403.

    Two reads: the dataset for its project, then the project - with
    unrestricted visibility, since only the dataset itself is the caller's
    visibility decision - for its organization, because a dataset record
    names only its parent and the scope must carry both ancestors.

    Args:
        repository: Where the dataset and its project are looked up; an id
            ``visibility`` does not admit raises the repository's
            not-found error before any binding is read.
        dataset_id: The path identifier of the dataset.
        visibility: The caller's discovery rights.

    Returns:
        A DATASET scope carrying the owning project and organization, so a
        binding at either level covers it.
    """
    dataset = await repository.dataset(dataset_id, visibility)
    project = await repository.project(dataset.project_id, Visibility.ALL)
    return Scope(
        ScopeType.DATASET,
        dataset_id,
        organization_id=project.organization_id,
        project_id=project.id,
        dataset_id=dataset_id,
    )
