"""Metadata schema versions: their table's constraints and in-memory store halves."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final

from huron.core.foundation.paging import Window
from huron.core.lake.errors import SchemaInvalid, SchemaVersionExists
from huron.core.lake.types import is_segment

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Hashable
    from uuid import UUID

    from huron.core.lake.types import MetadataSchemaRecord
    from huron.core.metastore.lake.memory import LakeBuffer, LakeTables, MetadataSchemaBuffer

_ORG_BASE: Final = "org"
_SHA256: Final = re.compile(r"[0-9a-f]{64}")


def metadata_schema_violation(
    record: MetadataSchemaRecord, visible: MetadataSchemaBuffer
) -> str | None:
    """Name the first `lake.metadata_schemas` constraint the record's row would violate.

    Args:
        record: The version about to be staged.
        visible: The versions the inserting transaction sees.

    Returns:
        The PostgreSQL constraint or trigger name, or None when the row is acceptable.
    """
    parent = visible.get(record.extends_id) if record.extends_id is not None else None
    holds = {
        "metadata_schemas_one_level": parent is None or parent.extends_id is None,
        "metadata_schemas_pkey": visible.get(record.id) is None,
        "metadata_schemas_name_check": is_segment(record.name),
        "metadata_schemas_sha256_check": bool(_SHA256.fullmatch(record.sha256)),
        "metadata_schemas_org_is_the_base": (record.extends_id is None)
        == (record.name == _ORG_BASE),
        "metadata_schemas_name_version_key": not visible.taken(record.name, record.version),
        "metadata_schemas_extends_id_fkey": record.extends_id is None or parent is not None,
    }
    return next((constraint for constraint, held in holds.items() if not held), None)


class InMemoryMetadataSchemas:
    """The committed metadata schema reads of the in-memory store root."""

    tables: LakeTables

    async def by_ref(self, name: str, version: int) -> MetadataSchemaRecord | None:
        """Read one committed version through the `(name, version)` key.

        Args:
            name: The schema series.
            version: The version number.

        Returns:
            The version, or None when none has that name and number.
        """
        schema_id = self.tables.metadata_schema_refs.get((name, version))
        return None if schema_id is None else self.tables.metadata_schemas[schema_id]

    async def by_id(self, schema_id: UUID) -> MetadataSchemaRecord | None:
        """Read one committed version by id.

        Args:
            schema_id: The version's id.

        Returns:
            The version, or None for an unknown id.
        """
        return self.tables.metadata_schemas.get(schema_id)

    async def latest(self, name: str) -> MetadataSchemaRecord | None:
        """Read a series' highest committed version.

        Args:
            name: The schema series.

        Returns:
            The latest version, or None when the series has none.
        """
        refs = self.tables.metadata_schema_refs
        versions = [version for series, version in refs if series == name]
        return await self.by_ref(name, max(versions)) if versions else None

    async def schemas(
        self, after: tuple[str, int] | None, limit: int
    ) -> Window[MetadataSchemaRecord]:
        """Page committed versions by `(name, version)`, names in code-point order.

        Args:
            after: The last key already seen, or None for the first page.
            limit: The most versions to return.

        Returns:
            The versions after the key, and whether more follow.
        """
        refs = self.tables.metadata_schema_refs
        keys = sorted(key for key in refs if after is None or key > after)
        return Window(
            [self.tables.metadata_schemas[refs[key]] for key in keys[:limit]],
            has_more=len(keys) > limit,
        )


class InMemoryMetadataSchemaWriter:
    """The metadata schema insert of an open in-memory transaction."""

    buffer: LakeBuffer
    lock: Callable[[Hashable], Awaitable[None]]

    async def insert_schema(self, record: MetadataSchemaRecord) -> None:
        """Stage the next version of a series, deciding taken and skipped versions first.

        The series stays locked until this transaction ends, so a racing insert of
        the same series waits and then decides against this one's outcome.

        Args:
            record: The new version.

        Raises:
            SchemaVersionExists: If the series' latest version is at least this one.
            SchemaInvalid: If the version does not directly follow the latest.
        """
        await self.lock(("metadata_schemas", record.name))
        latest = self.buffer.metadata_schemas.latest_version(record.name)
        if latest >= record.version:
            raise SchemaVersionExists(record.name, record.version, latest)
        if record.version != latest + 1:
            raise SchemaInvalid.version_gap(record.version, latest)
        self.buffer.metadata_schemas.insert(record)
