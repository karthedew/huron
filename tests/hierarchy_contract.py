"""Scenarios pinning ``HierarchyStore`` behavior, run against every backend.

Each ``scenario_*`` function proves one explicit contract of the port -
transaction atomicity, uniqueness, optimistic concurrency, idempotency,
ordering, windowing and the three visibility rules -
against whatever store it is handed, so the same assertions run for the
in-memory reference store and for a durable backend without being written
twice. ``seed_hierarchy`` builds the small organization/project/dataset
tree the scenarios and their callers need.
"""

from __future__ import annotations

import asyncio
import dataclasses
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from huron.core.hierarchy.errors import SlugExists
from huron.core.hierarchy.layers import Layer
from huron.core.hierarchy.lifecycle import DatasetLifecycle
from huron.core.hierarchy.types import Dataset, Organization, PlatformRoot, Project
from huron.core.foundation.errors import IdempotencyKeyReused, PreconditionFailed, ResourceNotFound
from huron.core.foundation.identifiers import uuid7
from huron.core.foundation.retry import IdempotencyClaim, Replay
from huron.core.security.rules import Visibility

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
    from uuid import UUID

    from huron.applications.api.capabilities import HierarchyStore


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
            await store.organizations.get(organization.id, Visibility.ALL)
    committed = await store.organizations.get(organization.id, Visibility.ALL)
    assert committed.id == organization.id

    doomed = _organization(slug="doomed")
    with pytest.raises(_AbortedError):
        async with store.transaction() as writer:
            await writer.insert_organization(doomed)
            raise _AbortedError
    with pytest.raises(ResourceNotFound):
        await store.organizations.get(doomed.id, Visibility.ALL)


async def scenario_2_uniqueness(store: HierarchyStore) -> None:
    """A duplicate slug under the same parent is refused; a different parent is not."""
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
        await writer.organizations.describe(updated_organization, expected_version=1)
    read_organization = await store.organizations.get(organization.id, Visibility.ALL)
    assert read_organization.title == "Astro II"
    assert read_organization.version == 2

    with pytest.raises(PreconditionFailed):
        async with store.transaction() as writer:
            await writer.organizations.describe(
                dataclasses.replace(updated_organization, title="lost", version=3, generation=3),
                expected_version=1,
            )
    unchanged_organization = await store.organizations.get(organization.id, Visibility.ALL)
    assert unchanged_organization.title == "Astro II"
    assert unchanged_organization.version == 2

    with pytest.raises(PreconditionFailed):
        async with store.transaction() as writer:
            await writer.organizations.describe(
                dataclasses.replace(organization, id=uuid7(), version=2, generation=2),
                expected_version=1,
            )

    updated_project = dataclasses.replace(project, title="Sims II", version=2, generation=2)
    async with store.transaction() as writer:
        await writer.projects.describe(updated_project, expected_version=1)
    read_project = await store.projects.get(project.id, Visibility.ALL)
    assert read_project.title == "Sims II"

    with pytest.raises(PreconditionFailed):
        async with store.transaction() as writer:
            await writer.projects.describe(
                dataclasses.replace(updated_project, title="lost", version=3, generation=3),
                expected_version=1,
            )
    assert (await store.projects.get(project.id, Visibility.ALL)).title == "Sims II"

    updated_dataset = dataclasses.replace(dataset, title="Run 1", version=2, generation=2)
    async with store.transaction() as writer:
        await writer.datasets.describe(updated_dataset, expected_version=1)
    read_dataset = await store.datasets.get(dataset.id, Visibility.ALL)
    assert read_dataset.title == "Run 1"

    with pytest.raises(PreconditionFailed):
        async with store.transaction() as writer:
            await writer.datasets.describe(
                dataclasses.replace(updated_dataset, title="lost", version=3, generation=3),
                expected_version=1,
            )
    assert (await store.datasets.get(dataset.id, Visibility.ALL)).title == "Run 1"

    with pytest.raises(PreconditionFailed):
        async with store.transaction() as writer:
            await writer.projects.describe(
                dataclasses.replace(project, id=uuid7(), version=2, generation=2),
                expected_version=1,
            )
    with pytest.raises(PreconditionFailed):
        async with store.transaction() as writer:
            await writer.datasets.describe(
                dataclasses.replace(dataset, id=uuid7(), version=2, generation=2),
                expected_version=1,
            )

    with pytest.raises(PreconditionFailed):
        async with store.transaction() as writer:
            await writer.organizations.describe(
                dataclasses.replace(updated_organization, title="rolled back", version=3),
                expected_version=2,
            )
            await writer.projects.describe(
                dataclasses.replace(updated_project, title="rolled back", version=3),
                expected_version=2,
            )
            await writer.datasets.describe(
                dataclasses.replace(updated_dataset, title="stale", version=3),
                expected_version=1,
            )
    assert await store.organizations.get(organization.id, Visibility.ALL) == updated_organization
    assert await store.projects.get(project.id, Visibility.ALL) == updated_project
    assert await store.datasets.get(dataset.id, Visibility.ALL) == updated_dataset


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
    window = await store.organizations.browse(
        PlatformRoot.ROOT, Visibility.ALL, limit=200, after=None
    )
    assert sum(1 for item in window.items if item.slug == "race") == 1


async def scenario_6_ordering(store: HierarchyStore) -> None:
    """Organizations, projects and datasets sort by (slug, id), not insertion order.

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

    organizations = await store.organizations.browse(
        PlatformRoot.ROOT, Visibility.ALL, limit=200, after=None
    )
    assert [item.slug for item in organizations.items] == expected

    projects = await store.projects.browse(
        hierarchy.organizations["a-1"], Visibility.ALL, limit=200, after=None
    )
    assert [item.slug for item in projects.items] == expected

    datasets = await store.datasets.browse(
        hierarchy.projects["a-1"], Visibility.ALL, limit=200, after=None
    )
    assert [item.slug for item in datasets.items] == expected


async def scenario_7_windows(store: HierarchyStore) -> None:
    """A window returns at most limit items, has_more tracks what remains, and after is exclusive.

    Five organizations are seeded - enough for a partial page, a full page
    and a limit=1 walk without being unwieldy - and every window and walk
    below is asserted against Python's own ``sorted`` order on their slugs.
    """
    slugs = ("org-1", "org-2", "org-3", "org-4", "org-5")
    await seed_hierarchy(store, {slug: {} for slug in slugs})
    ordered = sorted(slugs)

    partial = await store.organizations.browse(
        PlatformRoot.ROOT, Visibility.ALL, limit=3, after=None
    )
    assert [item.slug for item in partial.items] == ordered[:3]
    assert partial.has_more is True

    exact = await store.organizations.browse(
        PlatformRoot.ROOT, Visibility.ALL, limit=len(slugs), after=None
    )
    assert [item.slug for item in exact.items] == ordered
    assert exact.has_more is False

    generous = await store.organizations.browse(
        PlatformRoot.ROOT, Visibility.ALL, limit=200, after=None
    )
    assert [item.slug for item in generous.items] == ordered
    assert generous.has_more is False

    first = partial.items[0]
    after_first = await store.organizations.browse(
        PlatformRoot.ROOT, Visibility.ALL, limit=200, after=(first.slug, first.id)
    )
    assert first.slug not in {item.slug for item in after_first.items}
    assert [item.slug for item in after_first.items] == ordered[1:]

    last = exact.items[-1]
    after_last = await store.organizations.browse(
        PlatformRoot.ROOT, Visibility.ALL, limit=200, after=(last.slug, last.id)
    )
    assert after_last.items == []
    assert after_last.has_more is False

    seen: list[str] = []
    after: tuple[str, UUID] | None = None
    while True:
        window = await store.organizations.browse(
            PlatformRoot.ROOT, Visibility.ALL, limit=1, after=after
        )
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
    """

    organizations: frozenset[UUID]
    projects: frozenset[UUID]
    datasets: frozenset[UUID]


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

    async def visible_ids(visibility: Visibility) -> VisibleIds:
        """Compute the ids ``visibility`` admits at every level of the fixture."""
        organizations = await store.organizations.browse(
            PlatformRoot.ROOT, visibility, limit=200, after=None
        )
        projects_a = await store.projects.browse(org_a_id, visibility, limit=200, after=None)
        projects_b = await store.projects.browse(org_b_id, visibility, limit=200, after=None)
        projects_c = await store.projects.browse(org_c_id, visibility, limit=200, after=None)
        datasets_a1 = await store.datasets.browse(a1_id, visibility, limit=200, after=None)
        datasets_a2 = await store.datasets.browse(a2_id, visibility, limit=200, after=None)
        datasets_b1 = await store.datasets.browse(b1_id, visibility, limit=200, after=None)
        datasets_c1 = await store.datasets.browse(c1_id, visibility, limit=200, after=None)
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
    assert (await store.organizations.get(org_a_id, all_visibility)).id == org_a_id
    assert (await store.organizations.get(org_b_id, all_visibility)).id == org_b_id
    assert (await store.organizations.get(org_c_id, all_visibility)).id == org_c_id
    assert (await store.projects.get(a1_id, all_visibility)).id == a1_id
    assert (await store.projects.get(a2_id, all_visibility)).id == a2_id
    assert (await store.projects.get(b1_id, all_visibility)).id == b1_id
    assert (await store.projects.get(c1_id, all_visibility)).id == c1_id
    assert (await store.datasets.get(a1ds_id, all_visibility)).id == a1ds_id
    assert (await store.datasets.get(a2ds_id, all_visibility)).id == a2ds_id
    assert (await store.datasets.get(b1ds_id, all_visibility)).id == b1ds_id
    assert (await store.datasets.get(c1ds_id, all_visibility)).id == c1ds_id

    project_scoped = Visibility(project_ids=frozenset({a1_id}))
    results["project_ids"] = await visible_ids(project_scoped)
    assert results["project_ids"].organizations == frozenset({org_a_id})
    assert results["project_ids"].projects == frozenset({a1_id})
    assert results["project_ids"].datasets == frozenset({a1ds_id})
    assert (await store.organizations.get(org_a_id, project_scoped)).id == org_a_id
    assert (await store.projects.get(a1_id, project_scoped)).id == a1_id
    assert (await store.datasets.get(a1ds_id, project_scoped)).id == a1ds_id
    await assert_invisible(store.organizations.get, (org_b_id, org_c_id), project_scoped)
    await assert_invisible(store.projects.get, (a2_id, b1_id, c1_id), project_scoped)
    await assert_invisible(store.datasets.get, (a2ds_id, b1ds_id, c1ds_id), project_scoped)

    dataset_scoped = Visibility(dataset_ids=frozenset({a2ds_id, a2du_id, c1ds_id}))
    results["dataset_ids"] = await visible_ids(dataset_scoped)
    assert results["dataset_ids"].organizations == frozenset({org_a_id, org_c_id})
    assert results["dataset_ids"].projects == frozenset({a2_id, c1_id})
    assert results["dataset_ids"].datasets == frozenset({a2ds_id, a2du_id, c1ds_id})
    assert (await store.organizations.get(org_a_id, dataset_scoped)).id == org_a_id
    assert (await store.organizations.get(org_c_id, dataset_scoped)).id == org_c_id
    assert (await store.projects.get(a2_id, dataset_scoped)).id == a2_id
    assert (await store.projects.get(c1_id, dataset_scoped)).id == c1_id
    assert (await store.datasets.get(a2ds_id, dataset_scoped)).id == a2ds_id
    assert (await store.datasets.get(a2du_id, dataset_scoped)).id == a2du_id
    assert (await store.datasets.get(c1ds_id, dataset_scoped)).id == c1ds_id
    await assert_invisible(store.projects.get, (a1_id, b1_id), dataset_scoped)
    await assert_invisible(store.datasets.get, (a1ds_id, a2dt_id, b1ds_id), dataset_scoped)
    await assert_invisible(store.organizations.get, (org_b_id,), dataset_scoped)

    narrow_projects = await store.projects.browse(org_a_id, dataset_scoped, limit=1, after=None)
    assert [item.id for item in narrow_projects.items] == [a2_id]
    assert narrow_projects.has_more is False

    walked_dataset_ids: list[UUID] = []
    walk_after: tuple[str, UUID] | None = None
    while True:
        window = await store.datasets.browse(a2_id, dataset_scoped, limit=1, after=walk_after)
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
        window = await store.organizations.browse(
            PlatformRoot.ROOT, dataset_scoped, limit=1, after=organization_walk_after
        )
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
    assert (await store.organizations.get(org_a_id, organization_scoped)).id == org_a_id
    await assert_invisible(store.organizations.get, (org_b_id, org_c_id), organization_scoped)
    await assert_invisible(store.projects.get, (a1_id, a2_id, b1_id, c1_id), organization_scoped)
    await assert_invisible(
        store.datasets.get, (a1ds_id, a2ds_id, b1ds_id, c1ds_id), organization_scoped
    )

    empty = Visibility()
    results["empty"] = await visible_ids(empty)
    assert results["empty"].organizations == frozenset()
    assert results["empty"].projects == frozenset()
    assert results["empty"].datasets == frozenset()
    await assert_invisible(store.organizations.get, (org_a_id, org_b_id, org_c_id), empty)
    await assert_invisible(store.projects.get, (a1_id, a2_id, b1_id, c1_id), empty)
    await assert_invisible(store.datasets.get, (a1ds_id, a2ds_id, b1ds_id, c1ds_id), empty)

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
