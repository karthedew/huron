"""Raw bridge test wiring using the actual upload engine and temporary POSIX files."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from huron.applications.api.app import create_app
from huron.applications.api.settings import ApiSettings, ClassificationValue
from huron.core.catalog.external import ExternalDataset, target_key
from huron.core.catalog.types import PlatformRoot
from huron.core.foundation.errors import ResourceNotFound
from huron.core.metastore import InMemoryHierarchyStore
from huron.core.security.rules import Visibility
from tests.unit.support import memory_stores

if TYPE_CHECKING:
    from uuid import UUID

    from fastapi import FastAPI

    from huron.applications.api.runtime import ApiStores
    from huron.core.catalog.ports import CollectionReader
    from huron.core.catalog.types import Dataset, Organization, Project
    from huron.core.security.raw_delegation import DelegationTarget


async def _existing_identity[ItemT: (Organization, Project, Dataset), ParentT](
    reader: CollectionReader[ItemT, ParentT], parent: ParentT, slug: str
) -> UUID | None:
    """Find one deterministic infrastructure slug without exposing it to a user."""
    after: tuple[str, UUID] | None = None
    while True:
        page = await reader.browse(parent, Visibility(unrestricted=True), limit=100, after=after)
        for item in page.items:
            if item.slug == slug:
                return item.id
        if not page.has_more or not page.items:
            return None
        last = page.items[-1]
        after = (last.slug, last.id)


class MemoryRawWebStore:
    """Keep only mapping and acknowledgement facts; revisions use the real hierarchy."""

    def __init__(self, hierarchy: InMemoryHierarchyStore) -> None:
        self._hierarchy = hierarchy
        self._targets: dict[str, ExternalDataset] = {}
        self._datasets: dict[UUID, ExternalDataset] = {}
        self._registered: set[UUID] = set()

    async def by_target(self, target: DelegationTarget) -> ExternalDataset | None:
        """Resolve an exact endpoint, realm and target tuple."""
        return self._targets.get(target_key(target))

    async def provisioned_identity(
        self,
        kind: Literal["organization", "project", "dataset"],
        slug: str,
        parent_id: UUID | None,
    ) -> UUID | None:
        """Recover committed infrastructure identities after retry receipts expire."""
        if kind == "organization":
            return await _existing_identity(self._hierarchy.organizations, PlatformRoot.ROOT, slug)
        if parent_id is None:
            raise ValueError("projects and datasets require a parent")
        if kind == "project":
            return await _existing_identity(self._hierarchy.projects, parent_id, slug)
        return await _existing_identity(self._hierarchy.datasets, parent_id, slug)

    async def by_dataset(self, dataset_id: UUID) -> ExternalDataset:
        """Resolve a stored dataset identity, concealing unknown IDs."""
        try:
            return self._datasets[dataset_id]
        except KeyError as error:
            raise ResourceNotFound("no such Raw dataset") from error

    async def remember(self, mapping: ExternalDataset) -> ExternalDataset:
        """Preserve both uniqueness constraints without replacing a concurrent mapping."""
        key = target_key(mapping.target)
        existing = self._targets.get(key) or self._datasets.get(mapping.dataset_id)
        if existing is not None and existing != mapping:
            raise RuntimeError("conflicting Raw target mapping")
        self._targets[key] = mapping
        self._datasets[mapping.dataset_id] = mapping
        return mapping

    async def registered(self, revision_id: UUID) -> bool:
        """Return whether the bridge acknowledged external registration."""
        return revision_id in self._registered

    async def acknowledge(self, revision_id: UUID) -> None:
        """Acknowledge a verified committed revision idempotently."""
        self._registered.add(revision_id)

    async def revision_ids(
        self, dataset_id: UUID, *, before: int | None, limit: int
    ) -> tuple[UUID, ...]:
        """Page the hierarchy's revisions newest first, as the Postgres query reads its table."""
        newest_first = sorted(
            (
                record
                for record in self._hierarchy._revisions.values()
                if record.dataset_id == dataset_id and (before is None or record.number < before)
            ),
            key=lambda record: record.number,
            reverse=True,
        )
        return tuple(record.id for record in newest_first[:limit])


def raw_web_stores() -> ApiStores:
    """Create isolated stores for the real Raw workflow and its external mappings."""
    hierarchy = InMemoryHierarchyStore()
    return replace(memory_stores(), hierarchy=hierarchy, raw_web=MemoryRawWebStore(hierarchy))


def raw_web_app() -> FastAPI:
    """Start the browser fixture with real POSIX publication under its temporary root."""
    settings = ApiSettings(
        env="development",
        auth_mode="credentials",
        data_root=str(Path(os.environ["HURON_E2E_RAW_ROOT"])),
        database_url="postgresql://unused",
        classification_vocabulary=[ClassificationValue(code="open", order=0, discoverable=True)],
        raw_bridge_secret=os.environ["HURON_RAW_BRIDGE_SECRET"],
        completion_reserve_bytes=0,
    )
    return create_app(settings=settings, stores=raw_web_stores())
