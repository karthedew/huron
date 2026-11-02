"""Schema registry entries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import uuid
    from datetime import datetime

__all__ = ["BASE_SCHEMA_NAME", "SchemaEntry", "SchemaRef"]

BASE_SCHEMA_NAME = "huron-base"


@dataclass(frozen=True, slots=True)
class SchemaRef:
    """A short reference to a registry entry."""

    id: uuid.UUID
    name: str
    version: int

    def as_dict(self) -> dict[str, Any]:
        """Render for the API."""
        return {"id": str(self.id), "name": self.name, "version": self.version}


@dataclass(frozen=True, slots=True)
class SchemaEntry:
    """One immutable version of a named schema, at platform or organization scope."""

    id: uuid.UUID
    organization_id: uuid.UUID | None
    name: str
    version: int
    extends_id: uuid.UUID | None
    document: dict[str, Any]
    created_at: datetime
    created_by: str

    @property
    def ref(self) -> SchemaRef:
        """A short reference to this entry."""
        return SchemaRef(self.id, self.name, self.version)

    def as_dict(self) -> dict[str, Any]:
        """Render for the API."""
        return {
            "id": str(self.id),
            "organization_id": None if self.organization_id is None else str(self.organization_id),
            "scope": "platform" if self.organization_id is None else "organization",
            "name": self.name,
            "version": self.version,
            "extends_id": None if self.extends_id is None else str(self.extends_id),
            "document": self.document,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
        }
