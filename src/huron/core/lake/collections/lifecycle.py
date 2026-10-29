"""Collection lifecycle: create, update, activate, read, search and delete."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

from huron.core.lake.audit import Action, AuditWriter, ObjectType
from huron.core.lake.collections.errors import (
    CollectionNotEmpty,
    CollectionsNotAllowed,
    MetadataInvalid,
)
from huron.core.lake.collections.metadata import check_metadata, merge_patch, render_sidecar
from huron.core.lake.collections.models import (
    Collection,
    CollectionView,
    Search,
    State,
    Unset,
    Update,
)
from huron.core.lake.lookups import (
    check_version,
    collection_view,
    cursor_value,
    find_catalog,
    find_collection,
    find_namespace,
    page_of,
)
from huron.core.security.rbac import Authorizer, Privilege, Scope
from huron.pkg.errors import Conflict, Forbidden
from huron.pkg.identifiers import new_id
from huron.pkg.paging import Page, clamp_limit
from huron.schema.naming import check_segment, parse_identifier
from huron.schema.validator import check_schema_document, problems_context

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence

    from huron.core.lake.catalogs.models import Catalog
    from huron.core.lake.schemas.registry import SchemaResolver
    from huron.core.lake.transaction import Transaction, UnitOfWork
    from huron.core.security.rbac import Actor
    from huron.pkg.clock import Clock
    from huron.schema.validator import Problem

__all__ = ["Collections"]

_SETTLED = frozenset({State.ACTIVE, State.INCOMPLETE})
_ALL = frozenset(State)


class Collections:
    """The collection aggregate's operations."""

    def __init__(self, uow: UnitOfWork, clock: Clock, resolver: SchemaResolver) -> None:
        self._uow = uow
        self._clock = clock
        self._resolver = resolver

    async def create(
        self,
        actor: Actor,
        catalog: str,
        namespace: str,
        name: str,
        metadata: dict[str, Any] | None = None,
    ) -> CollectionView:
        """Reserve a draft under a namespace that allows collections."""
        check_segment(name)
        identifier = f"{catalog}.{namespace}.{name}"
        parse_identifier(identifier)
        document = check_metadata({} if metadata is None else metadata)
        async with self._uow.transaction() as tx:
            authz = Authorizer(tx.grants)
            found = await find_catalog(tx, authz, actor, catalog)
            await authz.require(actor, Privilege.COLLECTION_CREATE, Scope.catalog(found.id))
            await tx.lock_catalog(found.id)
            parent = await find_namespace(tx, found, namespace)
            if not parent.collections_allowed:
                raise CollectionsNotAllowed(
                    f"{catalog}.{namespace} does not allow collections",
                    {"namespace": f"{catalog}.{namespace}"},
                )
            now = self._clock.now()
            collection = Collection(
                id=new_id(),
                catalog_id=found.id,
                namespace_id=parent.id,
                name=name,
                identifier=identifier,
                state=State.DRAFT,
                version=1,
                metadata=document,
                schema_override=None,
                file_count=0,
                created_at=now,
                created_by=actor.subject,
                updated_at=now,
            )
            await tx.collections.insert(collection)
            await self._audit(
                tx, actor, Action.COLLECTION_CREATE, collection, {"identifier": identifier}
            )
            problems = await self._problems(tx, found, collection)
            return await collection_view(tx, collection, found, _dicts(problems))

    async def get(
        self, actor: Actor, collection_id: uuid.UUID | None = None, identifier: str | None = None
    ) -> CollectionView:
        """A collection by id or identifier; drafts and incomplete ones carry their problems."""
        async with self._uow.transaction() as tx:
            collection, catalog = await self._readable(tx, actor, collection_id, identifier)
            problems: Sequence[Problem] = ()
            if collection.state is not State.ACTIVE:
                problems = await self._problems(tx, catalog, collection)
            return await collection_view(tx, collection, catalog, _dicts(problems))

    async def list(
        self,
        actor: Actor,
        catalog: str,
        namespace: str,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> Page[CollectionView]:
        """Collections directly in a namespace; drafts only for actors who may create them."""
        size = clamp_limit(limit)
        after = cursor_value(cursor)
        async with self._uow.transaction() as tx:
            authz = Authorizer(tx.grants)
            found = await find_catalog(tx, authz, actor, catalog)
            await authz.require(actor, Privilege.CATALOG_READ, Scope.catalog(found.id))
            parent = await find_namespace(tx, found, namespace)
            states = await self._visible_states(authz, actor, found)
            rows = await tx.collections.list_in_namespace(
                parent.id, states, None if after is None else str(after), size + 1
            )
            views = [await collection_view(tx, row, found) for row in rows]
        return page_of(views, size, lambda view: view.collection.name)

    async def search(
        self,
        actor: Actor,
        catalog: str,
        query: Search,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> Page[CollectionView]:
        """Collections of a catalog matching ``query``, sorted by identifier."""
        size = clamp_limit(limit)
        after = cursor_value(cursor)
        async with self._uow.transaction() as tx:
            authz = Authorizer(tx.grants)
            found = await find_catalog(tx, authz, actor, catalog)
            await authz.require(actor, Privilege.CATALOG_READ, Scope.catalog(found.id))
            allowed = await self._visible_states(authz, actor, found)
            narrowed = replace(query, states=frozenset(query.states) & allowed)
            rows = await tx.collections.search(
                found.id, narrowed, None if after is None else str(after), size + 1
            )
            views = [await collection_view(tx, row, found) for row in rows]
        return page_of(views, size, lambda view: view.collection.identifier)

    async def update(
        self, actor: Actor, collection_id: uuid.UUID, expected_version: int, update: Update
    ) -> CollectionView:
        """Patch metadata and/or set the schema override; both validate together."""
        async with self._uow.transaction() as tx:
            collection, catalog = await self._writable(
                tx, actor, collection_id, Privilege.COLLECTION_WRITE_METADATA
            )
            check_version(collection.version, expected_version)
            metadata = collection.metadata
            if not isinstance(update.metadata_patch, Unset):
                metadata = check_metadata(merge_patch(metadata, update.metadata_patch))
            override = collection.schema_override
            if not isinstance(update.schema_override, Unset):
                override = update.schema_override
                if override is not None:
                    check_schema_document(override)
                    await self._resolver.for_collection(tx.schemas, catalog.schema_id, override)
            candidate = replace(collection, metadata=metadata, schema_override=override)
            problems = await self._problems(tx, catalog, candidate)
            if collection.settled and problems:
                raise MetadataInvalid(
                    "metadata does not satisfy the schema", problems_context(problems)
                )
            updated = replace(
                candidate,
                state=State.ACTIVE if collection.settled else State.DRAFT,
                version=collection.version + 1,
                updated_at=self._clock.now(),
            )
            await tx.collections.update(updated)
            await self._audit_update(tx, actor, collection, updated)
            return await collection_view(tx, updated, catalog, _dicts(problems))

    async def activate(
        self, actor: Actor, collection_id: uuid.UUID, expected_version: int
    ) -> CollectionView:
        """Turn a valid draft into an active collection."""
        async with self._uow.transaction() as tx:
            collection, catalog = await self._writable(
                tx, actor, collection_id, Privilege.COLLECTION_WRITE_METADATA
            )
            if collection.state is not State.DRAFT:
                raise Conflict(
                    "only drafts can be activated",
                    {"state": str(collection.state), "allowed": ["draft"]},
                )
            check_version(collection.version, expected_version)
            problems = await self._problems(tx, catalog, collection)
            if problems:
                raise MetadataInvalid(
                    "metadata does not satisfy the schema", problems_context(problems)
                )
            now = self._clock.now()
            activated = replace(
                collection,
                state=State.ACTIVE,
                version=collection.version + 1,
                activated_at=now,
                updated_at=now,
            )
            await tx.collections.update(activated)
            await self._audit(
                tx, actor, Action.COLLECTION_ACTIVATE, activated, {"version": activated.version}
            )
            return await collection_view(tx, activated, catalog)

    async def delete(
        self,
        actor: Actor,
        collection_id: uuid.UUID,
        expected_version: int,
        dry_run: bool = False,
    ) -> None:
        """Delete a collection without recorded files; its creator or a catalog admin may.

        With ``dry_run`` nothing changes: only the caller's right and the version are checked, so
        the CLI can learn the delete will be refused before it removes any file.
        """
        async with self._uow.transaction() as tx:
            authz = Authorizer(tx.grants)
            collection, catalog = await find_collection(
                tx, authz, actor, collection_id=collection_id, lock=True
            )
            await self._require_delete(authz, actor, collection, catalog)
            check_version(collection.version, expected_version)
            if dry_run:
                return
            if collection.file_count:
                raise CollectionNotEmpty(
                    f"{collection.identifier} still has {collection.file_count} files",
                    {"file_count": collection.file_count},
                )
            await tx.collections.delete(collection.id)
            await self._audit(
                tx,
                actor,
                Action.COLLECTION_DELETE,
                collection,
                {"identifier": collection.identifier},
            )

    async def resolved_schema(self, actor: Actor, collection_id: uuid.UUID) -> dict[str, Any]:
        """The schema the collection's metadata validates against."""
        async with self._uow.transaction() as tx:
            collection, catalog = await self._readable(tx, actor, collection_id, None)
            return await self._resolver.for_collection(
                tx.schemas, catalog.schema_id, collection.schema_override
            )

    async def sidecar(self, actor: Actor, collection_id: uuid.UUID) -> bytes:
        """The canonical ``metadata.json`` of a settled collection."""
        view = await self.get(actor, collection_id)
        if not view.collection.settled:
            raise Conflict(
                "drafts have no metadata.json",
                {"state": str(view.collection.state), "allowed": ["active", "incomplete"]},
            )
        return render_sidecar(view)

    async def _readable(
        self,
        tx: Transaction,
        actor: Actor,
        collection_id: uuid.UUID | None,
        identifier: str | None,
    ) -> tuple[Collection, Catalog]:
        authz = Authorizer(tx.grants)
        collection, catalog = await find_collection(
            tx, authz, actor, collection_id=collection_id, identifier=identifier
        )
        await authz.require(actor, Privilege.COLLECTION_READ, Scope.catalog(catalog.id))
        return collection, catalog

    async def _writable(
        self, tx: Transaction, actor: Actor, collection_id: uuid.UUID, privilege: Privilege
    ) -> tuple[Collection, Catalog]:
        authz = Authorizer(tx.grants)
        collection, catalog = await find_collection(
            tx, authz, actor, collection_id=collection_id, lock=True
        )
        await authz.require(actor, privilege, Scope.catalog(catalog.id))
        return collection, catalog

    async def _require_delete(
        self, authz: Authorizer, actor: Actor, collection: Collection, catalog: Catalog
    ) -> None:
        scope = Scope.catalog(catalog.id)
        if await authz.holds(actor, Privilege.COLLECTION_DELETE_ANY, scope):
            return
        own = collection.created_by == actor.subject
        if own and await authz.holds(actor, Privilege.COLLECTION_DELETE_OWN, scope):
            return
        raise Forbidden(
            "only the collection's creator or a catalog admin may delete it",
            {"privilege": str(Privilege.COLLECTION_DELETE_ANY), "scope": "catalog"},
        )

    async def _visible_states(
        self, authz: Authorizer, actor: Actor, catalog: Catalog
    ) -> frozenset[State]:
        if await authz.holds(actor, Privilege.COLLECTION_CREATE, Scope.catalog(catalog.id)):
            return _ALL
        return _SETTLED

    async def _problems(
        self, tx: Transaction, catalog: Catalog, collection: Collection
    ) -> Sequence[Problem]:
        return await self._resolver.problems(
            tx.schemas, catalog.schema_id, collection.schema_override, collection.metadata
        )

    async def _audit_update(
        self, tx: Transaction, actor: Actor, before: Collection, after: Collection
    ) -> None:
        if before.metadata != after.metadata:
            await self._audit(
                tx, actor, Action.COLLECTION_UPDATE_METADATA, after, {"version": after.version}
            )
        if before.schema_override != after.schema_override:
            await self._audit(
                tx,
                actor,
                Action.COLLECTION_SET_SCHEMA_OVERRIDE,
                after,
                {"version": after.version, "cleared": after.schema_override is None},
            )
        if before.state is State.INCOMPLETE and after.state is State.ACTIVE:
            await self._audit(
                tx, actor, Action.COLLECTION_MARK_ACTIVE, after, {"version": after.version}
            )

    async def _audit(
        self,
        tx: Transaction,
        actor: Actor,
        action: Action,
        collection: Collection,
        detail: dict[str, Any],
    ) -> None:
        await AuditWriter(tx.audit, self._clock).record(
            actor,
            action,
            ObjectType.COLLECTION,
            collection.id,
            catalog_id=collection.catalog_id,
            detail=detail,
        )


def _dicts(problems: Sequence[Problem]) -> list[dict[str, str]]:
    return [problem.as_dict() for problem in problems]
