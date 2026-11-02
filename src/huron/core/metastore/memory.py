"""The in-memory state shared by the in-memory adapters."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import uuid

    from huron.core.lake.audit.models import AuditEntry
    from huron.core.lake.catalogs.models import Catalog
    from huron.core.lake.collections.models import Collection
    from huron.core.lake.files.models import Commit, FileRecord
    from huron.core.lake.namespaces.models import Namespace
    from huron.core.lake.organizations.models import Organization
    from huron.core.lake.schemas.models import SchemaEntry
    from huron.core.security.broker.keys import SigningKey
    from huron.core.security.rbac import Role, Scope

__all__ = ["MemoryState"]


@dataclass(slots=True)
class MemoryState:
    """Every table as a dictionary keyed by primary key."""

    organizations: dict[uuid.UUID, Organization] = field(default_factory=dict)
    catalogs: dict[uuid.UUID, Catalog] = field(default_factory=dict)
    namespaces: dict[uuid.UUID, Namespace] = field(default_factory=dict)
    collections: dict[uuid.UUID, Collection] = field(default_factory=dict)
    files: dict[tuple[uuid.UUID, str], FileRecord] = field(default_factory=dict)
    commits: dict[uuid.UUID, Commit] = field(default_factory=dict)
    schemas: dict[uuid.UUID, SchemaEntry] = field(default_factory=dict)
    grants: dict[tuple[Scope, Role, str], str] = field(default_factory=dict)
    audit: list[AuditEntry] = field(default_factory=list)
    keys: dict[str, SigningKey] = field(default_factory=dict)

    def copy(self) -> MemoryState:
        """A copy whose tables can change without touching this state."""
        return replace(
            self,
            organizations=dict(self.organizations),
            catalogs=dict(self.catalogs),
            namespaces=dict(self.namespaces),
            collections=dict(self.collections),
            files=dict(self.files),
            commits=dict(self.commits),
            schemas=dict(self.schemas),
            grants=dict(self.grants),
            audit=list(self.audit),
            keys=dict(self.keys),
        )
