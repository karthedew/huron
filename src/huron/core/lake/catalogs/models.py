"""Catalogs: one per science domain, each assigned a metadata schema."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import uuid
    from datetime import datetime

    from huron.core.lake.schemas.models import SchemaRef

__all__ = ["Catalog", "CatalogView"]


@dataclass(frozen=True, slots=True)
class Catalog:
    """A catalog belongs to one organization; its name is unique on the platform."""

    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    display_name: str
    description: str
    schema_id: uuid.UUID
    version: int
    created_at: datetime
    created_by: str


@dataclass(frozen=True, slots=True)
class CatalogView:
    """A catalog as the API shows it."""

    catalog: Catalog
    organization: str
    schema: SchemaRef
    namespace_count: int

    def as_dict(self) -> dict[str, Any]:
        """Render for the API."""
        catalog = self.catalog
        return {
            "id": str(catalog.id),
            "name": catalog.name,
            "organization": self.organization,
            "display_name": catalog.display_name,
            "description": catalog.description,
            "schema": self.schema.as_dict(),
            "version": catalog.version,
            "created_at": catalog.created_at.isoformat(),
            "created_by": catalog.created_by,
            "namespace_count": self.namespace_count,
        }
