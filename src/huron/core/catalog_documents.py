"""Durable canonical generation documents shared by catalog mutations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from huron.pkg.catalog.manifest import canonical_bytes
from huron.pkg.catalog.records import jsonable

if TYPE_CHECKING:
    from pathlib import PurePosixPath

    from huron.pkg.catalog.ports import RawStore
    from huron.pkg.catalog.records import Dataset, Organization, Project


class GenerationDocuments:
    """Serialize and durably install catalog generations using an injected store."""

    def __init__(self, storage: RawStore) -> None:
        """Bind the storage capability used for durable document installation.

        Args:
            storage: Initialized generation storage owned by application wiring.
        """
        self._storage = storage

    def write(self, directory: PurePosixPath, item: Organization | Project | Dataset) -> None:
        """Write the canonical generation, replacing an unacknowledged crashed attempt.

        The calling workflow stages the database mutation first and commits afterward.
        Run this blocking filesystem operation off the event loop. Generation
        numbers outside the storage contract's range raise ValueError.

        Args:
            directory: The immutable catalog entity directory.
            item: The entity whose canonical generation is being published.
        """
        document = jsonable(item)
        document["schema"] = "urn:huron:generation:1"
        self._storage.write_generation(directory, item.generation, canonical_bytes(document))
