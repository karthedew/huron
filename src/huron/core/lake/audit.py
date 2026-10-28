"""Typed, append-only facts about accepted lake changes."""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, ClassVar, Final
from uuid import UUID

from huron.core.security.broker import COMPANY_USERNAME, Role

if TYPE_CHECKING:
    from collections.abc import Mapping

    from huron.core.lake.types import CollectionState
    from huron.schema.metadata import FieldChange, JsonValue


class AuditAction(StrEnum):
    """The closed vocabulary of audited changes."""

    CREATE = "create"
    ACTIVATE = "activate"
    ADD = "add"
    OVERWRITE = "overwrite"
    RM = "rm"
    META_PUBLISH = "meta_publish"
    MV = "mv"
    DELETE = "delete"
    CATALOG_CONFIG = "catalog_config"
    SCHEMA_PUBLISH = "schema_publish"
    ROLE_MAP = "role_map"
    KEY_ROTATE = "key_rotate"
    KEY_WITHDRAW = "key_withdraw"


class AuditObject(StrEnum):
    """The kinds of objects retained in audit history."""

    COLLECTION = "collection"
    CATALOG = "catalog"
    METADATA_SCHEMA = "metadata_schema"
    LDAP_GROUP = "ldap_group"
    SIGNING_KEY = "signing_key"


SYSTEM_BOOTSTRAP: Final = "system:bootstrap"
AUDIT_REASON_MAX: Final = 1000


@dataclass(frozen=True, slots=True, kw_only=True)
class CollectionCreated:
    """A newly reserved draft collection and its catalog configuration."""

    ACTION: ClassVar = AuditAction.CREATE
    OBJECT: ClassVar = AuditObject.COLLECTION
    KEY: ClassVar = "collection"

    collection: UUID
    catalog: UUID
    version: int
    config_version: int


@dataclass(frozen=True, slots=True, kw_only=True)
class CollectionActivated:
    """A collection settled at its canonical identifier."""

    ACTION: ClassVar = AuditAction.ACTIVATE
    OBJECT: ClassVar = AuditObject.COLLECTION
    KEY: ClassVar = "collection"

    collection: UUID
    catalog: UUID
    version: int
    identifier: str


@dataclass(frozen=True, slots=True, kw_only=True)
class FileAdded:
    """A newly committed file and the commit that verified its bytes."""

    ACTION: ClassVar = AuditAction.ADD
    OBJECT: ClassVar = AuditObject.COLLECTION
    KEY: ClassVar = "collection"

    collection: UUID
    catalog: UUID
    version: int
    commit_id: UUID
    host: str
    rel_path: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True, kw_only=True)
class FileOverwritten:
    """A replacement file together with the displaced file provenance."""

    ACTION: ClassVar = AuditAction.OVERWRITE
    OBJECT: ClassVar = AuditObject.COLLECTION
    KEY: ClassVar = "collection"

    collection: UUID
    catalog: UUID
    version: int
    commit_id: UUID
    host: str
    rel_path: str
    size_bytes: int
    sha256: str
    old_size_bytes: int
    old_sha256: str
    old_uploaded_by: str
    old_uploaded_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class FileRemoved:
    """A removed file and the provenance needed to locate its retained bytes."""

    ACTION: ClassVar = AuditAction.RM
    OBJECT: ClassVar = AuditObject.COLLECTION
    KEY: ClassVar = "collection"

    collection: UUID
    catalog: UUID
    version: int
    commit_id: UUID
    host: str
    rel_path: str
    size_bytes: int
    sha256: str
    uploaded_by: str
    uploaded_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class MetadataPublished:
    """Published collection metadata and its non-empty field diff."""

    ACTION: ClassVar = AuditAction.META_PUBLISH
    OBJECT: ClassVar = AuditObject.COLLECTION
    KEY: ClassVar = "collection"

    collection: UUID
    catalog: UUID
    version: int
    changes: tuple[FieldChange, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class CollectionMoved:
    """A collection relocation and the metadata changes accompanying it."""

    ACTION: ClassVar = AuditAction.MV
    OBJECT: ClassVar = AuditObject.COLLECTION
    KEY: ClassVar = "collection"

    collection: UUID
    catalog: UUID
    version: int
    from_identifier: str
    to_identifier: str
    changes: tuple[FieldChange, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class CollectionDeleted:
    """The last state and placement of a deleted collection."""

    ACTION: ClassVar = AuditAction.DELETE
    OBJECT: ClassVar = AuditObject.COLLECTION
    KEY: ClassVar = "collection"

    collection: UUID
    catalog: UUID
    version: int
    state: CollectionState
    identifier: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class CatalogCreated:
    """A new catalog and its initial configuration version."""

    ACTION: ClassVar = AuditAction.CREATE
    OBJECT: ClassVar = AuditObject.CATALOG
    KEY: ClassVar = "catalog"

    catalog: UUID
    name: str
    config_version: int


@dataclass(frozen=True, slots=True, kw_only=True)
class CatalogConfigChanged:
    """A catalog configuration publication and its field diff."""

    ACTION: ClassVar = AuditAction.CATALOG_CONFIG
    OBJECT: ClassVar = AuditObject.CATALOG
    KEY: ClassVar = "catalog"

    catalog: UUID
    config_version: int
    changes: tuple[FieldChange, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class SchemaPublished:
    """A published schema version and its optional parent schema."""

    ACTION: ClassVar = AuditAction.SCHEMA_PUBLISH
    OBJECT: ClassVar = AuditObject.METADATA_SCHEMA
    KEY: ClassVar = "schema"

    schema: UUID
    name: str
    version: int
    extends_id: UUID | None


@dataclass(frozen=True, slots=True, kw_only=True)
class RoleMapped:
    """A directory group role transition in its catalog or organization scope."""

    ACTION: ClassVar = AuditAction.ROLE_MAP
    OBJECT: ClassVar = AuditObject.LDAP_GROUP
    KEY: ClassVar = "ldap_group"

    ldap_group: str
    catalog: UUID | None
    old_role: Role | None
    new_role: Role | None
    posix_gid: int

    def __post_init__(self) -> None:
        """Refuse a mapping event that records no change.

        Raises:
            ValueError: If the old and new roles are equal, including both absent.
        """
        if self.old_role == self.new_role:
            raise ValueError("A role mapping must change its role")


@dataclass(frozen=True, slots=True, kw_only=True)
class KeyRotated:
    """A signing key activation and the key it retires, if any."""

    ACTION: ClassVar = AuditAction.KEY_ROTATE
    OBJECT: ClassVar = AuditObject.SIGNING_KEY
    KEY: ClassVar = "kid"

    kid: str
    alg: str
    active_from: datetime
    retired_kid: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class KeyWithdrawn:
    """A withdrawn key and its intended signing start time."""

    ACTION: ClassVar = AuditAction.KEY_WITHDRAW
    OBJECT: ClassVar = AuditObject.SIGNING_KEY
    KEY: ClassVar = "kid"

    kid: str
    active_from: datetime


type AuditEvent = (
    CollectionCreated
    | CollectionActivated
    | FileAdded
    | FileOverwritten
    | FileRemoved
    | MetadataPublished
    | CollectionMoved
    | CollectionDeleted
    | CatalogCreated
    | CatalogConfigChanged
    | SchemaPublished
    | RoleMapped
    | KeyRotated
    | KeyWithdrawn
)

_EVENT_TYPES = (
    CollectionCreated,
    CollectionActivated,
    FileAdded,
    FileOverwritten,
    FileRemoved,
    MetadataPublished,
    CollectionMoved,
    CollectionDeleted,
    CatalogCreated,
    CatalogConfigChanged,
    SchemaPublished,
    RoleMapped,
    KeyRotated,
    KeyWithdrawn,
)

AUDIT_VOCABULARY: Final = frozenset((event.ACTION, event.OBJECT) for event in _EVENT_TYPES)


def _detail_value(value: object) -> JsonValue:
    """Encode the scalar and change-list types declared by audit events.

    Args:
        value: One declared event field.

    Returns:
        Its canonical JSON representation.

    Raises:
        TypeError: If a field has an unsupported runtime type.
    """
    if isinstance(value, Role):
        return value.code
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, tuple):
        return [change.as_json() for change in sorted(value, key=lambda change: change.pointer)]
    if value is None or isinstance(value, (str, int)):
        return value
    raise TypeError(f"Unsupported audit detail value: {type(value).__name__}")


@dataclass(frozen=True, slots=True)
class AuditEntry:
    """One actor's accepted change, ready for transactional persistence."""

    at: datetime
    actor: str
    event: AuditEvent
    reason: str | None = None

    def __post_init__(self) -> None:
        """Refuse invalid timestamps, actors, explanations and no-op changes.

        Raises:
            ValueError: If an entry violates the audit value contract.
        """
        if self.at.utcoffset() is None:
            raise ValueError("Audit time must be timezone-aware")
        if not (COMPANY_USERNAME.fullmatch(self.actor) or self.actor.startswith("system:")):
            raise ValueError("Audit actor must be a company username or system actor")
        if self.reason is not None and (
            not 1 <= len(self.reason) <= AUDIT_REASON_MAX or self.reason != self.reason.strip()
        ):
            raise ValueError("Audit reason must be stripped and contain 1..1000 characters")
        if getattr(self.event, "version", 1) < 1:
            raise ValueError("Audit version must be positive")
        if getattr(self.event, "changes", None) == ():
            raise ValueError("Audit changes must not be empty")

    @property
    def object_id(self) -> str:
        """The canonical identifier of the object described by this entry."""
        return str(getattr(self.event, self.event.KEY))

    @property
    def catalog_id(self) -> UUID | None:
        """The affected catalog, absent for organization-wide objects."""
        if isinstance(self.event, (SchemaPublished, KeyRotated, KeyWithdrawn)):
            return None
        return self.event.catalog

    def detail(self) -> dict[str, JsonValue]:
        """Encode every declared detail field, preserving explicit null values.

        Returns:
            The event's JSON object, with sorted field changes and UTC instants.
        """
        return {
            field.name: _detail_value(getattr(self.event, field.name))
            for field in fields(self.event)
            if field.name not in (self.event.KEY, "catalog")
        }


@dataclass(frozen=True, slots=True)
class AuditRecord:
    """A persisted audit entry with its store-assigned monotonic identifier."""

    id: int
    at: datetime
    actor: str
    action: AuditAction
    object_type: AuditObject
    object_id: str
    catalog_id: UUID | None
    detail: Mapping[str, JsonValue]
    reason: str | None
