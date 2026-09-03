"""Path identifiers -> rbac.Scope, 404 before 403.

Each function resolves the path identifier through the repository before
any binding is consulted, so an unknown id never leaks its existence
through a permission error. The returned scope always carries its full
ancestry, because ``rbac.decide``'s inheritance walk reads those fields.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from huron.pkg.rbac import Scope, ScopeType

if TYPE_CHECKING:
    from ..repository import HierarchyRepository


def organization_scope(repository: HierarchyRepository, organization_id: UUID) -> Scope:
    """Resolve an organization id to its RBAC scope, 404 before 403.

    The organization is looked up purely for its existence: an unknown id
    fails with the repository's not-found error before any binding is
    read, so a caller without access cannot distinguish an organization
    that exists from one that does not.

    Args:
        repository: Where the organization is looked up.
        organization_id: The path identifier of the organization.

    Returns:
        An ORGANIZATION scope whose ancestry is the organization itself.
    """
    repository.get_organization(organization_id)  # 404 before 403 for unknown ids
    return Scope(ScopeType.ORGANIZATION, organization_id, organization_id=organization_id)


def project_scope(repository: HierarchyRepository, project_id: UUID) -> Scope:
    """Resolve a project id to its RBAC scope, 404 before 403.

    Args:
        repository: Where the project is looked up; an unknown id raises
            the repository's not-found error before any binding is read.
        project_id: The path identifier of the project.

    Returns:
        A PROJECT scope carrying the owning organization, so an
        organization-level binding covers it.
    """
    project = repository.get_project(project_id)
    return Scope(
        ScopeType.PROJECT,
        project_id,
        organization_id=project.organization_id,
        project_id=project_id,
    )


def dataset_scope(repository: HierarchyRepository, dataset_id: UUID) -> Scope:
    """Resolve a dataset id to its RBAC scope, 404 before 403.

    Two lookups: the dataset for its project, then the project for its
    organization, because a dataset record names only its parent and the
    scope must carry both ancestors.

    Args:
        repository: Where the dataset and its project are looked up; an
            unknown dataset id raises the repository's not-found error
            before any binding is read.
        dataset_id: The path identifier of the dataset.

    Returns:
        A DATASET scope carrying the owning project and organization, so a
        binding at either level covers it.
    """
    dataset = repository.get_dataset(dataset_id)
    project = repository.get_project(dataset.project_id)
    return Scope(
        ScopeType.DATASET,
        dataset_id,
        organization_id=project.organization_id,
        project_id=project.id,
        dataset_id=dataset_id,
    )
