"""Typed, append-only facts about accepted lake changes."""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, ClassVar, Final
from uuid import UUID

from huron.core.security.broker import COMPANY_USERNAME, Role

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

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
    """The kinds of objects whose history the audit log keeps."""

    COLLECTION = "collection"
    CATALOG = "catalog"
    METADATA_SCHEMA = "metadata_schema"
    LDAP_GROUP = "ldap_group"
    SIGNING_KEY = "signing_key"


SYSTEM_BOOTSTRAP: Final = "system:bootstrap"
AUDIT_REASON_MAX: Final = 1000
_SYSTEM_ACTOR_PREFIX: Final = "system:"


@dataclass(frozen=True, slots=True, kw_only=True)
class _CollectionEvent:
    """A change recorded in one collection's log, with the version it produced."""

    ACTION: ClassVar[AuditAction]
    OBJECT: ClassVar = AuditObject.COLLECTION
    KEY: ClassVar = "collection"

    collection: UUID
    catalog: UUID
    version: int


@dataclass(frozen=True, slots=True, kw_only=True)
class _FileEvent(_CollectionEvent):
    """A file change applied by one verified commit."""

    commit_id: UUID
    host: str
    rel_path: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True, kw_only=True)
class _SigningKeyEvent:
    """A signing-key lifecycle change, keyed by the key's identifier."""

    ACTION: ClassVar[AuditAction]
    OBJECT: ClassVar = AuditObject.SIGNING_KEY
    KEY: ClassVar = "kid"

    kid: str
    active_from: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class CollectionCreated(_CollectionEvent):
    """A draft collection reserved under the catalog configuration current at creation."""

    ACTION: ClassVar = AuditAction.CREATE

    config_version: int


@dataclass(frozen=True, slots=True, kw_only=True)
class CollectionActivated(_CollectionEvent):
    """A draft settled at its reserved identifier."""

    ACTION: ClassVar = AuditAction.ACTIVATE

    identifier: str


@dataclass(frozen=True, slots=True, kw_only=True)
class FileAdded(_FileEvent):
    """A newly committed file."""

    ACTION: ClassVar = AuditAction.ADD


@dataclass(frozen=True, slots=True, kw_only=True)
class FileOverwritten(_FileEvent):
    """A replaced file, with the provenance of the bytes it displaced."""

    ACTION: ClassVar = AuditAction.OVERWRITE

    old_size_bytes: int
    old_sha256: str
    old_uploaded_by: str
    old_uploaded_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class FileRemoved(_FileEvent):
    """A removed file, with the provenance needed to find its bytes in a snapshot."""

    ACTION: ClassVar = AuditAction.RM

    uploaded_by: str
    uploaded_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class MetadataPublished(_CollectionEvent):
    """Published collection metadata and its field diff."""

    ACTION: ClassVar = AuditAction.META_PUBLISH

    changes: tuple[FieldChange, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class CollectionMoved(_CollectionEvent):
    """A collection relocated within its catalog."""

    ACTION: ClassVar = AuditAction.MV

    from_identifier: str
    to_identifier: str


@dataclass(frozen=True, slots=True, kw_only=True)
class CollectionDeleted(_CollectionEvent):
    """The last state and identifier of a deleted collection."""

    ACTION: ClassVar = AuditAction.DELETE

    state: CollectionState
    identifier: str


@dataclass(frozen=True, slots=True, kw_only=True)
class CatalogCreated:
    """A new catalog and its first configuration version."""

    ACTION: ClassVar = AuditAction.CREATE
    OBJECT: ClassVar = AuditObject.CATALOG
    KEY: ClassVar = "catalog"

    catalog: UUID
    name: str
    config_version: int


@dataclass(frozen=True, slots=True, kw_only=True)
class CatalogConfigChanged:
    """A published catalog configuration version and its field diff."""

    ACTION: ClassVar = AuditAction.CATALOG_CONFIG
    OBJECT: ClassVar = AuditObject.CATALOG
    KEY: ClassVar = "catalog"

    catalog: UUID
    config_version: int
    changes: tuple[FieldChange, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class SchemaPublished:
    """A published metadata schema version and the base it extends, if any."""

    ACTION: ClassVar = AuditAction.SCHEMA_PUBLISH
    OBJECT: ClassVar = AuditObject.METADATA_SCHEMA
    KEY: ClassVar = "schema"

    schema: UUID
    name: str
    version: int
    extends_id: UUID | None


@dataclass(frozen=True, slots=True, kw_only=True)
class RoleMapped:
    """A directory group's role change on one catalog or across the organization."""

    ACTION: ClassVar = AuditAction.ROLE_MAP
    OBJECT: ClassVar = AuditObject.LDAP_GROUP
    KEY: ClassVar = "ldap_group"

    ldap_group: str
    catalog: UUID | None
    old_role: Role | None
    new_role: Role | None
    posix_gid: int

    def __post_init__(self) -> None:
        """Refuse a change that changes nothing or a role outside its scope.

        Raises:
            ValueError: If the roles are equal (both absent included), or a catalog role
                lacks a catalog, or the organization role names one.
        """
        if self.old_role == self.new_role:
            raise ValueError("A role mapping change must change the role")
        catalog_scope = self.catalog is not None
        for role in (self.old_role, self.new_role):
            if role is not None and role.catalog_scoped != catalog_scope:
                raise ValueError(f"Role {role.code} does not apply to this mapping scope")


@dataclass(frozen=True, slots=True, kw_only=True)
class KeyRotated(_SigningKeyEvent):
    """A key that became the signer, and the key it retired, if any."""

    ACTION: ClassVar = AuditAction.KEY_ROTATE

    alg: str
    retired_kid: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class KeyWithdrawn(_SigningKeyEvent):
    """A pending key withdrawn before the instant it would have started signing."""

    ACTION: ClassVar = AuditAction.KEY_WITHDRAW


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

AUDIT_VOCABULARY: Final = frozenset(
    (event.ACTION, event.OBJECT)
    for event in (
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
)


def _detail_value(value: object) -> JsonValue:
    """Encode one event field by the audit detail rules.

    Args:
        value: A declared event field.

    Returns:
        Role codes, canonical UUID strings, UTC instants, pointer-sorted field changes,
        or the value itself for strings, integers and null.

    Raises:
        TypeError: If the field holds a type the detail encoding does not define.
    """
    match value:
        case Role():
            return value.code
        case UUID():
            return str(value)
        case datetime():
            return value.astimezone(UTC).isoformat()
        case StrEnum():
            return value.value
        case tuple():
            return [change.as_json() for change in sorted(value, key=lambda c: c.pointer)]
        case str() | int() | None:
            return value
    raise TypeError(f"Audit detail cannot encode {type(value).__name__}")


@dataclass(frozen=True, slots=True)
class AuditEntry:
    """One actor's accepted change, ready to be appended in the transaction that made it."""

    at: datetime
    actor: str
    event: AuditEvent
    reason: str | None = None

    def __post_init__(self) -> None:
        """Refuse an entry that the audit log must never hold.

        Raises:
            ValueError: If `at` or an instant the event records is naive, the actor is
                neither a company username nor a system actor, the reason is blank,
                unstripped or too long, a version is below one, or a change list is empty.
        """
        if any(instant.utcoffset() is None for instant in self._instants()):
            raise ValueError("An audit instant must be timezone-aware")
        if not (
            COMPANY_USERNAME.fullmatch(self.actor) or self.actor.startswith(_SYSTEM_ACTOR_PREFIX)
        ):
            raise ValueError("An audit actor must be a company username or a system actor")
        if self.reason is not None and (
            not 1 <= len(self.reason) <= AUDIT_REASON_MAX or self.reason != self.reason.strip()
        ):
            raise ValueError(
                f"An audit reason must be stripped and 1 to {AUDIT_REASON_MAX} characters"
            )
        match self.event:
            case _CollectionEvent(version=version) | SchemaPublished(version=version) if (
                version < 1
            ):
                raise ValueError("An audited version must be at least 1")
            case MetadataPublished(changes=()) | CatalogConfigChanged(changes=()):
                raise ValueError("An audited change list must not be empty")

    def _instants(self) -> Iterator[datetime]:
        """Yield the entry's own instant, then every instant its event records.

        An append-only log cannot correct an instant later, so none may be left to
        the host's local time zone.

        Yields:
            Each instant the entry stores.
        """
        yield self.at
        for field in fields(self.event):
            value = getattr(self.event, field.name)
            if isinstance(value, datetime):
                yield value

    @property
    def object_id(self) -> str:
        """The described object's identifier, with UUIDs in canonical form."""
        return str(getattr(self.event, self.event.KEY))

    @property
    def catalog_id(self) -> UUID | None:
        """The catalog whose Readers may read this entry, or None for an organization entry."""
        if isinstance(self.event, SchemaPublished | _SigningKeyEvent):
            return None
        return self.event.catalog

    def detail(self) -> dict[str, JsonValue]:
        """Encode every event field except the object key and the catalog.

        Returns:
            The entry's `detail` object, with nullable values present as null.
        """
        return {
            field.name: _detail_value(getattr(self.event, field.name))
            for field in fields(self.event)
            if field.name not in {self.event.KEY, "catalog"}
        }


@dataclass(frozen=True, slots=True)
class AuditRecord:
    """A stored audit entry with its store-assigned, monotonically increasing id."""

    id: int
    at: datetime
    actor: str
    action: AuditAction
    object_type: AuditObject
    object_id: str
    catalog_id: UUID | None
    detail: Mapping[str, JsonValue]
    reason: str | None
