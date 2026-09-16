"""Authoritative catalog projections consumed by Security."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from uuid import UUID

    from .rules import Binding, ProjectVisibility, Scope, ScopeType, Visibility
    from .types import ServiceAccount


class CatalogFacts(Protocol):
    """Existence, discoverable ancestry, classification and organization naming."""

    async def project_visibilities(self) -> list[ProjectVisibility]:
        """Read current project classifications and ancestry.

        Returns:
            Every project's classification facts, without a visibility filter.
        """
        ...

    async def dataset_parents(self, dataset_ids: frozenset[UUID]) -> dict[UUID, UUID]:
        """Resolve the parents of dataset-scoped grants.

        Args:
            dataset_ids: The granted dataset identities.

        Returns:
            Existing datasets mapped to their projects.
        """
        ...

    async def resource_scope(
        self, kind: ScopeType, resource_id: UUID, visibility: Visibility
    ) -> Scope:
        """Read authoritative ancestry after checking resource discoverability.

        Args:
            kind: Organization, project or dataset scope.
            resource_id: The addressed resource.
            visibility: Security's discovery projection, applied to the target.

        Returns:
            The target and complete ancestry, or raises ResourceNotFound.
        """
        ...

    async def organization_slug(self, organization_id: UUID) -> str:
        """Read a stable organization name for an already-authorized provisioning operation.

        Args:
            organization_id: The existing organization.

        Returns:
            Its stable slug, or raises ResourceNotFound.
        """
        ...


class BindingFacts(Protocol):
    """Fresh human grants and service-account authority."""

    async def bindings_for(self, identifiers: frozenset[str]) -> tuple[Binding, ...]:
        """Read compiled grants for an actor and its groups.

        Args:
            identifiers: Subject and group identifiers.

        Returns:
            Current compiled bindings; Security applies inheritance and expiry.
        """
        ...

    async def service_account_by_subject(self, subject: str) -> ServiceAccount:
        """Read account authority including disabled accounts.

        Args:
            subject: The credential's service-account subject.

        Returns:
            The stored account or raises ResourceNotFound.
        """
        ...
