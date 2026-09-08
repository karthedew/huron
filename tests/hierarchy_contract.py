"""Scenarios pinning ``HierarchyStore`` behavior, run against every backend.

Each ``scenario_*`` function proves one explicit contract of the port -
transaction atomicity, uniqueness, optimistic concurrency, idempotency,
revision resolution, ordering, windowing and the three visibility rules -
against whatever store it is handed, so the same assertions run for the
in-memory reference store and for a durable backend without being written
twice. ``seed_hierarchy`` builds the small organization/project/dataset
tree the scenarios and their callers need.
"""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from huron.pkg.catalog.errors import (
    DatasetLocked,
    IdempotencyKeyReused,
    IngestSessionExpired,
    PreconditionFailed,
    ResourceNotFound,
    TagExists,
)
from huron.pkg.catalog.failures import SlugExists
from huron.pkg.catalog.ids import uuid7
from huron.pkg.catalog.ingest import (
    LEASE_TTL,
    FileState,
    IngestFile,
    IngestState,
    UploadAction,
    compute_upload_plan,
)
from huron.pkg.catalog.layers import Layer
from huron.pkg.catalog.lifecycle import DatasetLifecycle
from huron.pkg.catalog.manifest import Manifest, ManifestEntry
from huron.pkg.catalog.models import OutboxEvent, RevisionRecord, RevisionRef
from huron.pkg.catalog.persistence import IdempotencyClaim, Replay
from huron.pkg.catalog.records import AuditEvent, Dataset, Organization, Project, Release
from huron.pkg.rbac import Visibility

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
    from uuid import UUID

    from huron.core.ports import HierarchyStore
    from huron.pkg.catalog.ingest import IngestSession
    from tests.unit.support import FakeClock


class _AbortedError(Exception):
    """Raised deliberately, from inside an open transaction, to force a rollback."""


@dataclasses.dataclass(slots=True)
class SeededHierarchy:
    """The id ``seed_hierarchy`` assigned to each record it created, keyed by slug.

    Attributes:
        organizations: Each organization's id, keyed by slug.
        projects: Each project's id, keyed by slug.
        datasets: Each dataset's id, keyed by slug.
    """

    organizations: dict[str, UUID]
    projects: dict[str, UUID]
    datasets: dict[str, UUID]


def _organization(*, slug: str) -> Organization:
    """Build an ``Organization`` ready to insert, at generation and version 1."""
    return Organization(
        id=uuid7(),
        slug=slug,
        title=slug,
        description="",
        generation=1,
        version=1,
        created_at=datetime.now(UTC),
    )


def _project(*, organization_id: UUID, slug: str) -> Project:
    """Build a ``Project`` ready to insert, at generation and version 1."""
    return Project(
        id=uuid7(),
        organization_id=organization_id,
        slug=slug,
        title=slug,
        description="",
        data_classification="open",
        generation=1,
        version=1,
        created_at=datetime.now(UTC),
    )


def _dataset(*, project_id: UUID, slug: str) -> Dataset:
    """Build a ``Dataset`` ready to insert, at generation and version 1."""
    return Dataset(
        id=uuid7(),
        project_id=project_id,
        slug=slug,
        title=slug,
        description="",
        profile_name="generic",
        profile_version="1",
        entry_layer=Layer.RAW.value,
        lifecycle_state=DatasetLifecycle.ACTIVE.value,
        generation=1,
        version=1,
        created_at=datetime.now(UTC),
    )


def _release(*, dataset_id: UUID, tag: str, revision_id: UUID, revision_number: int) -> Release:
    """Build a ``Release`` citing one revision, ready to insert."""
    return Release(
        id=uuid7(),
        dataset_id=dataset_id,
        tag=tag,
        revision_id=revision_id,
        revision_number=revision_number,
        title=None,
        created_by="user:test",
        created_at=datetime.now(UTC),
    )


def committed_revision(
    dataset_id: UUID,
    number: int,
    *,
    revision_id: UUID | None = None,
    manifest_sha256: str | None = None,
) -> RevisionRecord:
    """Build a ``RevisionRecord`` ready to insert through ``insert_revision``.

    Args:
        dataset_id: The dataset the revision belongs to.
        number: The revision's 1-based position within its dataset.
        revision_id: The revision's identifier, or None to mint a fresh one.
        manifest_sha256: The manifest's content identity, or None to derive
            one from ``revision_id`` so two calls with distinct ids never
            collide by accident.

    Returns:
        A revision record with arbitrary but valid values for every field
        a scenario does not care about.
    """
    revision_id = revision_id if revision_id is not None else uuid7()
    digest = manifest_sha256 if manifest_sha256 is not None else revision_id.hex.ljust(64, "0")
    return RevisionRecord(
        id=revision_id,
        dataset_id=dataset_id,
        number=number,
        manifest_sha256=digest,
        metadata_sha256=digest,
        revision_path=f"revisions/{number:06d}--{revision_id}",
        committed_by="user:test",
        committed_at=datetime.now(UTC),
        file_count=1,
        total_bytes=1,
    )


async def seed_hierarchy(
    store: HierarchyStore,
    tree: Mapping[str, Mapping[str, Sequence[str]]] | None = None,
) -> SeededHierarchy:
    """Create an organization/project/dataset tree from a plain slug description.

    Args:
        store: The store to write into; every record is created in one
            transaction.
        tree: One entry per organization slug to create, each mapping to
            one entry per project slug to create under it, each mapping to
            the dataset slugs to create under that project. Defaults to a
            single organization, project and dataset.

    Returns:
        The id of every organization, project and dataset created, each
        keyed by its own slug.
    """
    if tree is None:
        tree = {"astro": {"sims": ("run-0001",)}}
    organizations: dict[str, UUID] = {}
    projects: dict[str, UUID] = {}
    datasets: dict[str, UUID] = {}
    async with store.transaction() as writer:
        for organization_slug, project_tree in tree.items():
            organization = _organization(slug=organization_slug)
            await writer.insert_organization(organization)
            organizations[organization_slug] = organization.id
            for project_slug, dataset_slugs in project_tree.items():
                project = _project(organization_id=organization.id, slug=project_slug)
                await writer.insert_project(project)
                projects[project_slug] = project.id
                for dataset_slug in dataset_slugs:
                    dataset = _dataset(project_id=project.id, slug=dataset_slug)
                    await writer.insert_dataset(dataset, data_classification="open")
                    datasets[dataset_slug] = dataset.id
    return SeededHierarchy(organizations=organizations, projects=projects, datasets=datasets)


async def scenario_1_write_invisible_until_commit(store: HierarchyStore) -> None:
    """A write is invisible to a reader until commit, and never lands if the transaction raises."""
    organization = _organization(slug="astro")
    async with store.transaction() as writer:
        await writer.insert_organization(organization)
        with pytest.raises(ResourceNotFound):
            await store.organization(organization.id, Visibility.ALL)
    committed = await store.organization(organization.id, Visibility.ALL)
    assert committed.id == organization.id

    doomed = _organization(slug="doomed")
    with pytest.raises(_AbortedError):
        async with store.transaction() as writer:
            await writer.insert_organization(doomed)
            raise _AbortedError
    with pytest.raises(ResourceNotFound):
        await store.organization(doomed.id, Visibility.ALL)


async def scenario_2_uniqueness(store: HierarchyStore) -> None:
    """A duplicate slug or tag under the same parent is refused; a different parent is not."""
    organization_a = _organization(slug="org-a")
    organization_b = _organization(slug="org-b")
    async with store.transaction() as writer:
        await writer.insert_organization(organization_a)
        await writer.insert_organization(organization_b)

    with pytest.raises(SlugExists):
        async with store.transaction() as writer:
            await writer.insert_organization(_organization(slug="org-a"))

    with pytest.raises(SlugExists):
        async with store.transaction() as writer:
            await writer.insert_organization(_organization(slug="org-c"))
            await writer.insert_organization(_organization(slug="org-c"))

    project_a = _project(organization_id=organization_a.id, slug="sims")
    project_b = _project(organization_id=organization_b.id, slug="sims")
    async with store.transaction() as writer:
        await writer.insert_project(project_a)
        await writer.insert_project(project_b)

    with pytest.raises(SlugExists):
        async with store.transaction() as writer:
            await writer.insert_project(_project(organization_id=organization_a.id, slug="sims"))

    dataset_a = _dataset(project_id=project_a.id, slug="run-0001")
    dataset_b = _dataset(project_id=project_b.id, slug="run-0001")
    async with store.transaction() as writer:
        await writer.insert_dataset(dataset_a, data_classification="open")
        await writer.insert_dataset(dataset_b, data_classification="open")

    with pytest.raises(SlugExists):
        async with store.transaction() as writer:
            await writer.insert_dataset(
                _dataset(project_id=project_a.id, slug="run-0001"), data_classification="open"
            )

    revision = committed_revision(dataset_a.id, 1, manifest_sha256="a" * 64)
    async with store.transaction() as writer:
        await writer.insert_revision(revision)
    async with store.transaction() as writer:
        await writer.insert_release(
            _release(
                dataset_id=dataset_a.id,
                tag="v1",
                revision_id=revision.id,
                revision_number=revision.number,
            )
        )

    with pytest.raises(TagExists):
        async with store.transaction() as writer:
            await writer.insert_release(
                _release(
                    dataset_id=dataset_a.id,
                    tag="v1",
                    revision_id=revision.id,
                    revision_number=revision.number,
                )
            )


async def scenario_3_optimistic_concurrency(store: HierarchyStore) -> None:
    """update_* stores the successor at the current version and refuses a stale one, unchanged."""
    organization = _organization(slug="astro")
    async with store.transaction() as writer:
        await writer.insert_organization(organization)
    project = _project(organization_id=organization.id, slug="sims")
    async with store.transaction() as writer:
        await writer.insert_project(project)
    dataset = _dataset(project_id=project.id, slug="run-0001")
    async with store.transaction() as writer:
        await writer.insert_dataset(dataset, data_classification="open")

    updated_organization = dataclasses.replace(
        organization, title="Astro II", version=2, generation=2
    )
    async with store.transaction() as writer:
        await writer.update_organization(updated_organization, expected_version=1)
    read_organization = await store.organization(organization.id, Visibility.ALL)
    assert read_organization.title == "Astro II"
    assert read_organization.version == 2

    with pytest.raises(PreconditionFailed):
        async with store.transaction() as writer:
            await writer.update_organization(
                dataclasses.replace(updated_organization, title="lost", version=3, generation=3),
                expected_version=1,
            )
    unchanged_organization = await store.organization(organization.id, Visibility.ALL)
    assert unchanged_organization.title == "Astro II"
    assert unchanged_organization.version == 2

    with pytest.raises(PreconditionFailed):
        async with store.transaction() as writer:
            await writer.update_organization(
                dataclasses.replace(organization, id=uuid7(), version=2, generation=2),
                expected_version=1,
            )

    updated_project = dataclasses.replace(project, title="Sims II", version=2, generation=2)
    async with store.transaction() as writer:
        await writer.update_project(updated_project, expected_version=1)
    read_project = await store.project(project.id, Visibility.ALL)
    assert read_project.title == "Sims II"

    with pytest.raises(PreconditionFailed):
        async with store.transaction() as writer:
            await writer.update_project(
                dataclasses.replace(updated_project, title="lost", version=3, generation=3),
                expected_version=1,
            )
    assert (await store.project(project.id, Visibility.ALL)).title == "Sims II"

    updated_dataset = dataclasses.replace(dataset, title="Run 1", version=2, generation=2)
    async with store.transaction() as writer:
        await writer.update_dataset(updated_dataset, expected_version=1)
    read_dataset = await store.dataset(dataset.id, Visibility.ALL)
    assert read_dataset.title == "Run 1"

    with pytest.raises(PreconditionFailed):
        async with store.transaction() as writer:
            await writer.update_dataset(
                dataclasses.replace(updated_dataset, title="lost", version=3, generation=3),
                expected_version=1,
            )
    assert (await store.dataset(dataset.id, Visibility.ALL)).title == "Run 1"


async def scenario_4_idempotency(store: HierarchyStore) -> None:
    """A claim replays inside its TTL, rejects a mismatch, and leaves no trace on rollback."""
    claim = IdempotencyClaim(principal="user:alice", key="create-astro", request_sha256="a" * 64)
    async with store.transaction() as writer:
        assert await writer.claim(claim) is None
        organization = _organization(slug="astro")
        await writer.insert_organization(organization)
        await writer.remember(claim, Replay(kind="organization", resource_id=organization.id))

    async with store.transaction() as writer:
        replay = await writer.claim(claim)
    assert replay == Replay(kind="organization", resource_id=organization.id)

    mismatched = IdempotencyClaim(
        principal="user:alice", key="create-astro", request_sha256="b" * 64
    )
    with pytest.raises(IdempotencyKeyReused):
        async with store.transaction() as writer:
            await writer.claim(mismatched)

    other_principal = IdempotencyClaim(
        principal="user:bob", key="create-astro", request_sha256="a" * 64
    )
    async with store.transaction() as writer:
        assert await writer.claim(other_principal) is None
        second_organization = _organization(slug="astro-bob")
        await writer.insert_organization(second_organization)
        await writer.remember(
            other_principal, Replay(kind="organization", resource_id=second_organization.id)
        )

    doomed_claim = IdempotencyClaim(principal="user:carol", key="doomed", request_sha256="c" * 64)
    with pytest.raises(_AbortedError):
        async with store.transaction() as writer:
            assert await writer.claim(doomed_claim) is None
            raise _AbortedError
    async with store.transaction() as writer:
        assert await writer.claim(doomed_claim) is None

    race_claim = IdempotencyClaim(principal="user:dana", key="create-race", request_sha256="d" * 64)

    async def _create_or_replay() -> Replay:
        """Stake ``race_claim``, creating the organization only for whichever attempt wins it."""
        async with store.transaction() as writer:
            replay = await writer.claim(race_claim)
            if replay is not None:
                return replay
            item = _organization(slug="race")
            await writer.insert_organization(item)
            won = Replay(kind="organization", resource_id=item.id)
            await writer.remember(race_claim, won)
            return won

    first, second = await asyncio.gather(_create_or_replay(), _create_or_replay())
    assert first == second
    window = await store.organizations(Visibility.ALL, limit=200, after=None)
    assert sum(1 for item in window.items if item.slug == "race") == 1


async def scenario_5_revisions(store: HierarchyStore) -> None:
    """revision_ref resolves a committed revision and insert_release enforces that it exists."""
    hierarchy = await seed_hierarchy(store)
    dataset_id = hierarchy.datasets["run-0001"]

    with pytest.raises(ResourceNotFound):
        await store.revision_ref(dataset_id, 1)

    revision = committed_revision(dataset_id, 1, manifest_sha256="b" * 64)
    async with store.transaction() as writer:
        await writer.insert_revision(revision)
    assert await store.revision_ref(dataset_id, 1) == RevisionRef(
        id=revision.id,
        dataset_id=revision.dataset_id,
        number=revision.number,
        manifest_sha256=revision.manifest_sha256,
    )

    with pytest.raises(ResourceNotFound):
        async with store.transaction() as writer:
            await writer.insert_release(
                _release(dataset_id=dataset_id, tag="v1", revision_id=uuid7(), revision_number=99)
            )

    async with store.transaction() as writer:
        await writer.insert_release(
            _release(
                dataset_id=dataset_id,
                tag="v1",
                revision_id=revision.id,
                revision_number=revision.number,
            )
        )
    release = await store.release(dataset_id, "v1", Visibility.ALL)
    assert release.revision_id == revision.id
    assert release.revision_number == revision.number


async def scenario_6_ordering(store: HierarchyStore) -> None:
    """Organizations, projects, datasets and releases sort by (slug, id) or tag, not insertion.

    Six slugs - three hyphenated, three not - sort one way under Python's
    own ``str`` comparison and a different way under the deployment's
    default collation; every window this store returns is expected to
    agree with Python's ``sorted``, never with insertion order or the
    deployment collation.
    """
    slugs = ("a-1", "a1", "a-b", "ab", "abc", "a-c")
    expected = ["a-1", "a-b", "a-c", "a1", "ab", "abc"]
    tree: dict[str, dict[str, tuple[str, ...]]] = {slug: {} for slug in slugs}
    tree["a-1"] = {slug: (slugs if slug == "a-1" else ()) for slug in slugs}
    hierarchy = await seed_hierarchy(store, tree)

    organizations = await store.organizations(Visibility.ALL, limit=200, after=None)
    assert [item.slug for item in organizations.items] == expected

    projects = await store.projects(
        hierarchy.organizations["a-1"], Visibility.ALL, limit=200, after=None
    )
    assert [item.slug for item in projects.items] == expected

    datasets = await store.datasets(
        hierarchy.projects["a-1"], Visibility.ALL, limit=200, after=None
    )
    assert [item.slug for item in datasets.items] == expected

    dataset_id = hierarchy.datasets["a-1"]
    revision = committed_revision(dataset_id, 1, manifest_sha256="d" * 64)
    async with store.transaction() as writer:
        await writer.insert_revision(revision)
    async with store.transaction() as writer:
        for tag in slugs:
            await writer.insert_release(
                _release(
                    dataset_id=dataset_id,
                    tag=tag,
                    revision_id=revision.id,
                    revision_number=revision.number,
                )
            )
    releases = await store.releases(dataset_id, Visibility.ALL, limit=200, after=None)
    assert [item.tag for item in releases.items] == expected


async def scenario_7_windows(store: HierarchyStore) -> None:
    """A window returns at most limit items, has_more tracks what remains, and after is exclusive.

    Five organizations are seeded - enough for a partial page, a full page
    and a limit=1 walk without being unwieldy - and every window and walk
    below is asserted against Python's own ``sorted`` order on their slugs.
    """
    slugs = ("org-1", "org-2", "org-3", "org-4", "org-5")
    await seed_hierarchy(store, {slug: {} for slug in slugs})
    ordered = sorted(slugs)

    partial = await store.organizations(Visibility.ALL, limit=3, after=None)
    assert [item.slug for item in partial.items] == ordered[:3]
    assert partial.has_more is True

    exact = await store.organizations(Visibility.ALL, limit=len(slugs), after=None)
    assert [item.slug for item in exact.items] == ordered
    assert exact.has_more is False

    generous = await store.organizations(Visibility.ALL, limit=200, after=None)
    assert [item.slug for item in generous.items] == ordered
    assert generous.has_more is False

    first = partial.items[0]
    after_first = await store.organizations(Visibility.ALL, limit=200, after=(first.slug, first.id))
    assert first.slug not in {item.slug for item in after_first.items}
    assert [item.slug for item in after_first.items] == ordered[1:]

    last = exact.items[-1]
    after_last = await store.organizations(Visibility.ALL, limit=200, after=(last.slug, last.id))
    assert after_last.items == []
    assert after_last.has_more is False

    seen: list[str] = []
    after: tuple[str, UUID] | None = None
    while True:
        window = await store.organizations(Visibility.ALL, limit=1, after=after)
        seen.extend(item.slug for item in window.items)
        if not window.has_more:
            break
        after = (window.items[-1].slug, window.items[-1].id)
    assert seen == ordered


@dataclasses.dataclass(frozen=True, slots=True)
class VisibleIds:
    """The ids one ``Visibility`` admits at each level of a hierarchy fixture.

    Attributes:
        organizations: Visible organization ids.
        projects: Visible project ids.
        datasets: Visible dataset ids.
        releases: Visible release ids.
    """

    organizations: frozenset[UUID]
    projects: frozenset[UUID]
    datasets: frozenset[UUID]
    releases: frozenset[UUID]


async def scenario_8_visibility(store: HierarchyStore) -> dict[str, VisibleIds]:
    """The three visibility rules, evaluated at every level against one fixture.

    Unlike every other scenario in this module, this one returns a value:
    a mapping from a visibility's label to the ids it admits at each
    level, so a later comparison of two backends can assert the two
    mappings are equal without re-deriving this fixture. One project holds
    an invisible dataset sorting between two visible ones, so a window
    narrower than the visible set and a single-item walk across it can
    prove that invisible rows are excluded before a limit is applied,
    rather than truncated from a page or skipped past by a cursor. A
    third organization sorts between the other two - visible only through
    a dataset of its own - so the same walk repeats one level up, over an
    invisible organization rather than an invisible dataset.

    Args:
        store: The store to seed and query.

    Returns:
        One ``VisibleIds`` per evaluated ``Visibility``, keyed by
        ``"all"``, ``"project_ids"``, ``"dataset_ids"``,
        ``"organization_ids"`` and ``"empty"``.
    """
    hierarchy = await seed_hierarchy(
        store,
        {
            "org-a": {"a1": ("a1-ds",), "a2": ("a2-ds", "a2-dt", "a2-du")},
            "org-b": {"b1": ("b1-ds",)},
            "org-c": {"c1": ("c1-ds",)},
        },
    )
    org_a_id = hierarchy.organizations["org-a"]
    org_b_id = hierarchy.organizations["org-b"]
    org_c_id = hierarchy.organizations["org-c"]
    a1_id = hierarchy.projects["a1"]
    a2_id = hierarchy.projects["a2"]
    b1_id = hierarchy.projects["b1"]
    c1_id = hierarchy.projects["c1"]
    a1ds_id = hierarchy.datasets["a1-ds"]
    a2ds_id = hierarchy.datasets["a2-ds"]
    a2dt_id = hierarchy.datasets["a2-dt"]
    a2du_id = hierarchy.datasets["a2-du"]
    b1ds_id = hierarchy.datasets["b1-ds"]
    c1ds_id = hierarchy.datasets["c1-ds"]

    revision = committed_revision(a1ds_id, 1, manifest_sha256="e" * 64)
    async with store.transaction() as writer:
        await writer.insert_revision(revision)
    release = _release(
        dataset_id=a1ds_id, tag="v1", revision_id=revision.id, revision_number=revision.number
    )
    async with store.transaction() as writer:
        await writer.insert_release(release)

    async def visible_ids(visibility: Visibility) -> VisibleIds:
        """Compute the ids ``visibility`` admits at every level of the fixture."""
        organizations = await store.organizations(visibility, limit=200, after=None)
        projects_a = await store.projects(org_a_id, visibility, limit=200, after=None)
        projects_b = await store.projects(org_b_id, visibility, limit=200, after=None)
        projects_c = await store.projects(org_c_id, visibility, limit=200, after=None)
        datasets_a1 = await store.datasets(a1_id, visibility, limit=200, after=None)
        datasets_a2 = await store.datasets(a2_id, visibility, limit=200, after=None)
        datasets_b1 = await store.datasets(b1_id, visibility, limit=200, after=None)
        datasets_c1 = await store.datasets(c1_id, visibility, limit=200, after=None)
        try:
            await store.release(a1ds_id, "v1", visibility)
            releases = frozenset({release.id})
        except ResourceNotFound:
            releases = frozenset()
        return VisibleIds(
            organizations=frozenset(item.id for item in organizations.items),
            projects=frozenset(
                item.id for item in (*projects_a.items, *projects_b.items, *projects_c.items)
            ),
            datasets=frozenset(
                item.id
                for item in (
                    *datasets_a1.items,
                    *datasets_a2.items,
                    *datasets_b1.items,
                    *datasets_c1.items,
                )
            ),
            releases=releases,
        )

    async def assert_invisible(
        reader: Callable[[UUID, Visibility], Awaitable[object]],
        ids: Iterable[UUID],
        visibility: Visibility,
    ) -> None:
        """Assert every id in ``ids`` is ``ResourceNotFound`` to ``reader`` under ``visibility``."""
        for resource_id in ids:
            with pytest.raises(ResourceNotFound):
                await reader(resource_id, visibility)

    results: dict[str, VisibleIds] = {}

    all_visibility = Visibility.ALL
    results["all"] = await visible_ids(all_visibility)
    assert results["all"].organizations == frozenset({org_a_id, org_b_id, org_c_id})
    assert results["all"].projects == frozenset({a1_id, a2_id, b1_id, c1_id})
    assert results["all"].datasets == frozenset(
        {a1ds_id, a2ds_id, a2dt_id, a2du_id, b1ds_id, c1ds_id}
    )
    assert results["all"].releases == frozenset({release.id})
    assert (await store.organization(org_a_id, all_visibility)).id == org_a_id
    assert (await store.organization(org_b_id, all_visibility)).id == org_b_id
    assert (await store.organization(org_c_id, all_visibility)).id == org_c_id
    assert (await store.project(a1_id, all_visibility)).id == a1_id
    assert (await store.project(a2_id, all_visibility)).id == a2_id
    assert (await store.project(b1_id, all_visibility)).id == b1_id
    assert (await store.project(c1_id, all_visibility)).id == c1_id
    assert (await store.dataset(a1ds_id, all_visibility)).id == a1ds_id
    assert (await store.dataset(a2ds_id, all_visibility)).id == a2ds_id
    assert (await store.dataset(b1ds_id, all_visibility)).id == b1ds_id
    assert (await store.dataset(c1ds_id, all_visibility)).id == c1ds_id
    assert (await store.release(a1ds_id, "v1", all_visibility)).id == release.id

    project_scoped = Visibility(project_ids=frozenset({a1_id}))
    results["project_ids"] = await visible_ids(project_scoped)
    assert results["project_ids"].organizations == frozenset({org_a_id})
    assert results["project_ids"].projects == frozenset({a1_id})
    assert results["project_ids"].datasets == frozenset({a1ds_id})
    assert results["project_ids"].releases == frozenset({release.id})
    assert (await store.organization(org_a_id, project_scoped)).id == org_a_id
    assert (await store.project(a1_id, project_scoped)).id == a1_id
    assert (await store.dataset(a1ds_id, project_scoped)).id == a1ds_id
    assert (await store.release(a1ds_id, "v1", project_scoped)).id == release.id
    await assert_invisible(store.organization, (org_b_id, org_c_id), project_scoped)
    await assert_invisible(store.project, (a2_id, b1_id, c1_id), project_scoped)
    await assert_invisible(store.dataset, (a2ds_id, b1ds_id, c1ds_id), project_scoped)

    dataset_scoped = Visibility(dataset_ids=frozenset({a2ds_id, a2du_id, c1ds_id}))
    results["dataset_ids"] = await visible_ids(dataset_scoped)
    assert results["dataset_ids"].organizations == frozenset({org_a_id, org_c_id})
    assert results["dataset_ids"].projects == frozenset({a2_id, c1_id})
    assert results["dataset_ids"].datasets == frozenset({a2ds_id, a2du_id, c1ds_id})
    assert results["dataset_ids"].releases == frozenset()
    assert (await store.organization(org_a_id, dataset_scoped)).id == org_a_id
    assert (await store.organization(org_c_id, dataset_scoped)).id == org_c_id
    assert (await store.project(a2_id, dataset_scoped)).id == a2_id
    assert (await store.project(c1_id, dataset_scoped)).id == c1_id
    assert (await store.dataset(a2ds_id, dataset_scoped)).id == a2ds_id
    assert (await store.dataset(a2du_id, dataset_scoped)).id == a2du_id
    assert (await store.dataset(c1ds_id, dataset_scoped)).id == c1ds_id
    await assert_invisible(store.project, (a1_id, b1_id), dataset_scoped)
    await assert_invisible(store.dataset, (a1ds_id, a2dt_id, b1ds_id), dataset_scoped)
    await assert_invisible(store.organization, (org_b_id,), dataset_scoped)
    with pytest.raises(ResourceNotFound):
        await store.release(a1ds_id, "v1", dataset_scoped)

    narrow_projects = await store.projects(org_a_id, dataset_scoped, limit=1, after=None)
    assert [item.id for item in narrow_projects.items] == [a2_id]
    assert narrow_projects.has_more is False

    walked_dataset_ids: list[UUID] = []
    walk_after: tuple[str, UUID] | None = None
    while True:
        window = await store.datasets(a2_id, dataset_scoped, limit=1, after=walk_after)
        assert a2dt_id not in {item.id for item in window.items}
        walked_dataset_ids.extend(item.id for item in window.items)
        if not window.has_more:
            break
        walk_after = (window.items[-1].slug, window.items[-1].id)
        assert walk_after != ("a2-dt", a2dt_id)
    assert walked_dataset_ids == [a2ds_id, a2du_id]

    walked_organization_ids: list[UUID] = []
    organization_walk_after: tuple[str, UUID] | None = None
    while True:
        window = await store.organizations(dataset_scoped, limit=1, after=organization_walk_after)
        assert org_b_id not in {item.id for item in window.items}
        walked_organization_ids.extend(item.id for item in window.items)
        if not window.has_more:
            break
        organization_walk_after = (window.items[-1].slug, window.items[-1].id)
        assert organization_walk_after != ("org-b", org_b_id)
    assert walked_organization_ids == [org_a_id, org_c_id]

    organization_scoped = Visibility(organization_ids=frozenset({org_a_id}))
    results["organization_ids"] = await visible_ids(organization_scoped)
    assert results["organization_ids"].organizations == frozenset({org_a_id})
    assert results["organization_ids"].projects == frozenset()
    assert results["organization_ids"].datasets == frozenset()
    assert results["organization_ids"].releases == frozenset()
    assert (await store.organization(org_a_id, organization_scoped)).id == org_a_id
    await assert_invisible(store.organization, (org_b_id, org_c_id), organization_scoped)
    await assert_invisible(store.project, (a1_id, a2_id, b1_id, c1_id), organization_scoped)
    await assert_invisible(store.dataset, (a1ds_id, a2ds_id, b1ds_id, c1ds_id), organization_scoped)
    with pytest.raises(ResourceNotFound):
        await store.release(a1ds_id, "v1", organization_scoped)

    empty = Visibility()
    results["empty"] = await visible_ids(empty)
    assert results["empty"].organizations == frozenset()
    assert results["empty"].projects == frozenset()
    assert results["empty"].datasets == frozenset()
    assert results["empty"].releases == frozenset()
    await assert_invisible(store.organization, (org_a_id, org_b_id, org_c_id), empty)
    await assert_invisible(store.project, (a1_id, a2_id, b1_id, c1_id), empty)
    await assert_invisible(store.dataset, (a1ds_id, a2ds_id, b1ds_id, c1ds_id), empty)
    with pytest.raises(ResourceNotFound):
        await store.release(a1ds_id, "v1", empty)

    return results


async def scenario_9_visibility_inputs(store: HierarchyStore) -> None:
    """project_visibilities and dataset_parents supply the visibility computation with its inputs.

    Two projects under one organization prove ``project_visibilities``
    names every seeded project with its owning organization and
    classification; ``dataset_parents`` resolves a known dataset id and
    silently omits an id that names nothing.
    """
    hierarchy = await seed_hierarchy(
        store, {"astro": {"sims": ("run-0001",), "obs": ("run-0002",)}}
    )
    visibilities = await store.project_visibilities()
    assert len(visibilities) == 2
    by_project = {visibility.project_id: visibility for visibility in visibilities}
    for project_slug in ("sims", "obs"):
        project_id = hierarchy.projects[project_slug]
        assert by_project[project_id].organization_id == hierarchy.organizations["astro"]
        assert by_project[project_id].classification == "open"

    known_dataset_id = hierarchy.datasets["run-0001"]
    parents = await store.dataset_parents(frozenset({known_dataset_id, uuid7()}))
    assert parents == {known_dataset_id: hierarchy.projects["sims"]}


def _manifest(paths: Sequence[str]) -> Manifest:
    """Build a manifest with one small, uniquely identified file per path.

    Args:
        paths: The payload paths to declare, each becoming one file.

    Returns:
        A manifest whose files hash distinctly by path, suitable for
        ``begin_ingest`` and ``compute_upload_plan``.
    """
    return Manifest(
        files=tuple(
            ManifestEntry(path=path, size=10, sha256=hashlib.sha256(path.encode()).hexdigest())
            for path in paths
        )
    )


def planned_files(manifest: Manifest) -> tuple[IngestFile, ...]:
    """Build the ledger rows an upload plan reserves for a manifest.

    Args:
        manifest: The manifest being ingested.

    Returns:
        One freshly identified, PENDING ``IngestFile`` per plan entry, in
        the plan's order.
    """
    plan = compute_upload_plan(manifest)
    return tuple(
        IngestFile(
            file_id=uuid7(),
            path=entry.file.path,
            size=entry.file.size,
            expected_sha256=entry.file.sha256,
            action=entry.action,
            part_count=entry.part_count,
        )
        for entry in plan
    )


def _complete_file() -> IngestFile:
    """Build an arbitrary already-COMPLETE file, for driving a session to VERIFYING.

    Returns:
        A one-part upload file recorded as fully received, not tied to any
        session's real ledger.
    """
    return IngestFile(
        file_id=uuid7(),
        path="payload/complete.bin",
        size=1,
        expected_sha256="a" * 64,
        action=UploadAction.UPLOAD,
        part_count=1,
        state=FileState.COMPLETE,
        completed_parts=frozenset({1}),
    )


def _walk_to_committing(
    session: IngestSession, *, manifest_sha256: str, now: datetime
) -> IngestSession:
    """Advance a PREPARING session straight to COMMITTING.

    Skips persisting the intermediate UPLOADING and VERIFYING edges, which
    the numbering and commit-transaction scenarios below have no need to
    observe.

    Args:
        session: The session to advance, currently PREPARING.
        manifest_sha256: The manifest identity to commit, checked against
            the session's declared one.
        now: The instant every edge is judged against.

    Returns:
        The session in COMMITTING, three edges and etags ahead.
    """
    uploading = session.open(now=now)
    verifying = uploading.verify((_complete_file(),), now=now)
    return verifying.begin_commit(manifest_sha256=manifest_sha256, now=now)


async def scenario_10_begin_ingest_reserves_and_locks(
    store: HierarchyStore, clock: FakeClock
) -> None:
    """begin_ingest reserves a gap-free number and locks the dataset until the session ends."""
    hierarchy = await seed_hierarchy(store, {"astro": {"sims": ("run-0001", "run-0002")}})
    locked_dataset_id = hierarchy.datasets["run-0001"]
    manifest = _manifest(("payload/a.bin", "payload/b.bin"))
    files = planned_files(manifest)

    async with store.transaction() as writer:
        session = await writer.begin_ingest(
            locked_dataset_id,
            manifest.sha256,
            created_by="user:alice",
            files=files,
        )
    assert session.lease.revision_number == 1
    assert session.state is IngestState.PREPARING
    assert session.etag == 1
    assert session.lease.expires_at == clock.now() + LEASE_TTL
    stored_files = await store.ingest_files(session.lease.ingest_id)
    assert [file.state for file in stored_files] == [FileState.PENDING, FileState.PENDING]
    assert [file.part_count for file in stored_files] == [file.part_count for file in files]

    with pytest.raises(DatasetLocked) as excinfo:
        async with store.transaction() as writer:
            await writer.begin_ingest(
                locked_dataset_id,
                "b" * 64,
                created_by="user:bob",
                files=(),
            )
    assert excinfo.value.context["session_id"] == str(session.lease.ingest_id)
    assert excinfo.value.context["state"] == "PREPARING"
    assert excinfo.value.context["expires_at"] == session.lease.expires_at.isoformat()

    clock.advance(LEASE_TTL * 2)
    with pytest.raises(DatasetLocked):
        async with store.transaction() as writer:
            await writer.begin_ingest(
                locked_dataset_id,
                "c" * 64,
                created_by="user:bob",
                files=(),
            )

    with pytest.raises(ResourceNotFound):
        async with store.transaction() as writer:
            await writer.begin_ingest(uuid7(), "d" * 64, created_by="user:carol", files=())

    open_dataset_id = hierarchy.datasets["run-0002"]
    committed = committed_revision(open_dataset_id, 1, manifest_sha256="e" * 64)
    async with store.transaction() as writer:
        await writer.insert_revision(committed)

    async with store.transaction() as writer:
        repeated = await writer.begin_ingest(
            open_dataset_id, "e" * 64, created_by="user:dana", files=()
        )
    assert repeated.lease.revision_number == 2


async def scenario_11_a_dead_session_frees_its_number_and_a_commit_spends_it(
    store: HierarchyStore, clock: FakeClock
) -> None:
    """An aborted session's number returns to the pool; a committed one keeps it spent."""
    hierarchy = await seed_hierarchy(store)
    dataset_id = hierarchy.datasets["run-0001"]

    async with store.transaction() as writer:
        first = await writer.begin_ingest(dataset_id, "a" * 64, created_by="user:alice", files=())
    assert first.lease.revision_number == 1
    async with store.transaction() as writer:
        await writer.update_ingest_session(first.abort(), expected_etag=first.etag)
    assert (await store.ingest_session(first.lease.ingest_id)).state is IngestState.ABORTED

    async with store.transaction() as writer:
        retry = await writer.begin_ingest(dataset_id, "b" * 64, created_by="user:alice", files=())
    assert retry.lease.revision_number == 1

    committing = _walk_to_committing(retry, manifest_sha256="b" * 64, now=clock.now())
    revision = committed_revision(
        dataset_id,
        retry.lease.revision_number,
        revision_id=retry.lease.revision_id,
        manifest_sha256="b" * 64,
    )
    async with store.transaction() as writer:
        await writer.insert_revision(revision)
        await writer.update_ingest_session(committing.commit(), expected_etag=retry.etag)

    async with store.transaction() as writer:
        second = await writer.begin_ingest(
            dataset_id,
            "c" * 64,
            created_by="user:alice",
            files=(),
        )
    assert second.lease.revision_number == 2

    second_committing = _walk_to_committing(second, manifest_sha256="c" * 64, now=clock.now())
    async with store.transaction() as writer:
        await writer.update_ingest_session(second_committing.fail(), expected_etag=second.etag)

    async with store.transaction() as writer:
        third = await writer.begin_ingest(
            dataset_id,
            "d" * 64,
            created_by="user:alice",
            files=(),
        )
    assert third.lease.revision_number == 2


async def scenario_12_state_edges_cas_on_etag_and_renew_does_not(
    store: HierarchyStore, clock: FakeClock
) -> None:
    """update_ingest_session CASes on etag; renew_ingest_session moves the lease, not the etag.

    A COMMITTING session still renews - only a terminal one refuses.
    """
    hierarchy = await seed_hierarchy(store)
    dataset_id = hierarchy.datasets["run-0001"]
    async with store.transaction() as writer:
        session = await writer.begin_ingest(dataset_id, "a" * 64, created_by="user:alice", files=())

    with pytest.raises(PreconditionFailed):
        async with store.transaction() as writer:
            await writer.update_ingest_session(session.open(now=clock.now()), expected_etag=99)
    unchanged = await store.ingest_session(session.lease.ingest_id)
    assert unchanged.state is IngestState.PREPARING
    assert unchanged.etag == session.etag

    phantom = dataclasses.replace(
        session, lease=dataclasses.replace(session.lease, ingest_id=uuid7())
    )
    with pytest.raises(PreconditionFailed):
        async with store.transaction() as writer:
            await writer.update_ingest_session(phantom.open(now=clock.now()), expected_etag=1)

    opened = session.open(now=clock.now())
    async with store.transaction() as writer:
        await writer.update_ingest_session(opened, expected_etag=session.etag)
    stored = await store.ingest_session(session.lease.ingest_id)
    assert stored.state is IngestState.UPLOADING
    assert stored.etag == opened.etag

    later = session.lease.expires_at + timedelta(hours=1)
    renewed_candidate = dataclasses.replace(
        opened, lease=dataclasses.replace(opened.lease, expires_at=later)
    )
    async with store.transaction() as writer:
        await writer.renew_ingest_session(renewed_candidate)
    renewed = await store.ingest_session(session.lease.ingest_id)
    assert renewed.lease.expires_at == later
    assert renewed.etag == opened.etag

    earlier_candidate = dataclasses.replace(
        opened, lease=dataclasses.replace(opened.lease, expires_at=session.lease.expires_at)
    )
    async with store.transaction() as writer:
        await writer.renew_ingest_session(earlier_candidate)
    unmoved = await store.ingest_session(session.lease.ingest_id)
    assert unmoved.lease.expires_at == later

    with pytest.raises(IngestSessionExpired):
        async with store.transaction() as writer:
            await writer.renew_ingest_session(phantom)

    aborted = renewed.abort()
    async with store.transaction() as writer:
        await writer.update_ingest_session(aborted, expected_etag=renewed.etag)
    with pytest.raises(IngestSessionExpired):
        async with store.transaction() as writer:
            await writer.renew_ingest_session(aborted)

    async with store.transaction() as writer:
        second = await writer.begin_ingest(dataset_id, "b" * 64, created_by="user:alice", files=())
    committing = _walk_to_committing(second, manifest_sha256="b" * 64, now=clock.now())
    async with store.transaction() as writer:
        await writer.update_ingest_session(committing, expected_etag=second.etag)

    still_later = committing.lease.expires_at + timedelta(hours=1)
    renewed_committing_candidate = dataclasses.replace(
        committing, lease=dataclasses.replace(committing.lease, expires_at=still_later)
    )
    async with store.transaction() as writer:
        await writer.renew_ingest_session(renewed_committing_candidate)
    renewed_committing = await store.ingest_session(second.lease.ingest_id)
    assert renewed_committing.state is IngestState.COMMITTING
    assert renewed_committing.lease.expires_at == still_later
    assert renewed_committing.etag == committing.etag


async def scenario_13_file_ledger_updates_fence_on_pending_and_parts(
    store: HierarchyStore, clock: FakeClock
) -> None:
    """update_ingest_file fences on the file being PENDING with exactly the expected parts."""
    hierarchy = await seed_hierarchy(store)
    dataset_id = hierarchy.datasets["run-0001"]
    manifest = _manifest(("payload/a.bin",))
    files = planned_files(manifest)
    async with store.transaction() as writer:
        session = await writer.begin_ingest(
            dataset_id,
            manifest.sha256,
            created_by="user:alice",
            files=files,
        )
    file_id = files[0].file_id

    with pytest.raises(PreconditionFailed):
        async with store.transaction() as writer:
            await writer.update_ingest_file(
                session.lease.ingest_id, files[0].part_received(1), expected_parts=frozenset({1})
            )

    with pytest.raises(PreconditionFailed):
        async with store.transaction() as writer:
            await writer.update_ingest_file(
                session.lease.ingest_id,
                dataclasses.replace(files[0], file_id=uuid7()).part_received(1),
                expected_parts=frozenset(),
            )

    advanced = files[0].part_received(1)
    async with store.transaction() as writer:
        await writer.update_ingest_file(
            session.lease.ingest_id, advanced, expected_parts=frozenset()
        )
    entry = await store.ingest_file(file_id)
    assert entry.ingest_id == session.lease.ingest_id
    assert entry.file.completed_parts == frozenset({1})
    assert entry.file.state is FileState.PENDING

    completed = advanced.completed(observed_size=10, observed_sha256=manifest.files[0].sha256)
    async with store.transaction() as writer:
        await writer.update_ingest_file(
            session.lease.ingest_id, completed, expected_parts=frozenset({1})
        )
    stored = await store.ingest_file(file_id)
    assert stored.file.state is FileState.COMPLETE

    with pytest.raises(PreconditionFailed):
        async with store.transaction() as writer:
            await writer.update_ingest_file(
                session.lease.ingest_id, completed, expected_parts=frozenset({1})
            )


async def scenario_14_the_commit_transaction_is_atomic_and_replays(
    store: HierarchyStore, clock: FakeClock
) -> None:
    """The commit transaction is atomic and a replayed claim returns the same revision."""
    hierarchy = await seed_hierarchy(store)
    dataset_id = hierarchy.datasets["run-0001"]
    async with store.transaction() as writer:
        session = await writer.begin_ingest(dataset_id, "a" * 64, created_by="user:alice", files=())
    committing = _walk_to_committing(session, manifest_sha256="a" * 64, now=clock.now())
    async with store.transaction() as writer:
        await writer.update_ingest_session(committing, expected_etag=session.etag)

    revision = committed_revision(
        dataset_id,
        session.lease.revision_number,
        revision_id=session.lease.revision_id,
        manifest_sha256="a" * 64,
    )
    claim = IdempotencyClaim(principal="user:alice", key="commit-1", request_sha256="1" * 64)

    with pytest.raises(_AbortedError):
        async with store.transaction() as writer:
            assert await writer.claim(claim) is None
            await writer.insert_revision(revision)
            raise _AbortedError

    with pytest.raises(ResourceNotFound):
        await store.revision(revision.id)
    rolled_back = await store.ingest_session(session.lease.ingest_id)
    assert rolled_back.state is IngestState.COMMITTING
    assert rolled_back.etag == committing.etag

    now = clock.now()
    audit = AuditEvent(
        id=uuid7(),
        kind="revision.committed",
        actor="user:alice",
        subject_kind="revision",
        subject_id=revision.id,
        payload={},
        created_at=now,
    )
    outbox = OutboxEvent(
        id=uuid7(), kind="revision.committed", subject_id=revision.id, payload={}, created_at=now
    )
    async with store.transaction() as writer:
        assert await writer.claim(claim) is None
        await writer.insert_revision(revision)
        await writer.update_ingest_session(committing.commit(), expected_etag=committing.etag)
        await writer.insert_audit_event(audit)
        await writer.insert_outbox_event(outbox)
        await writer.remember(claim, Replay(kind="revision", resource_id=revision.id))

    async with store.transaction() as writer:
        replay = await writer.claim(claim)
    assert replay == Replay(kind="revision", resource_id=revision.id)

    assert await store.revision(revision.id) == revision
    assert await store.latest_committed_revision(dataset_id) == revision
    assert await store.revision_ref(dataset_id, revision.number) == RevisionRef(
        id=revision.id,
        dataset_id=dataset_id,
        number=revision.number,
        manifest_sha256=revision.manifest_sha256,
    )

    duplicate = committed_revision(dataset_id, revision.number + 1, manifest_sha256="a" * 64)
    async with store.transaction() as writer:
        await writer.insert_revision(duplicate)
    assert await store.revision(duplicate.id) == duplicate


async def scenario_15_expiry_flips_lapsed_sessions_only(
    store: HierarchyStore, clock: FakeClock
) -> None:
    """lapsed_ingest_sessions lists only open, lapsed sessions, oldest first; expire flips one."""
    hierarchy = await seed_hierarchy(
        store, {"astro": {"sims": ("run-0001", "run-0002", "run-0003", "run-0004")}}
    )
    dataset_a = hierarchy.datasets["run-0001"]
    dataset_b = hierarchy.datasets["run-0002"]
    dataset_c = hierarchy.datasets["run-0003"]
    dataset_d = hierarchy.datasets["run-0004"]
    start = clock.now()

    assert await store.lapsed_ingest_sessions(start, limit=10) == ()

    async with store.transaction() as writer:
        session_a = await writer.begin_ingest(
            dataset_a, "a" * 64, created_by="user:alice", files=()
        )
    clock.set(start + timedelta(seconds=30))
    async with store.transaction() as writer:
        session_d = await writer.begin_ingest(
            dataset_d, "d" * 64, created_by="user:alice", files=()
        )
    clock.set(start + timedelta(minutes=1))
    async with store.transaction() as writer:
        session_b = await writer.begin_ingest(
            dataset_b, "b" * 64, created_by="user:alice", files=()
        )
    async with store.transaction() as writer:
        session_c = await writer.begin_ingest(
            dataset_c, "c" * 64, created_by="user:alice", files=()
        )
    committing_c = _walk_to_committing(session_c, manifest_sha256="c" * 64, now=clock.now())
    async with store.transaction() as writer:
        await writer.update_ingest_session(committing_c, expected_etag=session_c.etag)

    clock.set(start + LEASE_TTL + timedelta(seconds=30))
    renewed_b = session_b.renew(now=clock.now())
    async with store.transaction() as writer:
        await writer.renew_ingest_session(renewed_b)

    clock.set(start + LEASE_TTL + timedelta(minutes=2))
    lapsed = await store.lapsed_ingest_sessions(clock.now(), limit=10)
    assert [s.lease.ingest_id for s in lapsed] == [
        session_a.lease.ingest_id,
        session_d.lease.ingest_id,
    ]

    bounded = await store.lapsed_ingest_sessions(clock.now(), limit=1)
    assert [s.lease.ingest_id for s in bounded] == [session_a.lease.ingest_id]

    with pytest.raises(PreconditionFailed):
        async with store.transaction() as writer:
            await writer.expire_ingest_session(
                session_b.expire(now=clock.now()), expected_etag=session_b.etag, now=clock.now()
            )

    phantom_id = uuid7()
    phantom_expired = dataclasses.replace(
        session_a, lease=dataclasses.replace(session_a.lease, ingest_id=phantom_id)
    ).expire(now=clock.now())
    with pytest.raises(PreconditionFailed):
        async with store.transaction() as writer:
            await writer.expire_ingest_session(phantom_expired, expected_etag=1, now=clock.now())

    expired_a = session_a.expire(now=clock.now())
    async with store.transaction() as writer:
        await writer.expire_ingest_session(expired_a, expected_etag=session_a.etag, now=clock.now())
    assert (await store.ingest_session(session_a.lease.ingest_id)).state is IngestState.ABORTED

    async with store.transaction() as writer:
        retaken = await writer.begin_ingest(dataset_a, "e" * 64, created_by="user:alice", files=())
    assert retaken.lease.revision_number == session_a.lease.revision_number


async def scenario_16_a_hundred_sequential_ingests_number_gap_free(
    store: HierarchyStore, clock: FakeClock
) -> None:
    """100 sequential ingests number 1..100 gap-free, even with a failed attempt every tenth."""
    hierarchy = await seed_hierarchy(store)
    dataset_id = hierarchy.datasets["run-0001"]

    for number in range(1, 101):
        manifest_sha256 = format(number, "064x")
        if number % 10 == 0:
            async with store.transaction() as writer:
                doomed = await writer.begin_ingest(
                    dataset_id,
                    manifest_sha256,
                    created_by="user:alice",
                    files=(),
                )
            assert doomed.lease.revision_number == number
            async with store.transaction() as writer:
                await writer.update_ingest_session(doomed.fail(), expected_etag=doomed.etag)

        async with store.transaction() as writer:
            session = await writer.begin_ingest(
                dataset_id,
                manifest_sha256,
                created_by="user:alice",
                files=(),
            )
        assert session.lease.revision_number == number
        committing = _walk_to_committing(session, manifest_sha256=manifest_sha256, now=clock.now())
        revision = committed_revision(
            dataset_id,
            number,
            revision_id=session.lease.revision_id,
            manifest_sha256=manifest_sha256,
        )
        async with store.transaction() as writer:
            await writer.insert_revision(revision)
            await writer.update_ingest_session(committing.commit(), expected_etag=session.etag)

    latest = await store.latest_committed_revision(dataset_id)
    assert latest is not None
    assert latest.number == 100
