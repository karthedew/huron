"""Lake values shared by operations and persistence.

Persistence adapters reach the shared naming rules only through this module.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from huron.schema.catalog_config import SchemaRef
from huron.schema.naming import NamingError, check_segment

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime
    from uuid import UUID

    from huron.schema.metadata import JsonValue


def is_segment(value: str) -> bool:
    """Whether a value is a strict catalog, namespace, collection or schema name.

    Args:
        value: The candidate name.

    Returns:
        True when the name satisfies the shared segment rule unchanged.
    """
    try:
        check_segment(value)
    except NamingError:
        return False
    return True


class CollectionState(StrEnum):
    """A collection's draft or settled lifecycle state."""

    DRAFT = "draft"
    ACTIVE = "active"
    INCOMPLETE = "incomplete"

    @property
    def settled(self) -> bool:
        """Whether the collection has left its draft state."""
        return self is not CollectionState.DRAFT


@dataclass(frozen=True, slots=True, kw_only=True)
class MetadataSchemaRecord:
    """One published, immutable metadata schema version.

    The org base series extends nothing; every other series extends one org base row
    by id. The record owns a private copy of the submitted document.
    """

    id: UUID
    name: str
    version: int
    extends_id: UUID | None
    document: Mapping[str, JsonValue]
    sha256: str
    created_at: datetime
    created_by: str

    def __post_init__(self) -> None:
        """Own the document so a later change to the submitted value cannot alter the row."""
        object.__setattr__(self, "document", deepcopy(dict(self.document)))

    @property
    def ref(self) -> SchemaRef:
        """The exact reference a catalog config uses to select this version."""
        return SchemaRef(self.name, self.version)


@dataclass(frozen=True, slots=True)
class SchemaParts:
    """An org base and, unless the base itself is selected, the extension built on it."""

    base: MetadataSchemaRecord
    extension: MetadataSchemaRecord | None

    def __post_init__(self) -> None:
        """Refuse parts that do not form one base and its own extension.

        Raises:
            ValueError: If the base extends a schema or the extension extends another row.
        """
        if self.base.extends_id is not None:
            raise ValueError("A schema base must extend nothing")
        if self.extension is not None and self.extension.extends_id != self.base.id:
            raise ValueError("A schema extension must extend the base it is paired with")

    @property
    def referenced(self) -> MetadataSchemaRecord:
        """The version a catalog config selects: the extension, or the base selected alone."""
        return self.extension if self.extension is not None else self.base
