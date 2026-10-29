"""The audit vocabulary and entries."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import uuid
    from datetime import datetime

__all__ = ["Action", "AuditEntry", "ObjectType"]


class Action(StrEnum):
    """Every action the audit log records."""

    PLATFORM_GRANT = "platform.grant"
    PLATFORM_REVOKE = "platform.revoke"
    ORGANIZATION_CREATE = "organization.create"
    ORGANIZATION_DELETE = "organization.delete"
    ORGANIZATION_GRANT = "organization.grant"
    ORGANIZATION_REVOKE = "organization.revoke"
    CATALOG_CREATE = "catalog.create"
    CATALOG_DELETE = "catalog.delete"
    CATALOG_GRANT = "catalog.grant"
    CATALOG_REVOKE = "catalog.revoke"
    CATALOG_ASSIGN_SCHEMA = "catalog.assign_schema"
    NAMESPACE_CREATE = "namespace.create"
    NAMESPACE_DELETE = "namespace.delete"
    NAMESPACE_CONFIGURE = "namespace.configure"
    SCHEMA_PUBLISH = "schema.publish"
    COLLECTION_CREATE = "collection.create"
    COLLECTION_UPDATE_METADATA = "collection.update_metadata"
    COLLECTION_SET_SCHEMA_OVERRIDE = "collection.set_schema_override"
    COLLECTION_ACTIVATE = "collection.activate"
    COLLECTION_MARK_INCOMPLETE = "collection.mark_incomplete"
    COLLECTION_MARK_ACTIVE = "collection.mark_active"
    COLLECTION_COMMIT = "collection.commit"
    COLLECTION_DELETE = "collection.delete"
    SIGNING_KEY_ROTATE = "signing_key.rotate"


class ObjectType(StrEnum):
    """The kind of object an entry is about."""

    PLATFORM = "platform"
    ORGANIZATION = "organization"
    CATALOG = "catalog"
    NAMESPACE = "namespace"
    SCHEMA = "schema"
    COLLECTION = "collection"
    SIGNING_KEY = "signing_key"


@dataclass(frozen=True, slots=True)
class AuditEntry:
    """One audited change; ``id`` is assigned by the store."""

    at: datetime
    actor: str
    action: Action
    object_type: ObjectType
    object_id: uuid.UUID | None
    catalog_id: uuid.UUID | None = None
    organization_id: uuid.UUID | None = None
    detail: dict[str, Any] = field(default_factory=dict)
    id: int | None = None

    def as_dict(self) -> dict[str, Any]:
        """Render for the API."""
        return {
            "id": self.id,
            "at": self.at.isoformat(),
            "actor": self.actor,
            "action": str(self.action),
            "object_type": str(self.object_type),
            "object_id": None if self.object_id is None else str(self.object_id),
            "catalog_id": None if self.catalog_id is None else str(self.catalog_id),
            "organization_id": None if self.organization_id is None else str(self.organization_id),
            "detail": self.detail,
        }
