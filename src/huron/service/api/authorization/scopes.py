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
    repository.get_organization(organization_id)  # 404 before 403 for unknown ids
    return Scope(ScopeType.ORGANIZATION, organization_id, organization_id=organization_id)


def project_scope(repository: HierarchyRepository, project_id: UUID) -> Scope:
    project = repository.get_project(project_id)
    return Scope(
        ScopeType.PROJECT,
        project_id,
        organization_id=project.organization_id,
        project_id=project_id,
    )


def dataset_scope(repository: HierarchyRepository, dataset_id: UUID) -> Scope:
    dataset = repository.get_dataset(dataset_id)
    project = repository.get_project(dataset.project_id)
    return Scope(
        ScopeType.DATASET,
        dataset_id,
        organization_id=project.organization_id,
        project_id=project.id,
        dataset_id=dataset_id,
    )
