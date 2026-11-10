"""The directories a repair plans, and each one as its rows describe it now."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import uuid

__all__ = ["Level", "PlannedDirectory", "PlannedRow", "RepairPlan"]


class Level(StrEnum):
    """What a planned directory belongs to."""

    ORGANIZATION = "organization"
    CATALOG = "catalog"
    NAMESPACE = "namespace"
    COLLECTION = "collection"


@dataclass(frozen=True, slots=True)
class PlannedDirectory:
    """A directory that a repair plans: its API path and the row it belongs to.

    ``path`` has the form of the views' ``disk_path`` (``<organization>/<catalog>/…``). ``id``
    is the id of the organization, catalog, namespace or settled collection.
    """

    path: str
    level: Level
    id: uuid.UUID


@dataclass(frozen=True, slots=True)
class RepairPlan:
    """The directories of one repair, parents first, and the catalog's share group.

    ``share_group`` is the group that the catalog's directory carries, ``None`` for the service
    group. An organization's plan holds its directory alone.
    """

    directories: tuple[PlannedDirectory, ...]
    share_group: str | None = None

    @property
    def catalog(self) -> PlannedDirectory | None:
        """The catalog's directory; ``None`` in an organization's plan."""
        return next((d for d in self.directories if d.level is Level.CATALOG), None)


@dataclass(frozen=True, slots=True)
class PlannedRow:
    """A planned directory as its rows describe it now.

    ``metadata`` is the ``metadata.json`` of a settled collection, ``None`` for any other
    directory.
    """

    metadata: bytes | None = None
