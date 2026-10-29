"""Persistence port for organizations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import uuid
    from collections.abc import Collection, Sequence

    from huron.core.lake.organizations.models import Organization

__all__ = ["OrganizationStore"]


class OrganizationStore(Protocol):
    """Reads and writes organizations."""

    async def insert(self, organization: Organization) -> None:
        """Store a new organization; raises ``NameTaken`` for a used name."""
        ...

    async def get(self, organization_id: uuid.UUID) -> Organization | None:
        """The organization with ``organization_id``."""
        ...

    async def get_by_name(self, name: str) -> Organization | None:
        """The organization named ``name``."""
        ...

    async def list(
        self, ids: Collection[uuid.UUID] | None, after: str | None, limit: int
    ) -> Sequence[Organization]:
        """Organizations sorted by name after ``after``; ``ids`` limits them unless ``None``."""
        ...

    async def delete(self, organization_id: uuid.UUID) -> None:
        """Remove an organization."""
        ...

    async def catalog_count(self, organization_id: uuid.UUID) -> int:
        """How many catalogs the organization has."""
        ...
