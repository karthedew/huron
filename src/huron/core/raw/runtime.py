"""Public construction and trusted deployment maintenance for Raw operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._impl.ingest import IngestService
from ._impl.ingestion import RawIngestionService
from ._impl.reader import RevisionService
from ._impl.revisions import RevisionReadService

if TYPE_CHECKING:
    from huron.core.catalog import CatalogCreation, DatasetCollection
    from huron.core.foundation.clock import Clock
    from huron.core.security import AccessPolicy

    from .ports import HierarchyStore, RawStore
    from .types import ExpiryReport


class RawRuntime:
    """Own private Raw mechanics while publishing only actor-bound operations and expiry."""

    def __init__(self, storage: RawStore, persistence: HierarchyStore, *, clock: Clock) -> None:
        """Compose Raw over injected capabilities without acquiring their lifetimes.

        Args:
            storage: Initialized Raw storage.
            persistence: Raw persistence sharing the application's transaction implementation.
            clock: Authoritative lease clock.
        """
        self._ingest = IngestService(storage, persistence, clock=clock)
        self._reader = RevisionService(storage, persistence)

    def ingestion(
        self, access: AccessPolicy, catalog: CatalogCreation, datasets: DatasetCollection
    ) -> RawIngestionService:
        """Bind complete upload operations to one authenticated actor.

        Args:
            access: Fresh actor-bound authorization policy.
            catalog: Actor-bound dataset creation.
            datasets: Actor-bound dataset discovery.

        Returns:
            Authorized upload creation, inspection and publication operations.
        """
        return RawIngestionService(self._ingest, access, catalog, datasets)

    def revisions(self, access: AccessPolicy) -> RevisionReadService:
        """Bind revision discovery and downloads to one authenticated actor.

        Args:
            access: Fresh actor-bound authorization policy.

        Returns:
            Authorized revision discovery and download operations.
        """
        return RevisionReadService(self._reader, access)

    async def expire_lapsed(self, *, limit: int) -> ExpiryReport:
        """Run one trusted deployment-maintenance expiry pass.

        Args:
            limit: Maximum lapsed renewable sessions to examine.

        Returns:
            Listed, expired and concurrently changed session counts.
        """
        return await self._ingest.expire_lapsed(limit=limit)
