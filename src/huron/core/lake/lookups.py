"""Lookups every area shares: visible objects by name, version checks and paging."""

from __future__ import annotations

from typing import TYPE_CHECKING

from huron.core.lake.collections.models import Collection, CollectionView
from huron.core.lake.errors import VersionConflict
from huron.core.security.rbac import Privilege, Scope
from huron.pkg.errors import NotFound
from huron.pkg.paging import CursorValue, Page, decode_cursor, encode_cursor

if TYPE_CHECKING:
    import uuid
    from collections.abc import Callable, Sequence

    from huron.core.lake.catalogs.models import Catalog
    from huron.core.lake.namespaces.models import Namespace
    from huron.core.lake.organizations.models import Organization
    from huron.core.lake.transaction import Transaction
    from huron.core.security.rbac import Actor, Authorizer

__all__ = [
    "check_version",
    "collection_view",
    "cursor_value",
    "find_catalog",
    "find_collection",
    "find_namespace",
    "find_organization",
    "page_of",
]


async def find_organization(
    tx: Transaction, authz: Authorizer, actor: Actor, name: str
) -> Organization:
    """The organization named ``name`` if the actor may see it; otherwise :class:`NotFound`."""
    organization = await tx.organizations.get_by_name(name)
    if organization is None or not await authz.can_see_organization(actor, organization.id):
        raise NotFound(f"organization {name!r} not found", {"organization": name})
    return organization


async def find_catalog(tx: Transaction, authz: Authorizer, actor: Actor, name: str) -> Catalog:
    """The catalog named ``name`` if the actor may see it; otherwise :class:`NotFound`."""
    catalog = await tx.catalogs.get_by_name(name)
    if catalog is None or not await authz.can_see_catalog(actor, catalog.id):
        raise NotFound(f"catalog {name!r} not found", {"catalog": name})
    return catalog


async def find_namespace(tx: Transaction, catalog: Catalog, path: str) -> Namespace:
    """The namespace at ``path`` in ``catalog``; otherwise :class:`NotFound`."""
    namespace = await tx.namespaces.get_by_path(catalog.id, path)
    if namespace is None:
        raise NotFound(
            f"namespace {catalog.name}.{path} not found", {"namespace": f"{catalog.name}.{path}"}
        )
    return namespace


async def find_collection(
    tx: Transaction,
    authz: Authorizer,
    actor: Actor,
    *,
    collection_id: uuid.UUID | None = None,
    identifier: str | None = None,
    lock: bool = False,
) -> tuple[Collection, Catalog]:
    """A collection the actor may see, by id or identifier; drafts need ``COLLECTION_CREATE``."""
    found = await _load_collection(tx, collection_id, identifier, lock)
    missing = NotFound("collection not found", {"collection": str(collection_id or identifier)})
    if found is None:
        raise missing
    catalog = await tx.catalogs.get(found.catalog_id)
    if catalog is None or not await authz.can_see_catalog(actor, catalog.id):
        raise missing
    if not found.settled and not await authz.holds(
        actor, Privilege.COLLECTION_CREATE, Scope.catalog(catalog.id)
    ):
        raise missing
    return found, catalog


async def collection_view(
    tx: Transaction,
    collection: Collection,
    catalog: Catalog,
    problems: Sequence[dict[str, str]] = (),
) -> CollectionView:
    """Assemble the API view of a collection."""
    organization = await tx.organizations.get(catalog.organization_id)
    namespace = await tx.namespaces.get(collection.namespace_id)
    schema = await tx.schemas.get(catalog.schema_id)
    assert organization is not None and namespace is not None and schema is not None
    return CollectionView(
        collection=collection,
        organization=organization.name,
        catalog=catalog.name,
        namespace_path=namespace.path,
        schema=schema.ref,
        problems=list(problems),
    )


def check_version(current: int, expected: int) -> None:
    """Raise :class:`VersionConflict` unless ``expected`` is ``current``."""
    if current != expected:
        raise VersionConflict(current)


def cursor_value(cursor: str | None) -> CursorValue:
    """The single sort-key value carried by ``cursor``, or ``None`` without one."""
    if cursor is None:
        return None
    values = decode_cursor(cursor)
    return values[0] if values else None


def page_of[T](rows: Sequence[T], limit: int, key: Callable[[T], CursorValue]) -> Page[T]:
    """Turn ``limit + 1`` fetched rows into a page and its next cursor."""
    if len(rows) <= limit:
        return Page(tuple(rows), None)
    items = tuple(rows[:limit])
    return Page(items, encode_cursor([key(items[-1])]))


async def _load_collection(
    tx: Transaction, collection_id: uuid.UUID | None, identifier: str | None, lock: bool
) -> Collection | None:
    if collection_id is None:
        found = await tx.collections.get_by_identifier(str(identifier))
        if found is None or not lock:
            return found
        collection_id = found.id
    return await (tx.collections.lock if lock else tx.collections.get)(collection_id)
