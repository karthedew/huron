"""Durable canonical generation documents shared by catalog mutations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from asyncer import asyncify

from huron.core.foundation.canonical import canonical_bytes, jsonable

if TYPE_CHECKING:
    from pathlib import PurePosixPath

    from huron.core.catalog.ports import GenerationStorage
    from huron.core.catalog.types import Dataset, Organization, Project


class GenerationDocuments:
    """Serialize and durably install catalog generations using an injected store."""

    def __init__(self, storage: GenerationStorage) -> None:
        """Bind the storage capability used for durable document installation.

        Args:
            storage: Initialized generation storage owned by application wiring.
        """
        self._storage = storage

    async def write(self, directory: PurePosixPath, item: Organization | Project | Dataset) -> None:
        """Write the canonical generation, replacing an unacknowledged crashed attempt.

        The calling workflow stages the database mutation first and commits afterward.
        Serialization and durable filesystem writes run together off the event loop.
        Generation numbers outside the storage contract's range raise ValueError.

        Args:
            directory: The immutable catalog entity directory.
            item: The entity whose canonical generation is being published.
        """
        await asyncify(self._write)(directory, item)

    def _write(self, directory: PurePosixPath, item: Organization | Project | Dataset) -> None:
        """Serialize and install a generation in the worker thread.

        Args:
            directory: The immutable catalog entity directory.
            item: The entity whose canonical generation is being published.
        """
        document = jsonable(item)
        document["schema"] = "urn:huron:generation:1"
        self._storage.write_generation(directory, item.generation, canonical_bytes(document))
