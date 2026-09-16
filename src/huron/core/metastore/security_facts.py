"""Security projections using the adapters' authoritative discovery readers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from huron.core.security.rules import Scope, ScopeType, Visibility

if TYPE_CHECKING:
    from uuid import UUID

    from huron.core.catalog.ports import CollectionReader
    from huron.core.catalog.types import Dataset, Organization, PlatformRoot, Project


class SecurityFacts:
    """Project only the facts Security needs, preserving the existing visibility predicates."""

    organizations: CollectionReader[Organization, PlatformRoot]
    projects: CollectionReader[Project, UUID]
    datasets: CollectionReader[Dataset, UUID]

    async def resource_scope(
        self, kind: ScopeType, resource_id: UUID, visibility: Visibility
    ) -> Scope:
        """Resolve target discovery before projecting complete scope ancestry.

        Args:
            kind: Organization, project or dataset scope.
            resource_id: The addressed resource.
            visibility: The target's discovery rights.

        Returns:
            A scope with authoritative ancestors.

        Raises:
            ValueError: If a system scope is requested as a catalog resource.
        """
        if kind is ScopeType.ORGANIZATION:
            await self.organizations.get(resource_id, visibility)
            return Scope(kind, resource_id, organization_id=resource_id)
        if kind is ScopeType.PROJECT:
            project = await self.projects.get(resource_id, visibility)
            return Scope(
                kind, resource_id, organization_id=project.organization_id, project_id=resource_id
            )
        if kind is ScopeType.DATASET:
            dataset = await self.datasets.get(resource_id, visibility)
            project = await self.projects.get(dataset.project_id, Visibility.ALL)
            return Scope(
                kind,
                resource_id,
                organization_id=project.organization_id,
                project_id=project.id,
                dataset_id=resource_id,
            )
        raise ValueError("system scope has no catalog resource")

    async def organization_slug(self, organization_id: UUID) -> str:
        """Read the stable organization name after provisioning authority was checked.

        Args:
            organization_id: The owning organization's identity.

        Returns:
            Its stable slug.
        """
        return (await self.organizations.get(organization_id, Visibility.ALL)).slug
