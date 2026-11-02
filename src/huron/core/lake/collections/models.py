"""Collections: the leaves that hold files and metadata."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import uuid
    from datetime import datetime

    from huron.core.lake.schemas.models import SchemaRef

__all__ = ["UNSET", "Collection", "CollectionView", "Search", "State", "Unset", "Update"]


class State(StrEnum):
    """The lifecycle state of a collection."""

    DRAFT = "draft"
    ACTIVE = "active"
    INCOMPLETE = "incomplete"


class Unset:
    """Marks an update field the caller did not send."""

    def __repr__(self) -> str:
        return "UNSET"


UNSET = Unset()


@dataclass(frozen=True, slots=True)
class Collection:
    """A collection row."""

    id: uuid.UUID
    catalog_id: uuid.UUID
    namespace_id: uuid.UUID
    name: str
    identifier: str
    state: State
    version: int
    metadata: dict[str, Any]
    schema_override: dict[str, Any] | None
    file_count: int
    created_at: datetime
    created_by: str
    updated_at: datetime
    activated_at: datetime | None = None

    @property
    def settled(self) -> bool:
        """Whether the collection has a directory (active or incomplete)."""
        return self.state is not State.DRAFT


@dataclass(frozen=True, slots=True)
class Search:
    """Filters of a catalog search: free text, exact labels and states."""

    q: str | None = None
    labels: tuple[tuple[str, str], ...] = ()
    states: frozenset[State] = frozenset({State.ACTIVE, State.INCOMPLETE})


@dataclass(frozen=True, slots=True)
class Update:
    """A metadata merge patch and/or a schema override; ``UNSET`` leaves a field alone."""

    metadata_patch: dict[str, Any] | Unset = UNSET
    schema_override: dict[str, Any] | Unset | None = UNSET


@dataclass(frozen=True, slots=True)
class CollectionView:
    """A collection as the API shows it."""

    collection: Collection
    organization: str
    catalog: str
    namespace_path: str
    schema: SchemaRef
    problems: list[dict[str, str]] = field(default_factory=list)

    @property
    def disk_path(self) -> str | None:
        """The directory relative to the share prefix; ``None`` for a draft."""
        if not self.collection.settled:
            return None
        segments = (self.organization, self.catalog, *self.namespace_path.split("."))
        return "/".join((*segments, self.collection.name))

    def as_dict(self) -> dict[str, Any]:
        """Render for the API."""
        c = self.collection
        return {
            "id": str(c.id),
            "identifier": c.identifier,
            "organization": self.organization,
            "catalog": self.catalog,
            "namespace": self.namespace_path,
            "name": c.name,
            "state": str(c.state),
            "version": c.version,
            "metadata": c.metadata,
            "schema_override": c.schema_override,
            "schema": self.schema.as_dict(),
            "file_count": c.file_count,
            "created_at": c.created_at.isoformat(),
            "created_by": c.created_by,
            "updated_at": c.updated_at.isoformat(),
            "activated_at": None if c.activated_at is None else c.activated_at.isoformat(),
            "path": self.disk_path,
            "problems": self.problems,
        }
