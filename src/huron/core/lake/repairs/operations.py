"""Repair plans: the directories that a repair acts on, read from the rows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from huron.core.lake.collections.models import State
from huron.core.lake.lookups import find_catalog, find_organization, rendered_sidecar
from huron.core.lake.repairs.models import Level, PlannedDirectory, PlannedRow, RepairPlan
from huron.core.security.rbac import Authorizer, Privilege, Scope
from huron.pkg.errors import Conflict, Invalid, NotFound

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence

    from huron.core.lake.catalogs.models import Catalog
    from huron.core.lake.collections.models import Collection
    from huron.core.lake.namespaces.models import Namespace
    from huron.core.lake.transaction import Transaction, UnitOfWork
    from huron.core.security.rbac import Actor

__all__ = ["Repairs"]

_SETTLED = frozenset({State.ACTIVE, State.INCOMPLETE})

type _Segments = tuple[str, ...]


class Repairs:
    """Plan the repairs of catalogs and organizations. A repair reads rows and locks none."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def plan(self, actor: Actor, catalog: str, target: str, recursive: bool) -> RepairPlan:
        """The directories of a repair of ``target`` in ``catalog``; needs ``NAMESPACE_CONFIGURE``.

        ``target`` is the catalog's name, or the identifier of one of its namespaces or settled
        collections. The plan holds the directories from the catalog's down to the target's,
        and with ``recursive`` every namespace and settled collection below the target too,
        parents first. A target of another catalog is ``REQUEST_INVALID``, an unknown one
        ``NOT_FOUND`` and a draft ``STATE_CONFLICT``.
        """
        async with self._uow.transaction() as tx:
            authz = Authorizer(tx.grants)
            found = await find_catalog(tx, authz, actor, catalog)
            await authz.require(actor, Privilege.NAMESPACE_CONFIGURE, Scope.catalog(found.id))
            organization = await tx.organizations.get(found.organization_id)
            assert organization is not None
            tree = _Tree(organization.name, found, await tx.namespaces.list_in_catalog(found.id))
            top = await _target(tx, tree, target)
            directories = tree.ancestry(top)
            if recursive and top.level is not Level.COLLECTION:
                settled = await tx.collections.list_in_catalog(found.id, _SETTLED)
                directories += tree.descendants(top, settled)
            return RepairPlan(tuple(directories), found.share_group)

    async def organization(self, actor: Actor, name: str) -> RepairPlan:
        """The plan of the organization's own directory; needs ``CATALOG_GRANT_ADMIN`` on it."""
        async with self._uow.transaction() as tx:
            authz = Authorizer(tx.grants)
            found = await find_organization(tx, authz, actor, name)
            await authz.require(actor, Privilege.CATALOG_GRANT_ADMIN, Scope.organization(found.id))
            return RepairPlan((PlannedDirectory(found.name, Level.ORGANIZATION, found.id),))

    async def expected(self, directory: PlannedDirectory) -> PlannedRow | None:
        """The planned directory as its rows describe it now; ``None`` once its row is gone.

        A collection that became a draft again is gone too. It checks no privilege: the plan
        did.
        """
        async with self._uow.transaction() as tx:
            if directory.level is Level.COLLECTION:
                metadata = await rendered_sidecar(tx, directory.id)
                return None if metadata is None else PlannedRow(metadata)
            return PlannedRow() if await _row_exists(tx, directory) else None


@dataclass(frozen=True, slots=True)
class _Planned:
    """A planned directory by its segments below the catalog's directory."""

    segments: _Segments
    level: Level
    id: uuid.UUID


class _Tree:
    """A catalog's namespaces by their segments, and the API paths of its directories."""

    def __init__(
        self, organization: str, catalog: Catalog, namespaces: Sequence[Namespace]
    ) -> None:
        self._organization = organization
        self.catalog = catalog
        self.namespaces = {namespace.segments: namespace for namespace in namespaces}
        self._by_id = {namespace.id: namespace for namespace in namespaces}

    @property
    def root(self) -> _Planned:
        """The catalog's directory."""
        return _Planned((), Level.CATALOG, self.catalog.id)

    def ancestry(self, top: _Planned) -> list[PlannedDirectory]:
        """The directories from the catalog's down to ``top``, parents first."""
        planned = [self.root]
        if top.segments:
            sizes = range(1, len(top.segments))
            planned += [self.namespace(top.segments[:size]) for size in sizes]
            planned.append(top)
        return [self._directory(each) for each in planned]

    def namespace(self, segments: _Segments) -> _Planned:
        """The directory of the namespace at ``segments``."""
        return _Planned(segments, Level.NAMESPACE, self.namespaces[segments].id)

    def collection(self, collection: Collection) -> _Planned:
        """A settled collection's directory."""
        segments = (*self._by_id[collection.namespace_id].segments, collection.name)
        return _Planned(segments, Level.COLLECTION, collection.id)

    def descendants(self, top: _Planned, settled: Sequence[Collection]) -> list[PlannedDirectory]:
        """The namespaces and settled collections below ``top``, parents first."""
        candidates = [self.namespace(segments) for segments in self.namespaces]
        candidates += [self.collection(collection) for collection in settled]
        size = len(top.segments)
        inside = [
            c for c in candidates if len(c.segments) > size and c.segments[:size] == top.segments
        ]
        return [self._directory(c) for c in sorted(inside, key=lambda c: c.segments)]

    def _directory(self, planned: _Planned) -> PlannedDirectory:
        path = "/".join((self._organization, self.catalog.name, *planned.segments))
        return PlannedDirectory(path, planned.level, planned.id)


async def _target(tx: Transaction, tree: _Tree, target: str) -> _Planned:
    """The planned directory of ``target``: the catalog, a namespace or a settled collection."""
    catalog = tree.catalog.name
    if target == catalog:
        return tree.root
    if not target.startswith(f"{catalog}."):
        raise Invalid(f"{target} is not in the catalog {catalog}", {"target": target})
    segments = tuple(target.removeprefix(f"{catalog}.").split("."))
    if segments in tree.namespaces:
        return tree.namespace(segments)
    collection = await tx.collections.get_by_identifier(target)
    if collection is None or collection.catalog_id != tree.catalog.id:
        raise NotFound(
            f"{target} is not a namespace or a collection of the catalog {catalog}",
            {"target": target},
        )
    if not collection.settled:
        raise Conflict(
            f"{target} is a draft. A draft has no directory",
            {"state": str(collection.state), "allowed": ["active", "incomplete"]},
        )
    return tree.collection(collection)


async def _row_exists(tx: Transaction, directory: PlannedDirectory) -> bool:
    """Whether the organization, catalog or namespace row of ``directory`` is still there."""
    if directory.level is Level.ORGANIZATION:
        return await tx.organizations.get(directory.id) is not None
    if directory.level is Level.NAMESPACE:
        return await tx.namespaces.get(directory.id) is not None
    return await tx.catalogs.get(directory.id) is not None
