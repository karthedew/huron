"""The schema registry: publishing, reading and resolving schema entries."""

from __future__ import annotations

from collections import OrderedDict
from typing import TYPE_CHECKING, Any

from huron.core.lake.audit import Action, AuditWriter, ObjectType
from huron.core.lake.lookups import find_organization, page_of
from huron.core.lake.schemas.errors import SchemaScope
from huron.core.lake.schemas.models import BASE_SCHEMA_NAME, SchemaEntry
from huron.core.security.rbac import PLATFORM, Authorizer, Privilege, Scope
from huron.pkg.errors import NotFound
from huron.pkg.identifiers import new_id
from huron.pkg.paging import InvalidCursor, Page, clamp_limit, decode_cursor, encode_cursor
from huron.schema.composition import SchemaIncompatible, compose, resolve_chain
from huron.schema.naming import check_segment
from huron.schema.validator import Problem, Validator, check_schema_document

if TYPE_CHECKING:
    import uuid

    from huron.core.lake.schemas.ports import SchemaStore
    from huron.core.lake.transaction import UnitOfWork
    from huron.core.security.rbac import Actor
    from huron.pkg.clock import Clock

__all__ = ["SchemaRegistry", "SchemaResolver"]

_CACHE_SIZE = 512


class SchemaResolver:
    """Resolves entries to composed documents; entries are immutable, so results are cached."""

    def __init__(self) -> None:
        self._cache: OrderedDict[uuid.UUID, dict[str, Any]] = OrderedDict()

    async def resolve(self, store: SchemaStore, schema_id: uuid.UUID) -> dict[str, Any]:
        """The composed document of ``schema_id`` and every entry it extends."""
        cached = self._cache.get(schema_id)
        if cached is not None:
            self._cache.move_to_end(schema_id)
            return cached
        chain: list[dict[str, Any]] = []
        current: uuid.UUID | None = schema_id
        while current is not None:
            entry = await store.get(current)
            if entry is None:
                raise NotFound("schema not found", {"schema": str(current)})
            chain.append(entry.document)
            current = entry.extends_id
        resolved = resolve_chain(list(reversed(chain)))
        self._cache[schema_id] = resolved
        if len(self._cache) > _CACHE_SIZE:
            self._cache.popitem(last=False)
        return resolved

    async def for_collection(
        self, store: SchemaStore, catalog_schema_id: uuid.UUID, override: dict[str, Any] | None
    ) -> dict[str, Any]:
        """The schema a collection validates against: the catalog's, composed with its override."""
        base = await self.resolve(store, catalog_schema_id)
        return base if override is None else compose(base, override)

    async def problems(
        self,
        store: SchemaStore,
        catalog_schema_id: uuid.UUID,
        override: dict[str, Any] | None,
        metadata: dict[str, Any],
    ) -> list[Problem]:
        """Validation problems of ``metadata`` against the collection's schema."""
        try:
            document = await self.for_collection(store, catalog_schema_id, override)
        except SchemaIncompatible as error:
            return [
                Problem(
                    "/", f"schema override is incompatible: {error.message}", "schema_incompatible"
                )
            ]
        return Validator(document).validate(metadata)


class SchemaRegistry:
    """Publishes and reads registry entries."""

    def __init__(self, uow: UnitOfWork, clock: Clock, resolver: SchemaResolver) -> None:
        self._uow = uow
        self._clock = clock
        self._resolver = resolver

    async def publish(
        self,
        actor: Actor,
        organization: str | None,
        name: str,
        extends_id: uuid.UUID | None,
        document: dict[str, Any],
    ) -> SchemaEntry:
        """Publish the next version of ``name`` in the organization (or platform when ``None``)."""
        if name != BASE_SCHEMA_NAME:
            check_segment(name)
        check_schema_document(document)
        async with self._uow.transaction() as tx:
            authz = Authorizer(tx.grants)
            organization_id: uuid.UUID | None = None
            if organization is None:
                await authz.require(actor, Privilege.PLATFORM_SCHEMA_PUBLISH, PLATFORM)
            else:
                found = await find_organization(tx, authz, actor, organization)
                await authz.require(actor, Privilege.SCHEMA_PUBLISH, Scope.organization(found.id))
                organization_id = found.id
            await self._check_parent(tx.schemas, organization_id, name, extends_id, document)
            latest = await tx.schemas.latest(organization_id, name)
            entry = SchemaEntry(
                id=new_id(),
                organization_id=organization_id,
                name=name,
                version=1 if latest is None else latest.version + 1,
                extends_id=extends_id,
                document=document,
                created_at=self._clock.now(),
                created_by=actor.subject,
            )
            await tx.schemas.insert(entry)
            await AuditWriter(tx.audit, self._clock).record(
                actor,
                Action.SCHEMA_PUBLISH,
                ObjectType.SCHEMA,
                entry.id,
                organization_id=organization_id,
                detail={"name": name, "version": entry.version},
            )
            return entry

    async def get(self, actor: Actor, schema_id: uuid.UUID) -> SchemaEntry:
        """An entry the actor may see: platform entries are public, others need the organization."""
        async with self._uow.transaction() as tx:
            entry = await tx.schemas.get(schema_id)
            authz = Authorizer(tx.grants)
            if entry is None or (
                entry.organization_id is not None
                and not await authz.can_see_organization(actor, entry.organization_id)
            ):
                raise NotFound("schema not found", {"schema": str(schema_id)})
            return entry

    async def resolved(self, actor: Actor, schema_id: uuid.UUID) -> dict[str, Any]:
        """The composed document of an entry the actor may see."""
        await self.get(actor, schema_id)
        async with self._uow.transaction() as tx:
            return await self._resolver.resolve(tx.schemas, schema_id)

    async def list(
        self, actor: Actor, organization: str | None, cursor: str | None, limit: int | None
    ) -> Page[SchemaEntry]:
        """Entries of one organization (or the platform), by name then newest version."""
        size = clamp_limit(limit)
        after = _schema_cursor(cursor)
        async with self._uow.transaction() as tx:
            organization_id = None
            if organization is not None:
                organization_id = (
                    await find_organization(tx, Authorizer(tx.grants), actor, organization)
                ).id
            rows = await tx.schemas.list(organization_id, after, size + 1)
        page = page_of(rows, size, lambda entry: entry.name)
        if page.next_cursor is not None:
            last = page.items[-1]
            page = Page(page.items, encode_cursor([last.name, last.version]))
        return page

    async def _check_parent(
        self,
        store: SchemaStore,
        organization_id: uuid.UUID | None,
        name: str,
        extends_id: uuid.UUID | None,
        document: dict[str, Any],
    ) -> None:
        if extends_id is None:
            if organization_id is None and name == BASE_SCHEMA_NAME:
                return
            raise SchemaIncompatible(
                f"every schema must extend {BASE_SCHEMA_NAME} or a schema that does",
                {"name": name},
            )
        parent = await store.get(extends_id)
        if parent is None:
            raise NotFound("parent schema not found", {"schema": str(extends_id)})
        if parent.organization_id not in (None, organization_id):
            raise SchemaScope(
                "a schema can only extend platform schemas or its own organization's",
                {"extends_id": str(extends_id)},
            )
        compose(await self._resolver.resolve(store, extends_id), document)


def _schema_cursor(cursor: str | None) -> tuple[str, int] | None:
    if cursor is None:
        return None
    values = decode_cursor(cursor)
    if len(values) != 2 or not isinstance(values[0], str) or not isinstance(values[1], int):
        raise InvalidCursor("cursor does not belong to this listing", {"cursor": cursor})
    return values[0], values[1]
