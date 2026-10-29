"""The unit of work every lake operation runs in."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from huron.core.security.rbac.ports import GrantReader, GrantWriter

if TYPE_CHECKING:
    import uuid
    from contextlib import AbstractAsyncContextManager

    from huron.core.lake.audit.ports import AuditStore
    from huron.core.lake.catalogs.ports import CatalogStore
    from huron.core.lake.collections.ports import CollectionStore
    from huron.core.lake.files.ports import CommitStore, FileStore
    from huron.core.lake.namespaces.ports import NamespaceStore
    from huron.core.lake.organizations.ports import OrganizationStore
    from huron.core.lake.schemas.ports import SchemaStore
    from huron.core.security.broker.keys import KeyStore
    from huron.core.security.rbac.grants import Scope

__all__ = ["GrantStore", "Transaction", "UnitOfWork"]


class GrantStore(GrantReader, GrantWriter, Protocol):
    """Reads and writes grants."""

    async def delete_scope(self, scope: Scope) -> None:
        """Remove every grant at ``scope``."""
        ...


class Transaction(Protocol):
    """One database transaction: every area's store sharing one connection."""

    @property
    def organizations(self) -> OrganizationStore:
        """The organizations store."""
        ...

    @property
    def catalogs(self) -> CatalogStore:
        """The catalogs store."""
        ...

    @property
    def namespaces(self) -> NamespaceStore:
        """The namespaces store."""
        ...

    @property
    def collections(self) -> CollectionStore:
        """The collections store."""
        ...

    @property
    def files(self) -> FileStore:
        """The files store."""
        ...

    @property
    def commits(self) -> CommitStore:
        """The commits store."""
        ...

    @property
    def schemas(self) -> SchemaStore:
        """The schemas store."""
        ...

    @property
    def audit(self) -> AuditStore:
        """The audit store."""
        ...

    @property
    def grants(self) -> GrantStore:
        """The grants store."""
        ...

    @property
    def keys(self) -> KeyStore:
        """The keys store."""
        ...

    async def lock_catalog(self, catalog_id: uuid.UUID) -> None:
        """Serialize catalog-wide changes until the transaction ends."""
        ...


class UnitOfWork(Protocol):
    """Opens transactions; leaving the context commits, an exception rolls back."""

    def transaction(self) -> AbstractAsyncContextManager[Transaction]:
        """A new transaction."""
        ...
