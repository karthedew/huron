"""Typed actor-bound catalog discovery with current authority on every operation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING
from uuid import UUID

from asyncer import asyncify

from huron.pkg.catalog.paths import dataset_dir, organization_dir, project_dir
from huron.pkg.catalog.persistence import PlatformRoot
from huron.pkg.catalog.records import Dataset, Organization, Project
from huron.pkg.rbac import ScopeType, Visibility

from .catalog_documents import GenerationDocuments

if TYPE_CHECKING:
    from huron.pkg.catalog.persistence import Window
    from huron.pkg.catalog.ports import RawStore

    from .access import AccessPolicy
    from .catalog_ports import CollectionReader, DescriptionStore, DescriptionTransaction


@dataclass(frozen=True, slots=True)
class DescriptionChange:
    """A versioned descriptive change: null retains values and empty strings replace them.

    Attributes:
        expected_version: The version observed by the caller, required even for no-ops.
        slug: Current slug or None; any different slug is refused before version checking.
        title: Replacement title, or None to preserve it.
        description: Replacement description, or None to preserve it.
    """

    expected_version: int
    slug: str | None = None
    title: str | None = None
    description: str | None = None


class _Collection[ItemT: (Organization, Project, Dataset), ParentT: (PlatformRoot, UUID)]:
    """A fixed reader and parent scope, selected together by concrete construction."""

    def __init__(
        self,
        access: AccessPolicy,
        reader: CollectionReader[ItemT, ParentT],
        parent_kind: ScopeType,
        store: DescriptionStore,
        storage: RawStore,
    ) -> None:
        """Bind the fixed reader and parent discovery rule.

        Args:
            access: Current actor authority.
            reader: The concrete typed resource reader.
            parent_kind: The fixed owning resource scope.
            store: Committed ancestry and transaction capabilities.
            storage: Durable generation storage.
        """
        self._access = access
        self._reader: CollectionReader[ItemT, ParentT] = reader
        self._parent_kind = parent_kind
        self._kind = {
            ScopeType.SYSTEM: ScopeType.ORGANIZATION,
            ScopeType.ORGANIZATION: ScopeType.PROJECT,
            ScopeType.PROJECT: ScopeType.DATASET,
        }[parent_kind]
        self._store = store
        self._root = PurePosixPath(storage.root)
        self._generations = GenerationDocuments(storage)

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
            await self._access._resolve_scope(self._parent_kind, parent, visibility)
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
            await asyncify(self._generations.write)(directory, successor)
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

    def __init__(self, access: AccessPolicy, readers: DescriptionStore, storage: RawStore) -> None:
        """Bind organization reads to the platform parent.

        Args:
            access: Authenticated actor and current authorization facts.
            readers: Typed committed hierarchy readers and description transactions.
            storage: Durable generation storage.
        """
        super().__init__(access, readers.organizations, ScopeType.SYSTEM, readers, storage)


class ProjectCollection(_Collection[Project, UUID]):
    """Project discovery beneath an admitted organization."""

    def __init__(self, access: AccessPolicy, readers: DescriptionStore, storage: RawStore) -> None:
        """Bind project reads to organization discovery.

        Args:
            access: Authenticated actor and current authorization facts.
            readers: Typed committed hierarchy readers and description transactions.
            storage: Durable generation storage.
        """
        super().__init__(access, readers.projects, ScopeType.ORGANIZATION, readers, storage)


class DatasetCollection(_Collection[Dataset, UUID]):
    """Dataset discovery beneath an admitted project."""

    def __init__(self, access: AccessPolicy, readers: DescriptionStore, storage: RawStore) -> None:
        """Bind dataset reads to project discovery.

        Args:
            access: Authenticated actor and current authorization facts.
            readers: Typed committed hierarchy readers and description transactions.
            storage: Durable generation storage.
        """
        super().__init__(access, readers.datasets, ScopeType.PROJECT, readers, storage)
