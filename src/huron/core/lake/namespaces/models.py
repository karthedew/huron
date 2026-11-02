"""Namespaces: a recursive tree inside a catalog."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import uuid
    from datetime import datetime

__all__ = ["Namespace", "NamespaceView"]


@dataclass(frozen=True, slots=True)
class Namespace:
    """A namespace; ``path`` is its dotted path inside the catalog (``ns1.ns2``)."""

    id: uuid.UUID
    catalog_id: uuid.UUID
    parent_id: uuid.UUID | None
    name: str
    path: str
    collections_allowed: bool
    version: int
    created_at: datetime
    created_by: str

    @property
    def segments(self) -> tuple[str, ...]:
        """The path as segments."""
        return tuple(self.path.split("."))


@dataclass(frozen=True, slots=True)
class NamespaceView:
    """A namespace as the API shows it."""

    namespace: Namespace
    catalog: str
    organization: str
    namespace_count: int
    collection_count: int

    @property
    def identifier(self) -> str:
        """``catalog.path``."""
        return f"{self.catalog}.{self.namespace.path}"

    @property
    def disk_path(self) -> str:
        """The directory relative to the share prefix."""
        return "/".join((self.organization, self.catalog, *self.namespace.segments))

    def as_dict(self) -> dict[str, Any]:
        """Render for the API."""
        namespace = self.namespace
        return {
            "id": str(namespace.id),
            "identifier": self.identifier,
            "catalog": self.catalog,
            "organization": self.organization,
            "name": namespace.name,
            "path": namespace.path,
            "parent": ".".join(namespace.segments[:-1]),
            "collections_allowed": namespace.collections_allowed,
            "version": namespace.version,
            "created_at": namespace.created_at.isoformat(),
            "created_by": namespace.created_by,
            "namespace_count": self.namespace_count,
            "collection_count": self.collection_count,
            "disk_path": self.disk_path,
        }
