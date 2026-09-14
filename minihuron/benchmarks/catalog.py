"""Ephemeral catalog for one benchmark event loop, without database latency."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from minihuron.rawdatastore import DatasetRef, Ingest, IntegrityError, RevisionConflict

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from minihuron.rawdatastore import FileSpec, Revision


class BenchmarkCatalog:
    """Model session claims and publication for independent simulated users."""

    def __init__(self, users: int) -> None:
        """Create one independent dataset per user.

        Args:
            users: Number of simulated users.
        """
        self.datasets = {
            dataset_id: DatasetRef(dataset_id, f"datasets/{dataset_id}")
            for dataset_id in (uuid4() for _ in range(users))
        }
        self._heads: dict[UUID, UUID] = {}
        self._ordinals: dict[UUID, int] = {}
        self._sessions: dict[UUID, Ingest] = {}
        self._keys: dict[tuple[UUID, str], UUID] = {}
        self._locks: dict[UUID, asyncio.Lock] = {}
        self._receipts: dict[UUID, set[FileSpec]] = {}

    async def get_dataset(self, dataset_id: UUID) -> DatasetRef | None:
        """Look up a benchmark dataset.

        Args:
            dataset_id: Dataset identity.

        Returns:
            The dataset, when registered.
        """
        return self.datasets.get(dataset_id)

    async def begin_ingest(
        self, dataset_id: UUID, files: tuple[FileSpec, ...], idempotency_key: str
    ) -> Ingest:
        """Reserve a revision atomically within this event loop.

        Args:
            dataset_id: Dataset identity.
            files: Complete submission manifest.
            idempotency_key: Dataset-scoped request identity.

        Returns:
            A new or previously reserved ingest.

        Raises:
            ValueError: If a retry changes its manifest.
        """
        key = (dataset_id, idempotency_key)
        if key in self._keys:
            ingest = self._sessions[self._keys[key]]
            if ingest.files != files:
                raise ValueError("Idempotency key reused with different files")
            return ingest
        number = self._ordinals.get(dataset_id, 0) + 1
        ingest = Ingest(
            uuid4(),
            self.datasets[dataset_id],
            uuid4(),
            number,
            self._heads.get(dataset_id),
            files,
        )
        self._ordinals[dataset_id] = number
        self._sessions[ingest.ingest_id] = ingest
        self._keys[key] = ingest.ingest_id
        self._locks[ingest.ingest_id] = asyncio.Lock()
        self._receipts[ingest.ingest_id] = set()
        return ingest

    @asynccontextmanager
    async def upload_access(self, ingest_id: UUID) -> AsyncIterator[Ingest]:
        """Exclude writers and finalizers for one open ingest.

        Args:
            ingest_id: Reserved ingest identity.

        Yields:
            The exclusively claimed ingest.

        Raises:
            IntegrityError: If the ingest is no longer open.
        """
        async with self._locks[ingest_id]:
            ingest = self._sessions[ingest_id]
            if ingest.state != "OPEN":
                raise IntegrityError("Ingest is not open")
            yield ingest

    async def file_received(self, ingest_id: UUID, spec: FileSpec) -> None:
        """Record a verified file under its caller's session claim.

        Args:
            ingest_id: Claimed ingest identity.
            spec: Verified file declaration.

        Raises:
            IntegrityError: If the receipt does not belong to an open ingest.
        """
        ingest = self._sessions[ingest_id]
        if ingest.state != "OPEN" or spec not in ingest.files:
            raise IntegrityError("Invalid file receipt")
        self._receipts[ingest_id].add(spec)

    @asynccontextmanager
    async def finalize_access(self, ingest_id: UUID) -> AsyncIterator[Ingest]:
        """Seal complete ingests while excluding uploads and other finalizers.

        Args:
            ingest_id: Reserved ingest identity.

        Yields:
            The exclusively claimed ingest.

        Raises:
            IntegrityError: If files are missing or the session conflicted.
        """
        async with self._locks[ingest_id]:
            ingest = self._sessions[ingest_id]
            if ingest.state == "CONFLICT":
                raise IntegrityError("Ingest conflicted")
            if ingest.state == "OPEN":
                if self._receipts[ingest_id] != set(ingest.files):
                    raise IntegrityError("Missing file receipts")
                ingest = replace(ingest, state="SEALED")
                self._sessions[ingest_id] = ingest
            yield ingest

    async def publish(self, ingest: Ingest, revision: Revision) -> None:
        """Compare the dataset head and publish without an intervening await.

        Args:
            ingest: Exclusively claimed, sealed ingest.
            revision: Storage-validated revision.

        Raises:
            IntegrityError: If the ingest is not sealed or the revision differs.
            RevisionConflict: If another ingest has advanced the head.
        """
        current = self._sessions[ingest.ingest_id]
        if current.state == "COMMITTED":
            return
        if current.state != "SEALED" or revision.revision_id != current.revision_id:
            raise IntegrityError("Invalid publication")
        if self._heads.get(ingest.dataset.dataset_id) != ingest.expected_current_revision:
            self._sessions[ingest.ingest_id] = replace(current, state="CONFLICT")
            raise RevisionConflict("Dataset head changed")
        self._heads[ingest.dataset.dataset_id] = revision.revision_id
        self._sessions[ingest.ingest_id] = replace(current, state="COMMITTED")
