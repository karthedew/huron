"""Composite persistence contracts for the Raw lake."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from huron.core.foundation.retry import RetryTransaction
from huron.core.security.broker import RoleMappingReader, SigningKeyReader

if TYPE_CHECKING:
    from collections.abc import Sequence
    from contextlib import AbstractAsyncContextManager
    from uuid import UUID

    from huron.core.foundation.paging import Window
    from huron.core.lake.audit import AuditEntry
    from huron.core.lake.types import MetadataSchemaRecord, SchemaParts
    from huron.schema.catalog_config import SchemaRef


class AuditWriter(Protocol):
    """Appends audit entries in the transaction that makes their change.

    Entries become visible when that transaction commits and vanish if it rolls back.
    An operation appends after the write that locks the audited row, so one object's
    entry ids ascend in commit order.
    """

    async def append_audit(self, entries: Sequence[AuditEntry]) -> None:
        """Append entries, with ids ascending in call order.

        An empty sequence raises ValueError: an audited change always records an entry.

        Args:
            entries: Entries describing changes made in this transaction.
        """
        ...


class MetadataSchemaStore(Protocol):
    """Reads committed metadata schema versions."""

    async def by_ref(self, name: str, version: int) -> MetadataSchemaRecord | None:
        """Read one version by its series name and number.

        Args:
            name: The schema series.
            version: The version number.

        Returns:
            The published version, or None when none has that name and number.
        """
        ...

    async def by_id(self, schema_id: UUID) -> MetadataSchemaRecord | None:
        """Read one version by its id.

        Args:
            schema_id: The version's id.

        Returns:
            The published version, or None for an unknown id.
        """
        ...

    async def latest(self, name: str) -> MetadataSchemaRecord | None:
        """Read a series' highest version.

        Args:
            name: The schema series.

        Returns:
            The latest version, or None when the series has none.
        """
        ...

    async def schemas(
        self, after: tuple[str, int] | None, limit: int
    ) -> Window[MetadataSchemaRecord]:
        """Page every version in ascending `(name, version)` order, names in code-point order.

        Args:
            after: The last `(name, version)` key already seen, or None for the first page.
            limit: The most versions to return.

        Returns:
            The versions after the key, and whether more follow.
        """
        ...


class MetadataSchemaWriter(Protocol):
    """Inserts metadata schema versions in the transaction that audits them."""

    async def insert_schema(self, record: MetadataSchemaRecord) -> None:
        """Insert the next version of a series.

        The insert itself decides the version, so racing publishes neither collide
        nor leave a gap: a series whose latest version is at least this one raises
        SchemaVersionExists, and one whose latest is not exactly one lower raises
        SchemaInvalid with rule `version_gap`.

        Args:
            record: The new version.
        """
        ...


class SchemaResolver(Protocol):
    """Resolves a catalog config's schema reference to the parts that compose it."""

    async def resolve(self, ref: SchemaRef) -> SchemaParts | None:
        """Read the referenced version and the org base it builds on.

        Args:
            ref: The exact schema name and version.

        Returns:
            The base and extension, or None when no version has that reference.
        """
        ...


class LakeTransaction(AuditWriter, MetadataSchemaWriter, RetryTransaction, Protocol):
    """One open database transaction: every lake write, plus reads that see its own writes."""


class LakeStore(MetadataSchemaStore, RoleMappingReader, SigningKeyReader, Protocol):
    """The lake's persistence root, with atomic transactions and a readiness probe."""

    def transaction(self) -> AbstractAsyncContextManager[LakeTransaction]:
        """Open a transaction that commits on success and rolls back on failure.

        Returns:
            A context manager yielding one open transaction.
        """
        ...

    async def ping(self) -> None:
        """Probe whether persistence is available."""
        ...
