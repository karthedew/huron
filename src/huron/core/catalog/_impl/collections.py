"""Typed actor-bound catalog discovery with current authority on every operation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, ClassVar
from uuid import UUID

from huron.core.catalog.layers import LAYER_ORDER, LAYER_SPECS
from huron.core.catalog.paths import dataset_dir, organization_dir, project_dir
from huron.core.catalog.types import Dataset, DescriptionChange, Organization, PlatformRoot, Project
from huron.core.security import as_rbac_principal
from huron.core.security.rules import Decision, ScopeType, Visibility, decide

from .documents import GenerationDocuments

if TYPE_CHECKING:
    from huron.core.catalog.ports import (
        CollectionReader,
        DescriptionStore,
        DescriptionTransaction,
        GenerationStorage,
    )
    from huron.core.foundation.paging import Window
    from huron.core.security import AccessPolicy


class _Collection[ItemT: (Organization, Project, Dataset), ParentT: (PlatformRoot, UUID)](ABC):
    """A fixed reader and parent scope, selected together by concrete construction."""

    _parent_kind: ClassVar[ScopeType]

    def __init__(
        self,
        access: AccessPolicy,
        readers: DescriptionStore,
        storage: GenerationStorage,
    ) -> None:
        """Bind the fixed reader and parent discovery rule.

        Args:
            access: Current actor authority.
            readers: Committed ancestry and transaction capabilities.
            storage: Durable generation storage.
        """
        self._access = access
        self._kind = {
            ScopeType.SYSTEM: ScopeType.ORGANIZATION,
            ScopeType.ORGANIZATION: ScopeType.PROJECT,
            ScopeType.PROJECT: ScopeType.DATASET,
        }[self._parent_kind]
        self._store = readers
        self._root = PurePosixPath(storage.root)
        self._generations = GenerationDocuments(storage)

    @property
    @abstractmethod
    def _reader(self) -> CollectionReader[ItemT, ParentT]:
        """Return the fixed typed reader selected by this collection's entity kind."""
        ...

    async def get(self, resource_id: UUID) -> ItemT:
        """Discover an entity with the authenticated actor's current visibility.

        Args:
            resource_id: The addressed resource's identifier.

        Returns:
            The entity; hidden and absent identifiers raise ResourceNotFound.
        """
        return await self._reader.get(resource_id, await self._access.visibility())

    async def browse(
        self, parent: ParentT, *, limit: int, after: tuple[str, UUID] | None
    ) -> Window[ItemT]:
        """Discover the parent before requesting its visible keyset window.

        Args:
            parent: The owning resource or explicit platform root.
            limit: Maximum number of returned entities.
            after: Exclusive slug and UUID cursor.

        Returns:
            A visible window; hidden or absent parents raise ResourceNotFound.
        """
        visibility = await self._access.visibility()
        if not isinstance(parent, PlatformRoot):
            await self._access.scope(self._parent_kind, parent)
        return await self._reader.browse(parent, visibility, limit=limit, after=after)

    async def describe(self, resource_id: UUID, change: DescriptionChange) -> ItemT:
        """Authorize, validate, CAS and durably publish a descriptive successor.

        Hidden targets fail before permission, slug or version errors. A valid
        no-op opens no transaction. Successful CAS precedes committed ancestry
        reads and off-thread generation writing; any write failure rolls back.

        Args:
            resource_id: The exact entity to update.
            change: Expected version and optional descriptive replacements.

        Returns:
            The unchanged record for a no-op or the durably published successor.
        """
        await self._access.require(f"{self._kind.value.lower()}.update", self._kind, resource_id)
        item = await self.get(resource_id)
        successor = item.describe(
            expected_version=change.expected_version,
            slug=change.slug,
            title=change.title,
            description=change.description,
        )
        if successor is item:
            return item
        async with self._store.transaction() as writer:
            directory = await self._persist(writer, successor, item.version)
            await self._generations.write(directory, successor)
        return successor

    async def _persist(
        self,
        writer: DescriptionTransaction,
        item: Organization | Project | Dataset,
        expected_version: int,
    ) -> PurePosixPath:
        """CAS the fixed entity and then read committed ancestry for its storage path.

        Args:
            writer: The current atomic transaction.
            item: The immutable successor.
            expected_version: The required persisted version.

        Returns:
            The stable generation directory after successful CAS.
        """
        if isinstance(item, Organization):
            await writer.organizations.describe(item, expected_version=expected_version)
            return organization_dir(self._root, item)
        if isinstance(item, Project):
            await writer.projects.describe(item, expected_version=expected_version)
            organization = await self._store.organizations.get(item.organization_id, Visibility.ALL)
            return project_dir(self._root, organization, item)
        await writer.datasets.describe(item, expected_version=expected_version)
        project = await self._store.projects.get(item.project_id, Visibility.ALL)
        organization = await self._store.organizations.get(project.organization_id, Visibility.ALL)
        return dataset_dir(self._root, organization, project, item)


class OrganizationCollection(_Collection[Organization, PlatformRoot]):
    """Organization discovery at the platform root."""

    _parent_kind = ScopeType.SYSTEM

    @property
    def _reader(self) -> CollectionReader[Organization, PlatformRoot]:
        """Return the organization reader with its explicit platform parent."""
        return self._store.organizations


class ProjectCollection(_Collection[Project, UUID]):
    """Project discovery beneath an admitted organization."""

    _parent_kind = ScopeType.ORGANIZATION

    @property
    def _reader(self) -> CollectionReader[Project, UUID]:
        """Return the project reader with its organization parent."""
        return self._store.projects


class DatasetCollection(_Collection[Dataset, UUID]):
    """Dataset discovery beneath an admitted project."""

    _parent_kind = ScopeType.PROJECT

    @property
    def _reader(self) -> CollectionReader[Dataset, UUID]:
        """Return the dataset reader with its project parent."""
        return self._store.datasets

    async def layers(self, dataset_id: UUID) -> list[dict[str, object]]:
        """Describe layer capabilities for the current actor.

        Args:
            dataset_id: The dataset whose layer workflow to describe.

        Returns:
            Layer descriptions with current read and write decisions.
        """
        dataset = await self.get(dataset_id)
        scope = await self._access.scope(ScopeType.DATASET, dataset_id)
        actor = as_rbac_principal(self._access.actor)
        bindings = await self._access.bindings()
        return [
            {
                "layer": layer,
                "derived_from": list(LAYER_SPECS[layer].derived_from),
                "principal_writable": LAYER_SPECS[layer].principal_writable,
                "accepts_direct_entry": LAYER_SPECS[layer].accepts_direct_entry,
                "is_entry_layer": layer.value == dataset.entry_layer,
                "produced_by": LAYER_SPECS[layer].produced_by,
                "caller_may": {
                    action: decide(bindings, actor, f"data.{action}", scope, layer=layer.value)
                    is Decision.ALLOW
                    for action in ("read", "write")
                },
            }
            for layer in LAYER_ORDER
        ]
