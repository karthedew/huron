"""Both implementations of the hierarchy port: in-memory now, Postgres alongside it.

``InMemoryHierarchyStore`` is the reference every other backend is compared
against - the transaction, uniqueness, optimistic-concurrency, idempotency
contracts are proven here first, in ``tests/hierarchy_contract.py``,
and ``PostgresHierarchyStore`` is held to the same scenarios against a
migrated database.
"""

from __future__ import annotations

import asyncio
import bisect
import json
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import chain
from typing import TYPE_CHECKING, Literal
from uuid import UUID

import asyncpg

from huron.core.foundation.clock import SystemClock
from huron.core.foundation.errors import (
    IdempotencyKeyReused,
    PreconditionFailed,
    ResourceNotFound,
)
from huron.core.foundation.paging import Window
from huron.core.foundation.retry import Replay
from huron.core.hierarchy.errors import SlugExists
from huron.core.hierarchy.types import Dataset, Organization, PlatformRoot, Project
from huron.core.security.rules import ProjectVisibility

from .queries import _DATASETS, _ORGANIZATIONS, _PROJECTS, _PostgresCollection
from .security_facts import SecurityFacts

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from huron.core.foundation.clock import Clock
    from huron.core.foundation.retry import IdempotencyClaim
    from huron.core.security.rules import Visibility

#: How long an idempotency claim stands before it may be taken over by a
#: fresh request reusing the same ``(principal, key)``.
_CLAIM_TTL = timedelta(hours=24)


@dataclass(slots=True)
class TransactionBuffer:
    """Everything staged by one open transaction, applied atomically or not at all.

    Attributes:
        organizations: Organizations to insert or replace, by id.
        projects: Projects to insert or replace, by id.
        datasets: Datasets to insert or replace, by id.
        idempotency: Idempotency records to insert or replace, by
            ``(principal, key)``.
    """

    organizations: dict[UUID, Organization] = field(default_factory=dict)
    projects: dict[UUID, Project] = field(default_factory=dict)
    datasets: dict[UUID, Dataset] = field(default_factory=dict)
    idempotency: dict[tuple[str, str], tuple[str, Replay | None, datetime]] = field(
        default_factory=dict
    )


class _TransactionWriter:
    """The write surface of one in-memory transaction, staged until commit.

    Every ``insert_*``/``update_*`` here writes into ``buffer``, never into
    the store's live dicts; ``InMemoryHierarchyStore.transaction`` applies
    the buffer once this writer's block exits without raising.
    """

    def __init__(self, store: InMemoryHierarchyStore, buffer: TransactionBuffer) -> None:
        """Bind the writer to the store it stages writes for and its buffer.

        Args:
            store: The store whose live dicts this writer checks
                uniqueness and versions against, and eventually writes to.
            buffer: Where every write this writer performs is staged.
        """
        self._store = store
        self._buffer = buffer
        self.organizations = _MemoryDescriptionWriter[Organization](
            store._organizations, buffer.organizations, "organization"
        )
        self.projects = _MemoryDescriptionWriter[Project](
            store._projects, buffer.projects, "project"
        )
        self.datasets = _MemoryDescriptionWriter[Dataset](
            store._datasets, buffer.datasets, "dataset"
        )

    async def claim(self, claim: IdempotencyClaim) -> Replay | None:
        """Stake this transaction's claim to a principal-scoped idempotency key.

        Args:
            claim: The principal, key and request digest to stake.

        Returns:
            The replay already remembered for an identical live claim, or
            ``None`` when the claim is now this transaction's to fulfil.

        Raises:
            IdempotencyKeyReused: If a live, unexpired claim for the same
                ``(principal, key)`` carries a different ``request_sha256``.
        """
        key = (claim.principal, claim.key)
        now = self._store._clock.now()
        entry = self._buffer.idempotency.get(key)
        if entry is None:
            entry = self._store._idempotency.get(key)
        if entry is not None:
            request_sha256, replay, expires_at = entry
            if expires_at > now:
                if request_sha256 == claim.request_sha256:
                    self._buffer.idempotency[key] = entry
                    return replay
                raise IdempotencyKeyReused(
                    f"idempotency key reused with a different request: {claim.key!r}"
                )
        self._buffer.idempotency[key] = (claim.request_sha256, None, now + _CLAIM_TTL)
        return None

    async def remember(self, claim: IdempotencyClaim, replay: Replay) -> None:
        """Record what this transaction's write produced, for a later replay of the same claim.

        Args:
            claim: The claim staked earlier in this transaction by
                ``claim``.
            replay: What the write produced, to return on a future replay
                of the same claim.
        """
        key = (claim.principal, claim.key)
        request_sha256, _, expires_at = self._buffer.idempotency[key]
        self._buffer.idempotency[key] = (request_sha256, replay, expires_at)

    async def insert_organization(self, item: Organization) -> None:
        """Insert one organization row.

        Args:
            item: The organization to insert, fully formed.

        Raises:
            SlugExists: If another organization, live or already staged in
                this transaction, has ``item.slug``.
        """
        if any(
            organization.slug == item.slug
            for organization in chain(
                self._store._organizations.values(),
                self._buffer.organizations.values(),
            )
        ):
            raise SlugExists(f"organization slug already exists: {item.slug!r}")
        self._buffer.organizations[item.id] = item

    async def insert_project(self, item: Project) -> None:
        """Insert one project row under its organization.

        Args:
            item: The project to insert, fully formed.

        Raises:
            SlugExists: If another project, live or already staged in this
                transaction, has ``item.slug`` under ``item.organization_id``.
        """
        if any(
            project.organization_id == item.organization_id and project.slug == item.slug
            for project in chain(
                self._store._projects.values(),
                self._buffer.projects.values(),
            )
        ):
            raise SlugExists(f"project slug already exists: {item.slug!r}")
        self._buffer.projects[item.id] = item

    async def insert_dataset(self, item: Dataset, *, data_classification: str) -> None:
        """Insert one dataset row under its project.

        ``data_classification`` is accepted for parity with the Postgres
        writer, which stores it as a column; the in-memory store keeps no
        record of it because nothing in the ``HierarchyStore`` port ever
        reads a dataset's own classification back - only a project's.

        Args:
            item: The dataset to insert, fully formed.
            data_classification: The classification code inherited from
                the owning project at creation time.

        Raises:
            SlugExists: If another dataset, live or already staged in this
                transaction, has ``item.slug`` under ``item.project_id``.
        """
        del data_classification
        if any(
            dataset.project_id == item.project_id and dataset.slug == item.slug
            for dataset in chain(
                self._store._datasets.values(),
                self._buffer.datasets.values(),
            )
        ):
            raise SlugExists(f"dataset slug already exists: {item.slug!r}")
        self._buffer.datasets[item.id] = item


class _MemoryDescriptionWriter[ItemT: (Organization, Project, Dataset)]:
    """Stage a fixed entity kind's CAS replacement in the enclosing transaction."""

    def __init__(self, live: dict[UUID, ItemT], staged: dict[UUID, ItemT], kind: str) -> None:
        """Bind committed and staged state for this entity kind.

        Args:
            live: The committed entities.
            staged: This transaction's pending replacements.
            kind: Fixed entity name for conflict errors.
        """
        self._live: dict[UUID, ItemT] = live
        self._staged: dict[UUID, ItemT] = staged
        self._kind = kind

    async def describe(self, item: ItemT, *, expected_version: int) -> None:
        """Stage the successor only when the committed version still matches.

        Args:
            item: The descriptive successor.
            expected_version: Required committed version.

        Raises:
            PreconditionFailed: If the entity is absent or its version is stale.
        """
        current = self._live.get(item.id)
        if current is None or current.version != expected_version:
            raise PreconditionFailed(f"{self._kind} version conflict: {item.id}")
        self._staged[item.id] = item


def _dataset_visible(dataset: Dataset, visibility: Visibility) -> bool:
    """Return whether a dataset is discoverable under ``visibility``.

    Args:
        dataset: The dataset to evaluate.
        visibility: The caller's discovery rights.

    Returns:
        True when ``visibility`` is unrestricted, names the dataset's
        project directly, or names the dataset itself.
    """
    return (
        visibility.unrestricted
        or dataset.project_id in visibility.project_ids
        or dataset.id in visibility.dataset_ids
    )


def _project_visible(
    project: Project, visibility: Visibility, datasets: dict[UUID, Dataset]
) -> bool:
    """Return whether a project is discoverable under ``visibility``.

    Args:
        project: The project to evaluate.
        visibility: The caller's discovery rights.
        datasets: Every dataset the store holds, searched for one that
            belongs to ``project`` and is itself visible.

    Returns:
        True when ``visibility`` is unrestricted, names the project
        directly, or admits at least one of its datasets.
    """
    if visibility.unrestricted or project.id in visibility.project_ids:
        return True
    return any(
        dataset.project_id == project.id and _dataset_visible(dataset, visibility)
        for dataset in datasets.values()
    )


def _organization_visible(
    organization_id: UUID,
    visibility: Visibility,
    projects: dict[UUID, Project],
    datasets: dict[UUID, Dataset],
) -> bool:
    """Return whether an organization is discoverable under ``visibility``.

    A dataset named directly by ``visibility.dataset_ids`` always makes its
    own project visible (``_project_visible`` checks for exactly that), so
    scanning this organization's projects for one that is visible already
    covers "the organization owns a directly-visible dataset" - no separate
    scan over datasets is needed here.

    Args:
        organization_id: The organization to evaluate.
        visibility: The caller's discovery rights.
        projects: Every project the store holds, searched for one that
            belongs to this organization and is itself visible.
        datasets: Every dataset the store holds, passed through to
            ``_project_visible``.

    Returns:
        True when ``visibility`` is unrestricted, names the organization
        directly, or admits at least one of its projects.
    """
    if visibility.unrestricted or organization_id in visibility.organization_ids:
        return True
    return any(
        project.organization_id == organization_id
        and _project_visible(project, visibility, datasets)
        for project in projects.values()
    )


def _window[ItemT](
    items: list[ItemT],
    *,
    key: Callable[[ItemT], tuple[object, ...]],
    limit: int,
    after: tuple[object, ...] | None,
) -> Window[ItemT]:
    """Slice one keyset page out of a sequence already sorted by ``key``.

    Args:
        items: Every visible item, already sorted ascending by ``key``.
        key: The cursor key each item is compared by.
        limit: The maximum number of items the page may hold.
        after: The key of the last item already seen, excluded from the
            page, or ``None`` to start from the beginning.

    Returns:
        At most ``limit`` items following ``after``, and whether at least
        one further item follows the last one returned.
    """
    start = 0 if after is None else bisect.bisect_right(items, after, key=key)
    page = items[start : start + limit + 1]
    return Window(items=page[:limit], has_more=len(page) > limit)


class _MemoryCollection[ItemT: (Organization, Project, Dataset), ParentT]:
    """Visible lookup and keyset paging over committed catalog dictionaries."""

    def __init__(
        self,
        items: dict[UUID, ItemT],
        visible: Callable[[ItemT, Visibility], bool],
        parent: Callable[[ItemT], ParentT],
        kind: str,
    ) -> None:
        """Bind fixed memory selection facts at adapter construction.

        Args:
            items: Live committed records, updated atomically by transactions.
            visible: This entity kind's fixed visibility predicate.
            parent: This entity kind's fixed parent projection.
            kind: The entity name used for not-found errors.
        """
        self._items: dict[UUID, ItemT] = items
        self._visible: Callable[[ItemT, Visibility], bool] = visible
        self._parent: Callable[[ItemT], ParentT] = parent
        self._kind = kind

    async def get(self, resource_id: UUID, visibility: Visibility) -> ItemT:
        """Resolve one visible committed entity.

        Args:
            resource_id: The exact entity identifier.
            visibility: The caller's discovery rights.

        Returns:
            The stored entity.

        Raises:
            ResourceNotFound: If the entity is absent or hidden.
        """
        item = self._items.get(resource_id)
        if item is None or not self._visible(item, visibility):
            raise ResourceNotFound(f"{self._kind} does not exist: {resource_id}")
        return item

    async def browse(
        self,
        parent: ParentT,
        visibility: Visibility,
        *,
        limit: int,
        after: tuple[str, UUID] | None,
    ) -> Window[ItemT]:
        """Filter visible children before sorting and slicing the keyset window.

        Args:
            parent: The owning identifier or platform root.
            visibility: The caller's discovery rights.
            limit: Maximum returned entities.
            after: Exclusive slug and UUID cursor.

        Returns:
            The typed visible window.
        """
        visible = sorted(
            (
                item
                for item in self._items.values()
                if self._parent(item) == parent and self._visible(item, visibility)
            ),
            key=lambda item: (item.slug, item.id),
        )
        return _window(visible, key=lambda item: (item.slug, item.id), limit=limit, after=after)


class InMemoryHierarchyStore(SecurityFacts):
    """The reference ``HierarchyStore``: dicts and lists held in process memory.

    Every write goes through :meth:`transaction`, which serializes on one
    ``asyncio.Lock`` and buffers its writes until the block exits cleanly;
    because the lock is held for the whole transaction, no reader ever
    observes a write mid-transaction and no second transaction can ever
    observe an idempotency claim whose ``remember`` has not yet run - the
    lock rules that case out rather than a check in :meth:`_TransactionWriter.claim`.
    Reads never take the lock: they are computed directly off the live
    dicts, which a transaction only ever replaces in one uninterrupted
    (``await``-free) step at commit.
    """

    def __init__(self, *, clock: Clock | None = None) -> None:
        """Start with an empty hierarchy and no idempotency records.

        Args:
            clock: The source of the current time, used for idempotency
                TTLs. Defaults to the system's UTC clock.
        """
        self._clock: Clock = clock if clock is not None else SystemClock()
        self._organizations: dict[UUID, Organization] = {}
        self._projects: dict[UUID, Project] = {}
        self._datasets: dict[UUID, Dataset] = {}
        self._idempotency: dict[tuple[str, str], tuple[str, Replay | None, datetime]] = {}
        self._lock = asyncio.Lock()
        self.organizations = _MemoryCollection[Organization, PlatformRoot](
            self._organizations,
            lambda item, visibility: _organization_visible(
                item.id, visibility, self._projects, self._datasets
            ),
            lambda item: PlatformRoot.ROOT,
            "organization",
        )
        self.projects = _MemoryCollection[Project, UUID](
            self._projects,
            lambda item, visibility: _project_visible(item, visibility, self._datasets),
            lambda item: item.organization_id,
            "project",
        )
        self.datasets = _MemoryCollection[Dataset, UUID](
            self._datasets, _dataset_visible, lambda item: item.project_id, "dataset"
        )

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[_TransactionWriter]:
        """Open one write transaction.

        Yields:
            A writer that stages every insert, update, claim and remember
            until this block exits.
        """
        async with self._lock:
            buffer = TransactionBuffer()
            yield _TransactionWriter(self, buffer)
            self._organizations.update(buffer.organizations)
            self._projects.update(buffer.projects)
            self._datasets.update(buffer.datasets)
            self._idempotency.update(buffer.idempotency)

    async def project_visibilities(self) -> list[ProjectVisibility]:
        """Return every project's identity, owning organization and classification.

        Returns:
            Every project, in no particular order.
        """
        return [
            ProjectVisibility(
                project_id=project.id,
                organization_id=project.organization_id,
                classification=project.data_classification,
            )
            for project in self._projects.values()
        ]

    async def dataset_parents(self, dataset_ids: frozenset[UUID]) -> dict[UUID, UUID]:
        """Return each requested dataset's owning project id.

        Args:
            dataset_ids: The datasets to resolve.

        Returns:
            A mapping from dataset id to project id, holding an entry for
            every id in ``dataset_ids`` that exists; an id that names no
            dataset is simply absent, not an error.
        """
        return {
            dataset.id: dataset.project_id
            for dataset in self._datasets.values()
            if dataset.id in dataset_ids
        }


#: Postgres's name for ``organizations``' slug UNIQUE constraint.
_ORGANIZATION_SLUG_CONSTRAINT = "organizations_slug_key"

#: Postgres's name for ``projects``' per-organization slug UNIQUE constraint.
_PROJECT_SLUG_CONSTRAINT = "projects_organization_id_slug_key"

#: Postgres's name for ``datasets``' per-project slug UNIQUE constraint.
_DATASET_SLUG_CONSTRAINT = "datasets_project_id_slug_key"


class _PostgresDescriptionWriter[ItemT: (Organization, Project, Dataset)]:
    """CAS descriptive fields using the enclosing transaction's held connection."""

    def __init__(
        self,
        connection: asyncpg.Connection,
        clock: Clock,
        kind: Literal["organization", "project", "dataset"],
    ) -> None:
        """Bind the fixed table selection and transaction connection.

        Args:
            connection: The existing atomic transaction connection.
            clock: The source of the persisted update timestamp.
            kind: The trusted entity kind fixed by writer construction.
        """
        self._connection = connection
        self._clock = clock
        self._kind = kind
        self._table = {
            "organization": "organizations",
            "project": "projects",
            "dataset": "datasets",
        }[kind]

    async def describe(self, item: ItemT, *, expected_version: int) -> None:
        """Persist a successor with an atomic version comparison.

        Args:
            item: The descriptive successor.
            expected_version: Required persisted version.

        Raises:
            PreconditionFailed: If no row matches the identifier and version.
        """
        row = await self._connection.fetchrow(
            f"""UPDATE {self._table}
            SET title = $2, description = $3, generation = $4, version = $5, updated_at = $6
            WHERE id = $1 AND version = $7 RETURNING id""",
            item.id,
            item.title,
            item.description,
            item.generation,
            item.version,
            self._clock.now(),
            expected_version,
        )
        if row is None:
            raise PreconditionFailed(f"{self._kind} version conflict: {item.id}")


class _PostgresTransactionWriter:
    """The write surface of one Postgres transaction, bound to the connection that opened it.

    Every statement here runs on ``connection``, inside the transaction
    :meth:`PostgresHierarchyStore.transaction` opened on it; nothing it
    writes is visible to a reader on another connection until that
    transaction commits.
    """

    def __init__(self, connection: asyncpg.Connection, clock: Clock) -> None:
        """Bind the writer to one open transaction and the clock that times it.

        Args:
            connection: The connection the enclosing transaction is open
                on; every statement this writer runs is issued on it.
            clock: The source of the current time, for an idempotency
                claim's ``created_at`` and an update's ``updated_at``.
        """
        self._connection = connection
        self._clock = clock
        self.organizations = _PostgresDescriptionWriter[Organization](
            connection, clock, "organization"
        )
        self.projects = _PostgresDescriptionWriter[Project](connection, clock, "project")
        self.datasets = _PostgresDescriptionWriter[Dataset](connection, clock, "dataset")

    async def claim(self, claim: IdempotencyClaim) -> Replay | None:
        """Stake this transaction's claim to a principal-scoped idempotency key.

        The claim is staked with an ``INSERT ... ON CONFLICT DO UPDATE``
        that only takes over a row whose ``expires_at`` has already
        passed. A live conflicting row is
        left untouched and read back to decide between a replay and a reuse.

        Args:
            claim: The principal, key and request digest to stake.

        Returns:
            The replay already remembered for an identical live claim, or
            ``None`` when the claim is now this transaction's to fulfil.

        Raises:
            IdempotencyKeyReused: If a live, unexpired claim for the same
                ``(principal, key)`` carries a different ``request_sha256``.
            RuntimeError: If the row this transaction just staked or found
                a conflict on vanishes before it can be read back -
                unreachable, since nothing in this design deletes an
                ``idempotency_records`` row.
        """
        now = self._clock.now()
        won = await self._connection.fetchrow(
            """
            INSERT INTO idempotency_records
                (principal, key, request_sha256, status_code, response, created_at, expires_at)
            VALUES ($1, $2, $3, 0, '{}'::jsonb, $4::timestamptz,
                    $4::timestamptz + interval '24 hours')
            ON CONFLICT (principal, key) DO UPDATE
                SET request_sha256 = EXCLUDED.request_sha256, status_code = 0,
                    response = '{}'::jsonb, created_at = EXCLUDED.created_at,
                    expires_at = EXCLUDED.expires_at
                WHERE idempotency_records.expires_at <= EXCLUDED.created_at
            RETURNING key
            """,
            claim.principal,
            claim.key,
            claim.request_sha256,
            now,
        )
        if won is not None:
            return None
        live = await self._connection.fetchrow(
            """
            SELECT request_sha256, response FROM idempotency_records
            WHERE principal = $1 AND key = $2
            FOR UPDATE
            """,
            claim.principal,
            claim.key,
        )
        if live is None:
            raise RuntimeError(
                f"idempotency claim vanished mid-transaction: "
                f"principal={claim.principal!r} key={claim.key!r}"
            )
        if live["request_sha256"] != claim.request_sha256:
            raise IdempotencyKeyReused(
                f"idempotency key reused with a different request: {claim.key!r}"
            )
        response = json.loads(live["response"])
        return Replay(kind=response["kind"], resource_id=UUID(response["id"]))

    async def remember(self, claim: IdempotencyClaim, replay: Replay) -> None:
        """Record what this transaction's write produced, for a later replay of the same claim.

        Args:
            claim: The claim staked earlier in this transaction by
                ``claim``.
            replay: What the write produced, to return on a future replay
                of the same claim.
        """
        await self._connection.execute(
            """
            UPDATE idempotency_records SET status_code = 201, response = $3::jsonb
            WHERE principal = $1 AND key = $2
            """,
            claim.principal,
            claim.key,
            json.dumps({"kind": replay.kind, "id": str(replay.resource_id)}),
        )

    async def insert_organization(self, item: Organization) -> None:
        """Insert one organization row.

        Args:
            item: The organization to insert, fully formed.

        Raises:
            SlugExists: If another organization already holds ``item.slug``.
            asyncpg.UniqueViolationError: If some other unique constraint
                refused the row - not expected against the current schema.
        """
        try:
            await self._connection.execute(
                """
                INSERT INTO organizations
                    (id, slug, title, description, lifecycle_state, generation, version,
                     created_at, updated_at)
                VALUES ($1, $2, $3, $4, 'ACTIVE', $5, $6, $7, $7)
                """,
                item.id,
                item.slug,
                item.title,
                item.description,
                item.generation,
                item.version,
                item.created_at,
            )
        except asyncpg.UniqueViolationError as exc:
            if getattr(exc, "constraint_name", None) != _ORGANIZATION_SLUG_CONSTRAINT:
                raise
            raise SlugExists(f"organization slug already exists: {item.slug!r}") from exc

    async def insert_project(self, item: Project) -> None:
        """Insert one project row under its organization.

        Args:
            item: The project to insert, fully formed.

        Raises:
            SlugExists: If another project already holds ``item.slug``
                under ``item.organization_id``.
            asyncpg.UniqueViolationError: If some other unique constraint
                refused the row - not expected against the current schema.
        """
        try:
            await self._connection.execute(
                """
                INSERT INTO projects
                    (id, organization_id, slug, title, description, classification_default,
                     lifecycle_state, generation, version, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, 'ACTIVE', $7, $8, $9, $9)
                """,
                item.id,
                item.organization_id,
                item.slug,
                item.title,
                item.description,
                item.data_classification,
                item.generation,
                item.version,
                item.created_at,
            )
        except asyncpg.UniqueViolationError as exc:
            if getattr(exc, "constraint_name", None) != _PROJECT_SLUG_CONSTRAINT:
                raise
            raise SlugExists(f"project slug already exists: {item.slug!r}") from exc

    async def insert_dataset(self, item: Dataset, *, data_classification: str) -> None:
        """Insert one dataset row under its project.

        Args:
            item: The dataset to insert, fully formed.
            data_classification: The classification code inherited from
                the owning project at creation time.

        Raises:
            SlugExists: If another dataset already holds ``item.slug``
                under ``item.project_id``.
            asyncpg.UniqueViolationError: If some other unique constraint
                refused the row - not expected against the current schema.
        """
        try:
            await self._connection.execute(
                """
                INSERT INTO datasets
                    (id, project_id, slug, title, description, profile_name, profile_version,
                     entry_layer, data_classification, lifecycle_state, generation, version,
                     created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $13)
                """,
                item.id,
                item.project_id,
                item.slug,
                item.title,
                item.description,
                item.profile_name,
                item.profile_version,
                item.entry_layer,
                data_classification,
                item.lifecycle_state,
                item.generation,
                item.version,
                item.created_at,
            )
        except asyncpg.UniqueViolationError as exc:
            if getattr(exc, "constraint_name", None) != _DATASET_SLUG_CONSTRAINT:
                raise
            raise SlugExists(f"dataset slug already exists: {item.slug!r}") from exc


class PostgresHierarchyStore(SecurityFacts):
    """Real storage for the hierarchy tables ``migrations/versions/0001_foundations.py`` creates.

    Every read applies its level's visibility predicate in SQL before any
    ``LIMIT``, so a page never counts a row the caller cannot see. A point
    read raises ``ResourceNotFound`` both when the id names nothing and
    when it names a row ``visibility`` does not admit; the two are
    indistinguishable to a caller with no grant on the resource, by
    design. Shares no state with the other Postgres stores beyond the pool
    itself; the clock is this store's own, used only for idempotency
    claim timestamps and update timestamps.
    """

    def __init__(self, pool: asyncpg.Pool, *, clock: Clock | None = None) -> None:
        """Bind the store to a connection pool.

        Args:
            pool: The pool every read acquires from directly; each write
                transaction acquires and holds its own connection for the
                life of its ``async with`` block. The store never closes
                the pool, its owner does.
            clock: The source of the current time, used for an
                idempotency claim's ``created_at`` and an update's
                ``updated_at``. Defaults to the system's UTC clock.
        """
        self._pool = pool
        self._clock: Clock = clock if clock is not None else SystemClock()
        self.organizations = _PostgresCollection[Organization, PlatformRoot](
            pool, _ORGANIZATIONS, None
        )
        self.projects = _PostgresCollection[Project, UUID](pool, _PROJECTS, "organization_id")
        self.datasets = _PostgresCollection[Dataset, UUID](pool, _DATASETS, "project_id")

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[_PostgresTransactionWriter]:
        """Open one write transaction on a connection held for its duration.

        Yields:
            A writer bound to the connection and transaction, so every
            statement it runs commits or rolls back together.
        """
        async with self._pool.acquire() as connection, connection.transaction():
            yield _PostgresTransactionWriter(connection, self._clock)

    async def project_visibilities(self) -> list[ProjectVisibility]:
        """Return every project's identity, owning organization and classification.

        Returns:
            Every project, in no particular order.
        """
        fetched = await self._pool.fetch(
            "SELECT id, organization_id, classification_default FROM projects"
        )
        return [
            ProjectVisibility(
                project_id=row["id"],
                organization_id=row["organization_id"],
                classification=row["classification_default"],
            )
            for row in fetched
        ]

    async def dataset_parents(self, dataset_ids: frozenset[UUID]) -> dict[UUID, UUID]:
        """Return each requested dataset's owning project id.

        Args:
            dataset_ids: The datasets to resolve.

        Returns:
            A mapping from dataset id to project id, holding an entry for
            every id in ``dataset_ids`` that exists; an id that names no
            dataset is simply absent, not an error.
        """
        fetched = await self._pool.fetch(
            "SELECT id, project_id FROM datasets WHERE id = ANY($1::uuid[])",
            list(dataset_ids),
        )
        return {row["id"]: row["project_id"] for row in fetched}
