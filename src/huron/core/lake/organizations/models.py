"""Organizations: the top of the hierarchy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import uuid
    from datetime import datetime

__all__ = ["Organization", "OrganizationView"]


@dataclass(frozen=True, slots=True)
class Organization:
    """An organization owns catalogs."""

    id: uuid.UUID
    name: str
    display_name: str
    description: str
    version: int
    created_at: datetime
    created_by: str


@dataclass(frozen=True, slots=True)
class OrganizationView:
    """An organization as the API shows it."""

    organization: Organization
    catalog_count: int

    def as_dict(self) -> dict[str, Any]:
        """Render for the API."""
        organization = self.organization
        return {
            "id": str(organization.id),
            "name": organization.name,
            "display_name": organization.display_name,
            "description": organization.description,
            "version": organization.version,
            "created_at": organization.created_at.isoformat(),
            "created_by": organization.created_by,
            "catalog_count": self.catalog_count,
        }
