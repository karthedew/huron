"""Both implementations of the hierarchy port: in-memory now, Postgres alongside it.

``InMemoryHierarchyStore`` is the reference every other backend is compared
against - the transaction, uniqueness, optimistic-concurrency, idempotency
and revision contracts are proven here first, in ``tests/hierarchy_contract.py``,
and ``PostgresHierarchyStore`` is held to the same scenarios against a
migrated database.
"""

from __future__ import annotations

import asyncio
import bisect
import json
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from itertools import chain
from typing import TYPE_CHECKING
from uuid import UUID

import asyncpg

from huron.pkg.catalog.errors import (
    DuplicateContent,
    IdempotencyKeyReused,
    PreconditionFailed,
    ResourceNotFound,
    TagExists,
)
from huron.pkg.catalog.models import RevisionRef
from huron.pkg.rbac import ProjectVisibility
from huron.service.api.errors import SlugExists

from . import rows
from .ingest import (
    InMemoryIngestReader,
    InMemoryIngestWriter,
    PostgresIngestReader,
    PostgresIngestWriter,
    latest_revision,
)
from .ports import Replay, Window

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Iterable

    from huron.pkg.catalog.ingest import IngestSession
    from huron.pkg.catalog.models import OutboxEvent, RevisionRecord
    from huron.pkg.catalog.ports import Clock
    from huron.pkg.rbac import Visibility
    from huron.service.api.records import AuditEvent, Dataset, Organization, Project, Release

    from .ports import HierarchyWriter, IdempotencyClaim, LedgerEntry

#: How long an idempotency claim stands before it may be taken over by a
#: fresh request reusing the same ``(principal, key)``.
_CLAIM_TTL = timedelta(hours=24)


class SystemClock:
    """The default clock: the operating system's UTC time."""

    def now(self) -> datetime:
        """Return the current instant.

        Returns:
            The current time, timezone-aware in UTC.
        """
        return datetime.now(UTC)


def _find_revision(
    revisions: Iterable[RevisionRecord], dataset_id: UUID, number: int
) -> RevisionRecord | None:
    """Return the revision at ``(dataset_id, number)`` among ``revisions``, or None.

    Args:
        revisions: The revisions to search, live rows and staged ones alike.
        dataset_id: The dataset the wanted revision belongs to.
        number: The revision's 1-based position within that dataset.

    Returns:
        The matching revision, or None if none of ``revisions`` matches.
    """
    for revision in revisions:
        if revision.dataset_id == dataset_id and revision.number == number:
            return revision
    return None


@dataclass(slots=True)
class TransactionBuffer:
    """Everything staged by one open transaction, applied atomically or not at all.

    Attributes:
        organizations: Organizations to insert or replace, by id.
        projects: Projects to insert or replace, by id.
        datasets: Datasets to insert or replace, by id.
        releases: Releases to insert, by ``(dataset_id, tag)``.
        revisions: Revisions to insert, by id.
        sessions: Ingest sessions to insert or replace, by id.
        files: Ingest ledger entries to insert or replace, by file id.
        audit: Audit rows to append, in call order.
        outbox: Outbox rows to append, in call order.
        idempotency: Idempotency records to insert or replace, by
            ``(principal, key)``.
    """

    organizations: dict[UUID, Organization] = field(default_factory=dict)
    projects: dict[UUID, Project] = field(default_factory=dict)
    datasets: dict[UUID, Dataset] = field(default_factory=dict)
    releases: dict[tuple[UUID, str], Release] = field(default_factory=dict)
    revisions: dict[UUID, RevisionRecord] = field(default_factory=dict)
    sessions: dict[UUID, IngestSession] = field(default_factory=dict)
    files: dict[UUID, LedgerEntry] = field(default_factory=dict)
    audit: list[AuditEvent] = field(default_factory=list)
    outbox: list[OutboxEvent] = field(default_factory=list)
    idempotency: dict[tuple[str, str], tuple[str, Replay | None, datetime]] = field(
        default_factory=dict
    )


class _TransactionWriter(InMemoryIngestWriter):
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

    async def insert_release(self, item: Release) -> None:
        """Insert one release row, tagging a dataset revision.

        Args:
            item: The release to insert, fully formed.

        Raises:
            TagExists: If another release, live or already staged in this
                transaction, has ``item.tag`` under ``item.dataset_id``.
            ResourceNotFound: If ``(item.dataset_id, item.revision_number)``
                names no registered revision.
        """
        key = (item.dataset_id, item.tag)
        if key in self._store._releases or key in self._buffer.releases:
            raise TagExists(f"release tag already exists: {item.tag!r}")
        found = _find_revision(
            chain(self._store._revisions.values(), self._buffer.revisions.values()),
            item.dataset_id,
            item.revision_number,
        )
        if found is None:
            raise ResourceNotFound(
                f"revision does not exist: dataset={item.dataset_id} number={item.revision_number}"
            )
        self._buffer.releases[key] = item

    async def insert_revision(self, record: RevisionRecord) -> None:
        """Insert the row a COMMITTING session publishes when its commit lands.

        Args:
            record: The revision to insert, fully formed.

        Raises:
            DuplicateContent: If the dataset, live or already staged in
                this transaction, already holds a revision with
                ``record.manifest_sha256``.
        """
        duplicate = any(
            revision.dataset_id == record.dataset_id
            and revision.manifest_sha256 == record.manifest_sha256
            for revision in chain(self._store._revisions.values(), self._buffer.revisions.values())
        )
        if duplicate:
            raise DuplicateContent(
                f"dataset already holds this manifest: dataset={record.dataset_id} "
                f"manifest_sha256={record.manifest_sha256}"
            )
        self._buffer.revisions[record.id] = record

    async def insert_audit_event(self, event: AuditEvent) -> None:
        """Append one audit row.

        Args:
            event: The audit row to append, fully formed.
        """
        self._buffer.audit.append(event)

    async def insert_outbox_event(self, event: OutboxEvent) -> None:
        """Append one outbox row, unprocessed.

        Args:
            event: The event to append, fully formed.
        """
        self._buffer.outbox.append(event)

    async def update_organization(self, item: Organization, *, expected_version: int) -> None:
        """Apply an update to one organization, guarded by optimistic concurrency.

        Args:
            item: The organization as it should read after the update.
            expected_version: The version the caller last read; the update
                is refused unless this still matches what is stored.

        Raises:
            PreconditionFailed: If no live organization has ``item.id``, or
                its stored version is not ``expected_version``.
        """
        current = self._store._organizations.get(item.id)
        if current is None or current.version != expected_version:
            raise PreconditionFailed(f"organization version conflict: {item.id}")
        self._buffer.organizations[item.id] = item

    async def update_project(self, item: Project, *, expected_version: int) -> None:
        """Apply an update to one project, guarded by optimistic concurrency.

        Args:
            item: The project as it should read after the update.
            expected_version: The version the caller last read; the update
                is refused unless this still matches what is stored.

        Raises:
            PreconditionFailed: If no live project has ``item.id``, or its
                stored version is not ``expected_version``.
        """
        current = self._store._projects.get(item.id)
        if current is None or current.version != expected_version:
            raise PreconditionFailed(f"project version conflict: {item.id}")
        self._buffer.projects[item.id] = item

    async def update_dataset(self, item: Dataset, *, expected_version: int) -> None:
        """Apply an update to one dataset, guarded by optimistic concurrency.

        Args:
            item: The dataset as it should read after the update.
            expected_version: The version the caller last read; the update
                is refused unless this still matches what is stored.

        Raises:
            PreconditionFailed: If no live dataset has ``item.id``, or its
                stored version is not ``expected_version``.
        """
        current = self._store._datasets.get(item.id)
        if current is None or current.version != expected_version:
            raise PreconditionFailed(f"dataset version conflict: {item.id}")
        self._buffer.datasets[item.id] = item


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


class InMemoryHierarchyStore(InMemoryIngestReader):
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
        self._releases: dict[tuple[UUID, str], Release] = {}
        self._revisions: dict[UUID, RevisionRecord] = {}
        self._sessions: dict[UUID, IngestSession] = {}
        self._files: dict[UUID, LedgerEntry] = {}
        self._audit: list[AuditEvent] = []
        self._outbox: list[OutboxEvent] = []
        self._idempotency: dict[tuple[str, str], tuple[str, Replay | None, datetime]] = {}
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[HierarchyWriter]:
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
            self._releases.update(buffer.releases)
            self._revisions.update(buffer.revisions)
            self._sessions.update(buffer.sessions)
            self._files.update(buffer.files)
            self._audit.extend(buffer.audit)
            self._outbox.extend(buffer.outbox)
            self._idempotency.update(buffer.idempotency)

    async def organization(self, organization_id: UUID, visibility: Visibility) -> Organization:
        """Return one organization, if ``visibility`` admits it.

        Args:
            organization_id: The organization to read.
            visibility: The caller's discovery rights.

        Returns:
            The stored organization.

        Raises:
            ResourceNotFound: If no organization has ``organization_id``,
                or ``visibility`` does not admit it.
        """
        organization = self._organizations.get(organization_id)
        if organization is None or not _organization_visible(
            organization_id, visibility, self._projects, self._datasets
        ):
            raise ResourceNotFound(f"organization does not exist: {organization_id}")
        return organization

    async def project(self, project_id: UUID, visibility: Visibility) -> Project:
        """Return one project, if ``visibility`` admits it.

        Args:
            project_id: The project to read.
            visibility: The caller's discovery rights.

        Returns:
            The stored project.

        Raises:
            ResourceNotFound: If no project has ``project_id``, or
                ``visibility`` does not admit it.
        """
        project = self._projects.get(project_id)
        if project is None or not _project_visible(project, visibility, self._datasets):
            raise ResourceNotFound(f"project does not exist: {project_id}")
        return project

    async def dataset(self, dataset_id: UUID, visibility: Visibility) -> Dataset:
        """Return one dataset, if ``visibility`` admits it.

        Args:
            dataset_id: The dataset to read.
            visibility: The caller's discovery rights.

        Returns:
            The stored dataset.

        Raises:
            ResourceNotFound: If no dataset has ``dataset_id``, or
                ``visibility`` does not admit it.
        """
        dataset = self._datasets.get(dataset_id)
        if dataset is None or not _dataset_visible(dataset, visibility):
            raise ResourceNotFound(f"dataset does not exist: {dataset_id}")
        return dataset

    async def release(self, dataset_id: UUID, tag: str, visibility: Visibility) -> Release:
        """Return one release by its dataset and tag, if ``visibility`` admits the dataset.

        Args:
            dataset_id: The dataset the release belongs to.
            tag: The release's tag, unique within the dataset.
            visibility: The caller's discovery rights.

        Returns:
            The stored release.

        Raises:
            ResourceNotFound: If no release has ``(dataset_id, tag)``, or
                ``visibility`` does not admit the dataset.
        """
        release = self._releases.get((dataset_id, tag))
        dataset = self._datasets.get(dataset_id)
        if release is None or dataset is None or not _dataset_visible(dataset, visibility):
            raise ResourceNotFound(f"release does not exist: dataset={dataset_id} tag={tag!r}")
        return release

    async def revision_ref(self, dataset_id: UUID, revision_number: int) -> RevisionRef:
        """Return the identity of one committed revision by its dataset and sequential number.

        Args:
            dataset_id: The dataset the revision belongs to.
            revision_number: The revision's 1-based position within the
                dataset.

        Returns:
            The revision's identity and manifest digest.

        Raises:
            ResourceNotFound: If no revision has ``(dataset_id,
                revision_number)``.
        """
        found = _find_revision(self._revisions.values(), dataset_id, revision_number)
        if found is None:
            raise ResourceNotFound(
                f"revision does not exist: dataset={dataset_id} number={revision_number}"
            )
        return RevisionRef(
            id=found.id,
            dataset_id=found.dataset_id,
            number=found.number,
            manifest_sha256=found.manifest_sha256,
        )

    async def organizations(
        self, visibility: Visibility, *, limit: int, after: tuple[str, UUID] | None
    ) -> Window[Organization]:
        """Return a window of organizations ordered by ``(slug, id)``.

        Args:
            visibility: The caller's discovery rights; only admitted
                organizations are counted toward ``limit``.
            limit: The maximum number of organizations to return.
            after: The ``(slug, id)`` of the last organization already
                seen, excluded from the window, or ``None`` to start from
                the beginning.

        Returns:
            The next window of admitted organizations.
        """
        visible = sorted(
            (
                organization
                for organization in self._organizations.values()
                if _organization_visible(
                    organization.id, visibility, self._projects, self._datasets
                )
            ),
            key=lambda organization: (organization.slug, organization.id),
        )
        return _window(
            visible,
            key=lambda organization: (organization.slug, organization.id),
            limit=limit,
            after=after,
        )

    async def projects(
        self,
        organization_id: UUID,
        visibility: Visibility,
        *,
        limit: int,
        after: tuple[str, UUID] | None,
    ) -> Window[Project]:
        """Return a window of one organization's projects ordered by ``(slug, id)``.

        Args:
            organization_id: The owning organization.
            visibility: The caller's discovery rights; only admitted
                projects are counted toward ``limit``.
            limit: The maximum number of projects to return.
            after: The ``(slug, id)`` of the last project already seen,
                excluded from the window, or ``None`` to start from the
                beginning.

        Returns:
            The next window of admitted projects.
        """
        visible = sorted(
            (
                project
                for project in self._projects.values()
                if project.organization_id == organization_id
                and _project_visible(project, visibility, self._datasets)
            ),
            key=lambda project: (project.slug, project.id),
        )
        return _window(
            visible, key=lambda project: (project.slug, project.id), limit=limit, after=after
        )

    async def datasets(
        self,
        project_id: UUID,
        visibility: Visibility,
        *,
        limit: int,
        after: tuple[str, UUID] | None,
    ) -> Window[Dataset]:
        """Return a window of one project's datasets ordered by ``(slug, id)``.

        Args:
            project_id: The owning project.
            visibility: The caller's discovery rights; only admitted
                datasets are counted toward ``limit``.
            limit: The maximum number of datasets to return.
            after: The ``(slug, id)`` of the last dataset already seen,
                excluded from the window, or ``None`` to start from the
                beginning.

        Returns:
            The next window of admitted datasets.
        """
        visible = sorted(
            (
                dataset
                for dataset in self._datasets.values()
                if dataset.project_id == project_id and _dataset_visible(dataset, visibility)
            ),
            key=lambda dataset: (dataset.slug, dataset.id),
        )
        return _window(
            visible, key=lambda dataset: (dataset.slug, dataset.id), limit=limit, after=after
        )

    async def releases(
        self, dataset_id: UUID, visibility: Visibility, *, limit: int, after: tuple[str] | None
    ) -> Window[Release]:
        """Return a window of one dataset's releases ordered by ``tag``.

        ``visibility`` names the dataset a caller is already known to be
        able to discover - a prior call to :meth:`dataset` is what checks
        that - and every release of that dataset is itself visible, so
        this method applies no further filtering of its own.

        Args:
            dataset_id: The dataset the releases belong to.
            visibility: The caller's discovery rights, checked against the
                dataset itself by the caller before this method runs.
            limit: The maximum number of releases to return.
            after: The tag of the last release already seen, excluded from
                the window, or ``None`` to start from the beginning.

        Returns:
            The next window of the dataset's releases.
        """
        del visibility
        visible = sorted(
            (release for release in self._releases.values() if release.dataset_id == dataset_id),
            key=lambda release: (release.tag,),
        )
        return _window(visible, key=lambda release: (release.tag,), limit=limit, after=after)

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

    async def revision(self, revision_id: UUID) -> RevisionRecord:
        """Return one revision row in any state.

        Args:
            revision_id: The revision to read.

        Returns:
            The stored revision.

        Raises:
            ResourceNotFound: If no revision has ``revision_id``.
        """
        found = self._revisions.get(revision_id)
        if found is None:
            raise ResourceNotFound(f"revision does not exist: {revision_id}")
        return found

    async def latest_committed_revision(self, dataset_id: UUID) -> RevisionRecord | None:
        """Return the dataset's highest-numbered committed revision.

        Every revision this store holds is COMMITTED - nothing here ever
        writes another state - so the highest-numbered one is simply the
        one with the greatest ``number``.

        Args:
            dataset_id: The dataset to read.

        Returns:
            The dataset's highest-numbered revision, or None if it has
            never committed one.
        """
        return latest_revision(self._revisions.values(), dataset_id)


#: Postgres's name for ``organizations``' slug UNIQUE constraint.
_ORGANIZATION_SLUG_CONSTRAINT = "organizations_slug_key"

#: Postgres's name for ``projects``' per-organization slug UNIQUE constraint.
_PROJECT_SLUG_CONSTRAINT = "projects_organization_id_slug_key"

#: Postgres's name for ``datasets``' per-project slug UNIQUE constraint.
_DATASET_SLUG_CONSTRAINT = "datasets_project_id_slug_key"

#: Postgres's name for ``releases``' per-dataset tag UNIQUE constraint.
_RELEASE_TAG_CONSTRAINT = "releases_dataset_id_tag_key"

#: Postgres's name for the composite foreign key tying a release to a
#: revision of its own dataset.
_RELEASE_REVISION_FK_CONSTRAINT = "releases_revision_dataset_fk"

#: Postgres's name for ``dataset_revisions``' per-dataset manifest UNIQUE constraint.
_REVISION_MANIFEST_CONSTRAINT = "dataset_revisions_dataset_id_manifest_sha256_key"

#: Every column ``revision_record`` decodes, shared by ``revision`` and
#: ``latest_committed_revision`` so the two SELECTs stay in lockstep.
_REVISION_COLUMNS = (
    "id, dataset_id, revision_number, manifest_sha256, metadata_sha256, revision_path, "
    "file_count, total_bytes, committed_by, committed_at"
)


def _trim_window[ItemT](items: list[ItemT], *, limit: int) -> Window[ItemT]:
    """Split a ``limit + 1`` row fetch into a page and a "further row" flag.

    Args:
        items: Every row fetched, already mapped and in cursor order,
            numbering at most ``limit + 1``.
        limit: The page size the caller asked for.

    Returns:
        The first ``limit`` items, and whether one more followed.
    """
    return Window(items=items[:limit], has_more=len(items) > limit)


class _PostgresTransactionWriter(PostgresIngestWriter):
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

    async def claim(self, claim: IdempotencyClaim) -> Replay | None:
        """Stake this transaction's claim to a principal-scoped idempotency key.

        The claim is staked with an ``INSERT ... ON CONFLICT DO UPDATE``
        that only takes over a row whose ``expires_at`` has already
        passed; a live conflicting row is left untouched and read back to
        decide between a replay and a reuse.

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

    async def insert_release(self, item: Release) -> None:
        """Insert one release row, tagging a dataset revision.

        Args:
            item: The release to insert, fully formed.

        Raises:
            TagExists: If another release already holds ``item.tag`` under
                ``item.dataset_id``.
            ResourceNotFound: If ``item.revision_id`` does not name a
                revision of ``item.dataset_id`` - unreachable once the
                caller has resolved the revision through ``revision_ref``
                first, kept as the backstop the composite foreign key
                enforces regardless.
            asyncpg.UniqueViolationError: If some other unique constraint
                refused the row - not expected against the current schema.
            asyncpg.ForeignKeyViolationError: If some other foreign key
                refused the row - not expected against the current schema.
        """
        try:
            await self._connection.execute(
                """
                INSERT INTO releases
                    (id, dataset_id, tag, revision_id, title, created_by, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                item.id,
                item.dataset_id,
                item.tag,
                item.revision_id,
                item.title,
                item.created_by,
                item.created_at,
            )
        except asyncpg.UniqueViolationError as exc:
            if getattr(exc, "constraint_name", None) != _RELEASE_TAG_CONSTRAINT:
                raise
            raise TagExists(f"release tag already exists: {item.tag!r}") from exc
        except asyncpg.ForeignKeyViolationError as exc:
            if getattr(exc, "constraint_name", None) != _RELEASE_REVISION_FK_CONSTRAINT:
                raise
            raise ResourceNotFound(
                f"revision does not exist: dataset={item.dataset_id} revision={item.revision_id}"
            ) from exc

    async def insert_revision(self, record: RevisionRecord) -> None:
        """Insert the row a COMMITTING session publishes when its commit lands.

        Args:
            record: The revision to insert, fully formed.

        Raises:
            DuplicateContent: If the dataset already holds a revision with
                ``record.manifest_sha256``.
            asyncpg.UniqueViolationError: If some other unique constraint
                refused the row - unreachable under the allocator, which
                reserves ``record.number`` and ``record.revision_path``
                before this insert ever runs.
        """
        try:
            await self._connection.execute(
                f"""
                INSERT INTO dataset_revisions ({_REVISION_COLUMNS})
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                """,
                record.id,
                record.dataset_id,
                record.number,
                record.manifest_sha256,
                record.metadata_sha256,
                record.revision_path,
                record.file_count,
                record.total_bytes,
                record.committed_by,
                record.committed_at,
            )
        except asyncpg.UniqueViolationError as exc:
            if getattr(exc, "constraint_name", None) != _REVISION_MANIFEST_CONSTRAINT:
                raise
            raise DuplicateContent(
                f"dataset already holds this manifest: dataset={record.dataset_id} "
                f"manifest_sha256={record.manifest_sha256}"
            ) from exc

    async def insert_audit_event(self, event: AuditEvent) -> None:
        """Append one audit row.

        Args:
            event: The audit row to append, fully formed.
        """
        await self._connection.execute(
            """
            INSERT INTO audit_events (id, kind, actor, subject_kind, subject_id, payload,
                                       created_at)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7)
            """,
            event.id,
            event.kind,
            event.actor,
            event.subject_kind,
            event.subject_id,
            json.dumps(event.payload),
            event.created_at,
        )

    async def insert_outbox_event(self, event: OutboxEvent) -> None:
        """Append one outbox row, unprocessed.

        Args:
            event: The event to append, fully formed.
        """
        await self._connection.execute(
            """
            INSERT INTO outbox_events (id, kind, subject_id, payload, created_at)
            VALUES ($1, $2, $3, $4::jsonb, $5)
            """,
            event.id,
            event.kind,
            event.subject_id,
            json.dumps(event.payload),
            event.created_at,
        )

    async def update_organization(self, item: Organization, *, expected_version: int) -> None:
        """Apply an update to one organization, guarded by optimistic concurrency.

        Args:
            item: The organization as it should read after the update.
            expected_version: The version the caller last read; the update
                is refused unless this still matches what is stored.

        Raises:
            PreconditionFailed: If no row has ``item.id`` with
                ``expected_version`` as its stored version.
        """
        row = await self._connection.fetchrow(
            """
            UPDATE organizations
            SET title = $2, description = $3, generation = $4, version = $5, updated_at = $6
            WHERE id = $1 AND version = $7
            RETURNING id
            """,
            item.id,
            item.title,
            item.description,
            item.generation,
            item.version,
            self._clock.now(),
            expected_version,
        )
        if row is None:
            raise PreconditionFailed(f"organization version conflict: {item.id}")

    async def update_project(self, item: Project, *, expected_version: int) -> None:
        """Apply an update to one project, guarded by optimistic concurrency.

        Args:
            item: The project as it should read after the update.
            expected_version: The version the caller last read; the update
                is refused unless this still matches what is stored.

        Raises:
            PreconditionFailed: If no row has ``item.id`` with
                ``expected_version`` as its stored version.
        """
        row = await self._connection.fetchrow(
            """
            UPDATE projects
            SET title = $2, description = $3, generation = $4, version = $5, updated_at = $6
            WHERE id = $1 AND version = $7
            RETURNING id
            """,
            item.id,
            item.title,
            item.description,
            item.generation,
            item.version,
            self._clock.now(),
            expected_version,
        )
        if row is None:
            raise PreconditionFailed(f"project version conflict: {item.id}")

    async def update_dataset(self, item: Dataset, *, expected_version: int) -> None:
        """Apply an update to one dataset, guarded by optimistic concurrency.

        Args:
            item: The dataset as it should read after the update.
            expected_version: The version the caller last read; the update
                is refused unless this still matches what is stored.

        Raises:
            PreconditionFailed: If no row has ``item.id`` with
                ``expected_version`` as its stored version.
        """
        row = await self._connection.fetchrow(
            """
            UPDATE datasets
            SET title = $2, description = $3, generation = $4, version = $5, updated_at = $6
            WHERE id = $1 AND version = $7
            RETURNING id
            """,
            item.id,
            item.title,
            item.description,
            item.generation,
            item.version,
            self._clock.now(),
            expected_version,
        )
        if row is None:
            raise PreconditionFailed(f"dataset version conflict: {item.id}")


class PostgresHierarchyStore(PostgresIngestReader):
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

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[HierarchyWriter]:
        """Open one write transaction on a connection held for its duration.

        Yields:
            A writer bound to the connection and transaction, so every
            statement it runs commits or rolls back together.
        """
        async with self._pool.acquire() as connection, connection.transaction():
            yield _PostgresTransactionWriter(connection, self._clock)

    async def organization(self, organization_id: UUID, visibility: Visibility) -> Organization:
        """Return one organization, if ``visibility`` admits it.

        Args:
            organization_id: The organization to read.
            visibility: The caller's discovery rights.

        Returns:
            The stored organization.

        Raises:
            ResourceNotFound: If no organization has ``organization_id``,
                or ``visibility`` does not admit it.
        """
        row = await self._pool.fetchrow(
            """
            SELECT id, slug, title, description, generation, version, created_at
            FROM organizations o
            WHERE o.id = $1
              AND ($2::boolean
                   OR o.id = ANY($3::uuid[])
                   OR EXISTS (SELECT 1 FROM projects p
                              WHERE p.organization_id = o.id AND p.id = ANY($4::uuid[]))
                   OR EXISTS (SELECT 1 FROM datasets d JOIN projects p ON p.id = d.project_id
                              WHERE p.organization_id = o.id AND d.id = ANY($5::uuid[])))
            LIMIT 1
            """,
            organization_id,
            visibility.unrestricted,
            list(visibility.organization_ids),
            list(visibility.project_ids),
            list(visibility.dataset_ids),
        )
        if row is None:
            raise ResourceNotFound(f"organization does not exist: {organization_id}")
        return rows.organization(row)

    async def project(self, project_id: UUID, visibility: Visibility) -> Project:
        """Return one project, if ``visibility`` admits it.

        Args:
            project_id: The project to read.
            visibility: The caller's discovery rights.

        Returns:
            The stored project.

        Raises:
            ResourceNotFound: If no project has ``project_id``, or
                ``visibility`` does not admit it.
        """
        row = await self._pool.fetchrow(
            """
            SELECT id, organization_id, slug, title, description, classification_default,
                   generation, version, created_at
            FROM projects p
            WHERE p.id = $1
              AND ($2::boolean
                   OR p.id = ANY($3::uuid[])
                   OR EXISTS (SELECT 1 FROM datasets d
                              WHERE d.project_id = p.id AND d.id = ANY($4::uuid[])))
            LIMIT 1
            """,
            project_id,
            visibility.unrestricted,
            list(visibility.project_ids),
            list(visibility.dataset_ids),
        )
        if row is None:
            raise ResourceNotFound(f"project does not exist: {project_id}")
        return rows.project(row)

    async def dataset(self, dataset_id: UUID, visibility: Visibility) -> Dataset:
        """Return one dataset, if ``visibility`` admits it.

        Args:
            dataset_id: The dataset to read.
            visibility: The caller's discovery rights.

        Returns:
            The stored dataset.

        Raises:
            ResourceNotFound: If no dataset has ``dataset_id``, or
                ``visibility`` does not admit it.
        """
        row = await self._pool.fetchrow(
            """
            SELECT id, project_id, slug, title, description, profile_name, profile_version,
                   entry_layer, lifecycle_state, generation, version, created_at
            FROM datasets d
            WHERE d.id = $1
              AND ($2::boolean OR d.project_id = ANY($3::uuid[]) OR d.id = ANY($4::uuid[]))
            LIMIT 1
            """,
            dataset_id,
            visibility.unrestricted,
            list(visibility.project_ids),
            list(visibility.dataset_ids),
        )
        if row is None:
            raise ResourceNotFound(f"dataset does not exist: {dataset_id}")
        return rows.dataset(row)

    async def release(self, dataset_id: UUID, tag: str, visibility: Visibility) -> Release:
        """Return one release by its dataset and tag, if ``visibility`` admits the dataset.

        Args:
            dataset_id: The dataset the release belongs to.
            tag: The release's tag, unique within the dataset.
            visibility: The caller's discovery rights.

        Returns:
            The stored release.

        Raises:
            ResourceNotFound: If no release has ``(dataset_id, tag)``, or
                ``visibility`` does not admit the dataset.
        """
        row = await self._pool.fetchrow(
            """
            SELECT r.id, r.dataset_id, r.tag, r.revision_id, dr.revision_number, r.title,
                   r.created_by, r.created_at
            FROM releases r
            JOIN dataset_revisions dr ON dr.id = r.revision_id
            JOIN datasets d ON d.id = r.dataset_id
            WHERE r.dataset_id = $1 AND r.tag = $2
              AND ($3::boolean OR d.project_id = ANY($4::uuid[]) OR d.id = ANY($5::uuid[]))
            LIMIT 1
            """,
            dataset_id,
            tag,
            visibility.unrestricted,
            list(visibility.project_ids),
            list(visibility.dataset_ids),
        )
        if row is None:
            raise ResourceNotFound(f"release does not exist: dataset={dataset_id} tag={tag!r}")
        return rows.release(row)

    async def revision_ref(self, dataset_id: UUID, revision_number: int) -> RevisionRef:
        """Return the identity of one committed revision by its dataset and sequential number.

        Args:
            dataset_id: The dataset the revision belongs to.
            revision_number: The revision's 1-based position within the
                dataset.

        Returns:
            The revision's identity and manifest digest.

        Raises:
            ResourceNotFound: If no revision has ``(dataset_id,
                revision_number)``.
        """
        row = await self._pool.fetchrow(
            """
            SELECT id, dataset_id, revision_number, manifest_sha256 FROM dataset_revisions
            WHERE dataset_id = $1 AND revision_number = $2
            """,
            dataset_id,
            revision_number,
        )
        if row is None:
            raise ResourceNotFound(
                f"revision does not exist: dataset={dataset_id} number={revision_number}"
            )
        return rows.revision_ref(row)

    async def organizations(
        self, visibility: Visibility, *, limit: int, after: tuple[str, UUID] | None
    ) -> Window[Organization]:
        """Return a window of organizations ordered by ``(slug, id)``.

        Args:
            visibility: The caller's discovery rights; only admitted
                organizations are counted toward ``limit``.
            limit: The maximum number of organizations to return.
            after: The ``(slug, id)`` of the last organization already
                seen, excluded from the window, or ``None`` to start from
                the beginning.

        Returns:
            The next window of admitted organizations.
        """
        after_slug, after_id = after if after is not None else (None, None)
        fetched = await self._pool.fetch(
            """
            SELECT id, slug, title, description, generation, version, created_at
            FROM organizations o
            WHERE ($1::boolean
                   OR o.id = ANY($2::uuid[])
                   OR EXISTS (SELECT 1 FROM projects p
                              WHERE p.organization_id = o.id AND p.id = ANY($3::uuid[]))
                   OR EXISTS (SELECT 1 FROM datasets d JOIN projects p ON p.id = d.project_id
                              WHERE p.organization_id = o.id AND d.id = ANY($4::uuid[])))
              AND ($5::text IS NULL OR (o.slug COLLATE "C", o.id) > ($5 COLLATE "C", $6::uuid))
            ORDER BY o.slug COLLATE "C", o.id
            LIMIT $7
            """,
            visibility.unrestricted,
            list(visibility.organization_ids),
            list(visibility.project_ids),
            list(visibility.dataset_ids),
            after_slug,
            after_id,
            limit + 1,
        )
        return _trim_window([rows.organization(row) for row in fetched], limit=limit)

    async def projects(
        self,
        organization_id: UUID,
        visibility: Visibility,
        *,
        limit: int,
        after: tuple[str, UUID] | None,
    ) -> Window[Project]:
        """Return a window of one organization's projects ordered by ``(slug, id)``.

        Args:
            organization_id: The owning organization.
            visibility: The caller's discovery rights; only admitted
                projects are counted toward ``limit``.
            limit: The maximum number of projects to return.
            after: The ``(slug, id)`` of the last project already seen,
                excluded from the window, or ``None`` to start from the
                beginning.

        Returns:
            The next window of admitted projects.
        """
        after_slug, after_id = after if after is not None else (None, None)
        fetched = await self._pool.fetch(
            """
            SELECT id, organization_id, slug, title, description, classification_default,
                   generation, version, created_at
            FROM projects p
            WHERE p.organization_id = $1
              AND ($2::boolean
                   OR p.id = ANY($3::uuid[])
                   OR EXISTS (SELECT 1 FROM datasets d
                              WHERE d.project_id = p.id AND d.id = ANY($4::uuid[])))
              AND ($5::text IS NULL OR (p.slug COLLATE "C", p.id) > ($5 COLLATE "C", $6::uuid))
            ORDER BY p.slug COLLATE "C", p.id
            LIMIT $7
            """,
            organization_id,
            visibility.unrestricted,
            list(visibility.project_ids),
            list(visibility.dataset_ids),
            after_slug,
            after_id,
            limit + 1,
        )
        return _trim_window([rows.project(row) for row in fetched], limit=limit)

    async def datasets(
        self,
        project_id: UUID,
        visibility: Visibility,
        *,
        limit: int,
        after: tuple[str, UUID] | None,
    ) -> Window[Dataset]:
        """Return a window of one project's datasets ordered by ``(slug, id)``.

        Args:
            project_id: The owning project.
            visibility: The caller's discovery rights; only admitted
                datasets are counted toward ``limit``.
            limit: The maximum number of datasets to return.
            after: The ``(slug, id)`` of the last dataset already seen,
                excluded from the window, or ``None`` to start from the
                beginning.

        Returns:
            The next window of admitted datasets.
        """
        after_slug, after_id = after if after is not None else (None, None)
        fetched = await self._pool.fetch(
            """
            SELECT id, project_id, slug, title, description, profile_name, profile_version,
                   entry_layer, lifecycle_state, generation, version, created_at
            FROM datasets d
            WHERE d.project_id = $1
              AND ($2::boolean OR d.project_id = ANY($3::uuid[]) OR d.id = ANY($4::uuid[]))
              AND ($5::text IS NULL OR (d.slug COLLATE "C", d.id) > ($5 COLLATE "C", $6::uuid))
            ORDER BY d.slug COLLATE "C", d.id
            LIMIT $7
            """,
            project_id,
            visibility.unrestricted,
            list(visibility.project_ids),
            list(visibility.dataset_ids),
            after_slug,
            after_id,
            limit + 1,
        )
        return _trim_window([rows.dataset(row) for row in fetched], limit=limit)

    async def releases(
        self, dataset_id: UUID, visibility: Visibility, *, limit: int, after: tuple[str] | None
    ) -> Window[Release]:
        """Return a window of one dataset's releases ordered by ``tag``.

        ``visibility`` names the dataset a caller is already known to be
        able to discover - a prior call to :meth:`dataset` is what checks
        that - and every release of that dataset is itself visible, so
        this method applies no further filtering of its own.

        Args:
            dataset_id: The dataset the releases belong to.
            visibility: The caller's discovery rights, checked against the
                dataset itself by the caller before this method runs.
            limit: The maximum number of releases to return.
            after: The tag of the last release already seen, excluded
                from the window, or ``None`` to start from the beginning.

        Returns:
            The next window of the dataset's releases.
        """
        del visibility
        after_tag = after[0] if after is not None else None
        fetched = await self._pool.fetch(
            """
            SELECT r.id, r.dataset_id, r.tag, r.revision_id, dr.revision_number, r.title,
                   r.created_by, r.created_at
            FROM releases r JOIN dataset_revisions dr ON dr.id = r.revision_id
            WHERE r.dataset_id = $1
              AND ($2::text IS NULL OR r.tag COLLATE "C" > $2 COLLATE "C")
            ORDER BY r.tag COLLATE "C"
            LIMIT $3
            """,
            dataset_id,
            after_tag,
            limit + 1,
        )
        return _trim_window([rows.release(row) for row in fetched], limit=limit)

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

    async def revision(self, revision_id: UUID) -> RevisionRecord:
        """Return one revision row in any state.

        Args:
            revision_id: The revision to read.

        Returns:
            The stored revision.

        Raises:
            ResourceNotFound: If no revision has ``revision_id``.
        """
        row = await self._pool.fetchrow(
            f"SELECT {_REVISION_COLUMNS} FROM dataset_revisions WHERE id = $1", revision_id
        )
        if row is None:
            raise ResourceNotFound(f"revision does not exist: {revision_id}")
        return rows.revision_record(row)

    async def latest_committed_revision(self, dataset_id: UUID) -> RevisionRecord | None:
        """Return the dataset's highest-numbered committed revision.

        Args:
            dataset_id: The dataset to read.

        Returns:
            The dataset's highest-numbered revision in state COMMITTED, or
            None if it has never committed one.
        """
        row = await self._pool.fetchrow(
            f"""
            SELECT {_REVISION_COLUMNS} FROM dataset_revisions
            WHERE dataset_id = $1 AND state = 'COMMITTED'
            ORDER BY revision_number DESC LIMIT 1
            """,
            dataset_id,
        )
        return rows.revision_record(row) if row is not None else None
