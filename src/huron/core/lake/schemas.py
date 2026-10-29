"""The metadata schema registry: publishing, reading and resolving immutable versions."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from huron.core.foundation.canonical import canonical_bytes, content_identity
from huron.core.foundation.errors import Forbidden, ResourceNotFound
from huron.core.foundation.identifiers import uuid7
from huron.core.foundation.retry import Replay
from huron.core.lake.audit import AuditEntry, SchemaPublished
from huron.core.lake.errors import SchemaInvalid
from huron.core.lake.types import MetadataSchemaRecord, SchemaParts, is_segment
from huron.core.security.broker import Role
from huron.schema.catalog_config import Problem, SchemaRef
from huron.schema.metadata import (
    BASE_SCHEMA_NAME,
    CompositionError,
    SchemaDocumentError,
    check_schema_document,
    compose,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping
    from uuid import UUID

    from huron.core.foundation.clock import Clock
    from huron.core.foundation.paging import Window
    from huron.core.foundation.retry import IdempotencyClaim
    from huron.core.lake.ports import LakeStore
    from huron.core.security.broker import Actor
    from huron.schema.metadata import JsonValue

MAX_DOCUMENT_BYTES: Final = 262_144
_DOCUMENT: Final = "/json_schema"


@dataclass(frozen=True, slots=True)
class Published:
    """A publish outcome: the stored version and whether this request created it."""

    record: MetadataSchemaRecord
    created: bool


class _RowCache:
    """The most recently read versions by id.

    Ids are UUIDv7 and never reused, and a version never changes, so an entry is
    never stale, even when the transaction that wrote its row rolled back.
    """

    def __init__(self, size: int) -> None:
        """Start empty.

        Args:
            size: The most versions held; 0 disables caching.
        """
        self._size = size
        self._rows: OrderedDict[UUID, MetadataSchemaRecord] = OrderedDict()

    def get(self, schema_id: UUID) -> MetadataSchemaRecord | None:
        """Return a cached version, marking it most recently used.

        Args:
            schema_id: The version's id.

        Returns:
            The cached version, or None when it is not held.
        """
        try:
            self._rows.move_to_end(schema_id)
        except KeyError:
            return None
        return self._rows[schema_id]

    def put(self, record: MetadataSchemaRecord) -> None:
        """Hold a version, evicting the least recently used one when full.

        Args:
            record: A version read by id.
        """
        self._rows[record.id] = record
        if len(self._rows) > self._size:
            self._rows.popitem(last=False)


def _request_problems(
    name: str, version: int, extends: SchemaRef | None, base: MetadataSchemaRecord | None
) -> Iterator[Problem]:
    """Check the request's name, version and extended base.

    Args:
        name: The schema series.
        version: The stated version.
        extends: The org base version the request extends, if any.
        base: The row `extends` names, if one exists.

    Yields:
        Each failure, pointing into the publish request.
    """
    if not is_segment(name):
        yield Problem("/name", "name", "expected a lowercase ASCII name of 1-64 characters")
    if type(version) is not int or version < 1:
        yield Problem("/version", "version", "expected a positive integer")
    if name == BASE_SCHEMA_NAME:
        if extends is not None:
            yield Problem("/extends", "extends", "the org base extends no schema")
    elif base is None or base.extends_id is not None:
        yield Problem("/extends", "extends", "an extension must extend a published org base")


def _document_problems(document: Mapping[str, JsonValue]) -> list[Problem]:
    """Check the document's canonical size and every document-level publication rule.

    Args:
        document: The submitted schema part.

    Returns:
        Each failure, pointing into the publish request.
    """
    problems = []
    try:
        size = len(canonical_bytes(document))
    except ValueError as error:
        problems.append(Problem(_DOCUMENT, "size", str(error)))
    else:
        if size > MAX_DOCUMENT_BYTES:
            problems.append(
                Problem(_DOCUMENT, "size", f"canonical document exceeds {MAX_DOCUMENT_BYTES} bytes")
            )
    try:
        check_schema_document(document)
    except SchemaDocumentError as error:
        problems.extend(Problem(_DOCUMENT + p.where, p.rule, p.message) for p in error.problems)
    return problems


def _composition_problems(
    name: str, version: int, base: MetadataSchemaRecord | None, document: Mapping[str, JsonValue]
) -> list[Problem]:
    """Check that a part meeting every document rule composes: a base alone, or with its base.

    Args:
        name: The schema series.
        version: The stated version.
        base: The extended org base, or None when the part is the org base.
        document: The submitted schema part.

    Returns:
        One `composition` failure when the part does not compose, otherwise none.
    """
    selected = SchemaRef(name, version)
    try:
        if base is None:
            compose(document, None, schema=selected, base_version=version)
        else:
            compose(base.document, (name, document), schema=selected, base_version=base.version)
    except CompositionError as error:
        return [Problem(_DOCUMENT, "composition", str(error))]
    return []


def _republishes(record: MetadataSchemaRecord, latest: MetadataSchemaRecord) -> bool:
    """Whether a new version repeats the latest one's number, document and base exactly.

    Args:
        record: The validated new version.
        latest: The series' latest published version.

    Returns:
        True when publishing the record would change nothing.
    """
    return (record.version, record.sha256, record.extends_id) == (
        latest.version,
        latest.sha256,
        latest.extends_id,
    )


def _published(record: MetadataSchemaRecord | None, described: str) -> MetadataSchemaRecord:
    """Require that a read found a version.

    Args:
        record: The read's result.
        described: How the request named the version.

    Returns:
        The version.

    Raises:
        ResourceNotFound: If the read found none.
    """
    if record is None:
        raise ResourceNotFound(f"metadata schema {described} is not published")
    return record


class MetadataSchemas:
    """Publishes, reads and resolves metadata schema versions.

    Publishing registers a version without adopting it: a catalog changes schema
    only by publishing a config that names the version.
    """

    def __init__(self, store: LakeStore, clock: Clock, *, row_cache: int = 256) -> None:
        """Bind the registry to its store and clock.

        Args:
            store: The lake persistence root.
            clock: The source of publication instants.
            row_cache: The most versions read by id to keep; 0 disables caching.
        """
        self._store = store
        self._clock = clock
        self._rows = _RowCache(row_cache)

    async def publish(
        self,
        actor: Actor,
        name: str,
        version: int,
        extends: SchemaRef | None,
        document: Mapping[str, JsonValue],
        *,
        claim: IdempotencyClaim,
    ) -> Published:
        """Publish the next version of a series, auditing it in the same transaction.

        Republishing the latest version's exact document and base is a no-op that
        answers that version, and a replay of an accepted request answers its version.
        The insert refuses a taken version with SchemaVersionExists and a skipped one
        with SchemaInvalid; reusing a retry key for another request raises
        IdempotencyKeyReused.

        Args:
            actor: The authenticated caller, who must be an Administrator.
            name: The schema series; `org` is the base series, which extends nothing.
            version: The stated version, which must follow the series' latest.
            extends: The org base version an extension builds on, or None for the base.
            document: The open JSON Schema part, stored as submitted.
            claim: The caller's idempotency claim for this request.

        Returns:
            The published version, and whether this request created it.

        Raises:
            Forbidden: If the actor is not an Administrator or the claim is another's.
            SchemaInvalid: If the request breaks a publication rule.
        """
        actor.grants.require(Role.ADMINISTRATOR)
        if claim.principal != actor.subject:
            raise Forbidden("An idempotency claim must belong to the authenticated actor")
        base = None if extends is None else await self._store.by_ref(extends.name, extends.version)
        problems = [*_request_problems(name, version, extends, base), *_document_problems(document)]
        if not problems:
            problems = _composition_problems(name, version, base, document)
        if problems:
            raise SchemaInvalid(problems)
        record = MetadataSchemaRecord(
            id=uuid7(),
            name=name,
            version=version,
            extends_id=None if base is None else base.id,
            document=document,
            sha256=content_identity(document),
            created_at=self._clock.now(),
            created_by=actor.subject,
        )
        return await self._insert(record, claim)

    async def _insert(self, record: MetadataSchemaRecord, claim: IdempotencyClaim) -> Published:
        """Insert a validated version with its audit entry and receipt, unless already done.

        Args:
            record: The validated new version.
            claim: The caller's idempotency claim for this request.

        Returns:
            The created version, a replayed request's version, or the identical latest.
        """
        async with self._store.transaction() as tx:
            replay = await tx.claim(claim)
            if replay is not None:
                return Published(await self._row(replay.resource_id), created=True)
            latest = await self._store.latest(record.name)
            if latest is not None and _republishes(record, latest):
                return Published(latest, created=False)
            await tx.insert_schema(record)
            event = SchemaPublished(
                schema=record.id,
                name=record.name,
                version=record.version,
                extends_id=record.extends_id,
            )
            await tx.append_audit([AuditEntry(record.created_at, record.created_by, event)])
            await tx.remember(claim, Replay("metadata_schema", record.id))
        return Published(record, created=True)

    async def get(self, actor: Actor, name: str, version: int) -> MetadataSchemaRecord:
        """Read one version; schemas are organization-wide and need no role.

        An unpublished name and number raises ResourceNotFound.

        Args:
            actor: The authenticated caller.
            name: The schema series.
            version: The version number.

        Returns:
            The published version.
        """
        return _published(await self._store.by_ref(name, version), f"{name} version {version}")

    async def list(
        self, actor: Actor, after: tuple[str, int] | None, limit: int
    ) -> Window[MetadataSchemaRecord]:
        """Page every version by `(name, version)`; schemas need no role.

        Args:
            actor: The authenticated caller.
            after: The last `(name, version)` key already seen, or None for the first page.
            limit: The most versions to return.

        Returns:
            The versions after the key, and whether more follow.
        """
        return await self._store.schemas(after, limit)

    async def resolve(self, ref: SchemaRef) -> SchemaParts | None:
        """Read a referenced version and the org base it builds on.

        The reference is read from the store every time: a name and number name
        a row only once it commits.

        Args:
            ref: The exact schema name and version.

        Returns:
            The base and extension, or None when no version has that reference.
        """
        record = await self._store.by_ref(ref.name, ref.version)
        return None if record is None else await self._parts(record)

    async def parts(self, schema_id: UUID) -> SchemaParts:
        """Read the parts of the version a stored catalog config selects.

        A stored config's version always exists; an unknown id raises ResourceNotFound.

        Args:
            schema_id: The selected version's id.

        Returns:
            The base and extension.
        """
        return await self._parts(await self._row(schema_id))

    async def _parts(self, record: MetadataSchemaRecord) -> SchemaParts:
        """Pair a version with its base, or a base with no extension.

        Args:
            record: The selected version.

        Returns:
            The base and extension.
        """
        if record.extends_id is None:
            return SchemaParts(record, None)
        return SchemaParts(await self._row(record.extends_id), record)

    async def _row(self, schema_id: UUID) -> MetadataSchemaRecord:
        """Read a version by id through the row cache; an unknown id raises ResourceNotFound.

        Args:
            schema_id: The version's id.

        Returns:
            The version.
        """
        if (cached := self._rows.get(schema_id)) is not None:
            return cached
        record = _published(await self._store.by_id(schema_id), str(schema_id))
        self._rows.put(record)
        return record
