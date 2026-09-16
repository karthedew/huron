"""Catalog-owned hierarchy discovery, generation storage and mutation ports."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from huron.core.foundation.retry import RetryTransaction

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager
    from pathlib import Path, PurePosixPath
    from uuid import UUID

    from huron.core.security.rules import Visibility

    from .types import Dataset, Organization, PlatformRoot, Project, Window


class CollectionReader[ItemT, ParentT](Protocol):
    """Discoverable point reads and visibility-before-limit keyset windows."""

    async def get(self, resource_id: UUID, visibility: Visibility) -> ItemT:
        """Read an admitted resource; absent and hidden identities are indistinguishable.

        Args:
            resource_id: Resource identity.
            visibility: Discovery projection.

        Returns:
            The record, or raises ResourceNotFound.
        """
        ...

    async def browse(
        self,
        parent: ParentT,
        visibility: Visibility,
        *,
        limit: int,
        after: tuple[str, UUID] | None,
    ) -> Window[ItemT]:
        """Page visible children in C-collated slug and UUID order.

        Args:
            parent: Authorized parent or explicit platform root.
            visibility: Discovery projection, applied before limiting.
            limit: Maximum returned records.
            after: Exclusive cursor or None.

        Returns:
            The window, with has_more counting only visible records.
        """
        ...


class CatalogReaders(Protocol):
    """Typed readers for committed hierarchy records."""

    @property
    def organizations(self) -> CollectionReader[Organization, PlatformRoot]:
        """Return the organization reader."""
        ...

    @property
    def projects(self) -> CollectionReader[Project, UUID]:
        """Return the project reader."""
        ...

    @property
    def datasets(self) -> CollectionReader[Dataset, UUID]:
        """Return the dataset reader."""
        ...


class DescriptionWriter[ItemT](Protocol):
    """Compare-and-swap descriptive persistence within an open transaction."""

    async def describe(self, item: ItemT, *, expected_version: int) -> None:
        """Stage descriptive changes only when the stored version matches.

        Args:
            item: The descriptive successor.
            expected_version: Required current version; mismatch raises PreconditionFailed.
        """
        ...


class DescriptionTransaction(Protocol):
    """Typed description writers sharing a single atomic transaction."""

    @property
    def organizations(self) -> DescriptionWriter[Organization]:
        """Return the organization's CAS writer."""
        ...

    @property
    def projects(self) -> DescriptionWriter[Project]:
        """Return the project's CAS writer."""
        ...

    @property
    def datasets(self) -> DescriptionWriter[Dataset]:
        """Return the dataset's CAS writer."""
        ...


class DescriptionStore(CatalogReaders, Protocol):
    """Committed ancestry and atomic descriptive changes."""

    def transaction(self) -> AbstractAsyncContextManager[DescriptionTransaction]:
        """Open one transaction, committing only on clean exit.

        Returns:
            Writers sharing one connection or staged memory transaction.
        """
        ...


class CreationTransaction(RetryTransaction, Protocol):
    """Identity inserts and retry receipts committed in one transaction."""

    async def insert_organization(self, item: Organization) -> None:
        """Insert an organization, enforcing global slug uniqueness.

        Args:
            item: Fully formed organization.
        """
        ...

    async def insert_project(self, item: Project) -> None:
        """Insert a project, enforcing slug uniqueness within its organization.

        Args:
            item: Fully formed project.
        """
        ...

    async def insert_dataset(self, item: Dataset, *, data_classification: str) -> None:
        """Insert a dataset, enforcing slug uniqueness within its project.

        Args:
            item: Fully formed dataset.
            data_classification: Authoritative inherited project classification.
        """
        ...


class CreationStore(CatalogReaders, Protocol):
    """Committed ancestry and atomic identity creation."""

    def transaction(self) -> AbstractAsyncContextManager[CreationTransaction]:
        """Open one identity creation and retry transaction.

        Returns:
            A context whose mutation and receipt commit only on clean exit.
        """
        ...


class GenerationStorage(Protocol):
    """Durable hierarchy documents; no upload or revision mutation capability."""

    @property
    def root(self) -> Path:
        """Return the data root."""
        ...

    def write_generation(self, entity_dir: PurePosixPath, generation: int, payload: bytes) -> Path:
        """Durably write a numbered generation and replace CURRENT.json.

        Args:
            entity_dir: Hierarchy entity directory.
            generation: Generation from 1 through 999,999.
            payload: Complete canonical document bytes.

        Returns:
            The numbered document path.
        """
        ...
