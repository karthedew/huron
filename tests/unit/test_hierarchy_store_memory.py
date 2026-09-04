"""Direct unit tests for ``InMemoryHierarchyStore``.

The transaction, uniqueness, optimistic-concurrency, idempotency and
revision-resolution contracts are pinned once, in ``tests/hierarchy_contract.py``,
and run here against the in-memory store; this module adds what is specific
to this backend - the injectable clock's 24-hour TTL boundary - and direct
coverage of the reads and seeding method the shared scenarios do not
otherwise exercise (point-read failures, window ordering, the three
visibility predicates, and ``register_revision``'s own refusals).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from huron.pkg.catalog.errors import ResourceNotFound
from huron.pkg.catalog.ids import uuid7
from huron.pkg.catalog.models import RevisionRef
from huron.pkg.rbac import Visibility
from huron.service.api.records import Organization, Release
from huron.service.api.stores.hierarchy import InMemoryHierarchyStore
from huron.service.api.stores.ports import IdempotencyClaim, Replay
from tests.hierarchy_contract import (
    scenario_1_write_invisible_until_commit,
    scenario_2_uniqueness,
    scenario_3_optimistic_concurrency,
    scenario_4_idempotency,
    scenario_5_revisions,
    scenario_6_ordering,
    scenario_7_windows,
    scenario_8_visibility,
    scenario_9_visibility_inputs,
    seed_hierarchy,
)

if TYPE_CHECKING:
    from uuid import UUID

pytestmark = pytest.mark.unit

#: Two organizations, three projects and four datasets, deep enough to
#: exercise ordering and every visibility predicate's fallback branch.
_TREE = {
    "org-a": {"proj-a1": ("ds-a1x", "ds-a1y"), "proj-a2": ("ds-a2x",)},
    "org-b": {"proj-b1": ("ds-b1x",)},
}


@dataclass(slots=True)
class _FakeClock:
    """A ``Clock`` whose ``now()`` returns a value the test advances explicitly."""

    _now: datetime

    def now(self) -> datetime:
        """Return the clock's current instant."""
        return self._now

    def advance(self, delta: timedelta) -> None:
        """Move the clock forward by ``delta``."""
        self._now += delta


def _release(dataset_id: UUID, tag: str, revision: RevisionRef) -> Release:
    """Build a ``Release`` citing ``revision``, ready to insert."""
    return Release(
        id=uuid7(),
        dataset_id=dataset_id,
        tag=tag,
        revision_id=revision.id,
        revision_number=revision.number,
        title=None,
        created_by="user:test",
        created_at=datetime.now(UTC),
    )


async def test_a_write_is_invisible_until_commit_and_vanishes_on_rollback() -> None:
    """Pins the transaction-atomicity contract against the in-memory store."""
    store = InMemoryHierarchyStore()
    await scenario_1_write_invisible_until_commit(store, store.register_revision)


async def test_a_duplicate_slug_or_tag_under_the_same_parent_is_refused() -> None:
    """Pins the uniqueness contract against the in-memory store."""
    store = InMemoryHierarchyStore()
    await scenario_2_uniqueness(store, store.register_revision)


async def test_update_succeeds_at_the_current_version_and_fails_at_a_stale_one() -> None:
    """Pins the optimistic-concurrency contract against the in-memory store."""
    store = InMemoryHierarchyStore()
    await scenario_3_optimistic_concurrency(store, store.register_revision)


async def test_idempotency_claims_replay_reject_and_serialize_across_transactions() -> None:
    """Pins the idempotency contract against the in-memory store."""
    store = InMemoryHierarchyStore()
    await scenario_4_idempotency(store, store.register_revision)


async def test_revision_ref_resolves_a_seeded_revision_and_gates_release_creation() -> None:
    """Pins the revision-resolution contract against the in-memory store."""
    store = InMemoryHierarchyStore()
    await scenario_5_revisions(store, store.register_revision)


async def test_organizations_projects_datasets_and_releases_sort_by_c_collation_order() -> None:
    """Pins the ordering contract against the in-memory store."""
    store = InMemoryHierarchyStore()
    await scenario_6_ordering(store, store.register_revision)


async def test_windows_respect_limit_has_more_and_an_exclusive_after() -> None:
    """Pins the window-arithmetic contract against the in-memory store."""
    store = InMemoryHierarchyStore()
    await scenario_7_windows(store, store.register_revision)


async def test_the_three_visibility_rules_hold_at_every_level() -> None:
    """Pins the visibility contract against the in-memory store."""
    store = InMemoryHierarchyStore()
    await scenario_8_visibility(store, store.register_revision)


async def test_project_visibilities_and_dataset_parents_feed_visibility_computation() -> None:
    """Pins project_visibilities and dataset_parents against the in-memory store."""
    store = InMemoryHierarchyStore()
    await scenario_9_visibility_inputs(store, store.register_revision)


async def test_an_expired_claim_is_taken_over_rather_than_rejected() -> None:
    """A claim older than 24 hours is silently replaced, even by a mismatched retry."""
    clock = _FakeClock(datetime(2026, 1, 1, tzinfo=UTC))
    store = InMemoryHierarchyStore(clock=clock)
    claim = IdempotencyClaim(principal="user:alice", key="create-astro", request_sha256="sha-a")
    first_id = uuid7()
    async with store.transaction() as writer:
        assert await writer.claim(claim) is None
        await writer.insert_organization(
            Organization(
                id=first_id,
                slug="astro",
                title="astro",
                description="",
                generation=1,
                version=1,
                created_at=datetime.now(UTC),
            )
        )
        await writer.remember(claim, Replay(kind="organization", resource_id=first_id))

    clock.advance(timedelta(hours=24, seconds=1))

    retry = IdempotencyClaim(principal="user:alice", key="create-astro", request_sha256="sha-b")
    second_id = uuid7()
    async with store.transaction() as writer:
        assert await writer.claim(retry) is None
        await writer.insert_organization(
            Organization(
                id=second_id,
                slug="astro-2",
                title="astro-2",
                description="",
                generation=1,
                version=1,
                created_at=datetime.now(UTC),
            )
        )
        await writer.remember(retry, Replay(kind="organization", resource_id=second_id))

    replayed = await store.organization(second_id, Visibility.ALL)
    assert replayed.id == second_id


async def test_register_revision_rejects_an_unknown_dataset() -> None:
    """register_revision refuses a revision for a dataset the store has never seen."""
    store = InMemoryHierarchyStore()
    revision = RevisionRef(id=uuid7(), dataset_id=uuid7(), number=1, manifest_sha256="a" * 64)
    with pytest.raises(ResourceNotFound):
        await store.register_revision(revision)


async def test_register_revision_rejects_a_duplicate_dataset_and_number() -> None:
    """register_revision refuses to register the same (dataset, number) pair twice."""
    store = InMemoryHierarchyStore()
    hierarchy = await seed_hierarchy(store)
    dataset_id = hierarchy.datasets["run-0001"]
    revision = RevisionRef(id=uuid7(), dataset_id=dataset_id, number=1, manifest_sha256="a" * 64)
    await store.register_revision(revision)
    duplicate = RevisionRef(id=uuid7(), dataset_id=dataset_id, number=1, manifest_sha256="b" * 64)
    with pytest.raises(RuntimeError):
        await store.register_revision(duplicate)


async def test_a_registered_revision_is_exactly_what_revision_ref_returns() -> None:
    """A registered revision round-trips unchanged through revision_ref."""
    store = InMemoryHierarchyStore()
    hierarchy = await seed_hierarchy(store)
    dataset_id = hierarchy.datasets["run-0001"]
    revision = RevisionRef(id=uuid7(), dataset_id=dataset_id, number=1, manifest_sha256="a" * 64)
    await store.register_revision(revision)
    assert await store.revision_ref(dataset_id, 1) == revision


async def test_organization_point_read_raises_for_an_unknown_id() -> None:
    """organization() reports an id that names nothing as not found."""
    store = InMemoryHierarchyStore()
    with pytest.raises(ResourceNotFound):
        await store.organization(uuid7(), Visibility.ALL)


async def test_project_point_read_raises_for_an_unknown_id() -> None:
    """project() reports an id that names nothing as not found."""
    store = InMemoryHierarchyStore()
    with pytest.raises(ResourceNotFound):
        await store.project(uuid7(), Visibility.ALL)


async def test_dataset_point_read_raises_for_an_unknown_id() -> None:
    """dataset() reports an id that names nothing as not found."""
    store = InMemoryHierarchyStore()
    with pytest.raises(ResourceNotFound):
        await store.dataset(uuid7(), Visibility.ALL)


async def test_release_point_read_raises_for_an_unknown_tag() -> None:
    """release() reports a tag that names nothing as not found."""
    store = InMemoryHierarchyStore()
    hierarchy = await seed_hierarchy(store)
    dataset_id = hierarchy.datasets["run-0001"]
    with pytest.raises(ResourceNotFound):
        await store.release(dataset_id, "missing", Visibility.ALL)


async def test_organizations_window_orders_by_slug_and_admits_only_visible_rows() -> None:
    """organizations() sorts by (slug, id) and only counts what visibility admits."""
    store = InMemoryHierarchyStore()
    hierarchy = await seed_hierarchy(store, _TREE)
    restricted = Visibility(organization_ids=frozenset({hierarchy.organizations["org-a"]}))
    window = await store.organizations(restricted, limit=10, after=None)
    assert [item.slug for item in window.items] == ["org-a"]
    assert window.has_more is False


async def test_projects_window_admits_a_project_named_directly() -> None:
    """projects() admits a project named by visibility.project_ids directly."""
    store = InMemoryHierarchyStore()
    hierarchy = await seed_hierarchy(store, _TREE)
    restricted = Visibility(project_ids=frozenset({hierarchy.projects["proj-a1"]}))
    window = await store.projects(
        hierarchy.organizations["org-a"], restricted, limit=10, after=None
    )
    assert [item.slug for item in window.items] == ["proj-a1"]


async def test_datasets_window_admits_a_dataset_named_directly() -> None:
    """datasets() sorts by (slug, id) and admits a dataset named by visibility.dataset_ids."""
    store = InMemoryHierarchyStore()
    hierarchy = await seed_hierarchy(store, _TREE)
    restricted = Visibility(dataset_ids=frozenset({hierarchy.datasets["ds-a1y"]}))
    window = await store.datasets(hierarchy.projects["proj-a1"], restricted, limit=10, after=None)
    assert [item.slug for item in window.items] == ["ds-a1y"]


async def test_a_project_is_visible_when_it_contains_a_directly_visible_dataset() -> None:
    """A project outside project_ids is still visible when one of its datasets is."""
    store = InMemoryHierarchyStore()
    hierarchy = await seed_hierarchy(store, _TREE)
    restricted = Visibility(dataset_ids=frozenset({hierarchy.datasets["ds-a1x"]}))
    project = await store.project(hierarchy.projects["proj-a1"], restricted)
    assert project.slug == "proj-a1"
    with pytest.raises(ResourceNotFound):
        await store.project(hierarchy.projects["proj-a2"], restricted)


async def test_an_organization_is_visible_when_it_contains_a_visible_project() -> None:
    """An organization outside organization_ids is still visible when one of its projects is."""
    store = InMemoryHierarchyStore()
    hierarchy = await seed_hierarchy(store, _TREE)
    restricted = Visibility(project_ids=frozenset({hierarchy.projects["proj-a1"]}))
    organization = await store.organization(hierarchy.organizations["org-a"], restricted)
    assert organization.slug == "org-a"
    with pytest.raises(ResourceNotFound):
        await store.organization(hierarchy.organizations["org-b"], restricted)


async def test_empty_visibility_admits_nothing() -> None:
    """Visibility() with every id set empty and unrestricted False admits nothing at any level."""
    store = InMemoryHierarchyStore()
    hierarchy = await seed_hierarchy(store, _TREE)
    empty = Visibility()
    with pytest.raises(ResourceNotFound):
        await store.organization(hierarchy.organizations["org-a"], empty)
    with pytest.raises(ResourceNotFound):
        await store.project(hierarchy.projects["proj-a1"], empty)
    with pytest.raises(ResourceNotFound):
        await store.dataset(hierarchy.datasets["ds-a1x"], empty)


async def test_releases_window_orders_by_tag_regardless_of_visibility() -> None:
    """releases() sorts by tag and lists every release of the named dataset."""
    store = InMemoryHierarchyStore()
    hierarchy = await seed_hierarchy(store)
    dataset_id = hierarchy.datasets["run-0001"]
    revision = RevisionRef(id=uuid7(), dataset_id=dataset_id, number=1, manifest_sha256="a" * 64)
    await store.register_revision(revision)
    async with store.transaction() as writer:
        await writer.insert_release(_release(dataset_id, "v2", revision))
        await writer.insert_release(_release(dataset_id, "v1", revision))
    window = await store.releases(dataset_id, Visibility.ALL, limit=10, after=None)
    assert [item.tag for item in window.items] == ["v1", "v2"]


async def test_a_limit_one_walk_visits_every_dataset_exactly_once() -> None:
    """A limit=1 walk, following has_more and the last row's key, visits every row exactly once."""
    store = InMemoryHierarchyStore()
    hierarchy = await seed_hierarchy(store, _TREE)
    seen: list[str] = []
    after: tuple[str, UUID] | None = None
    while True:
        window = await store.datasets(
            hierarchy.projects["proj-a1"], Visibility.ALL, limit=1, after=after
        )
        seen.extend(item.slug for item in window.items)
        if not window.has_more:
            break
        after = (window.items[-1].slug, window.items[-1].id)
    assert seen == ["ds-a1x", "ds-a1y"]


async def test_project_visibilities_lists_every_project_with_its_classification() -> None:
    """project_visibilities() returns one entry per project, whatever the caller's visibility."""
    store = InMemoryHierarchyStore()
    hierarchy = await seed_hierarchy(store, _TREE)
    visibilities = await store.project_visibilities()
    assert len(visibilities) == 3
    by_id = {v.project_id: v for v in visibilities}
    project_a1_id = hierarchy.projects["proj-a1"]
    assert by_id[project_a1_id].organization_id == hierarchy.organizations["org-a"]
    assert by_id[project_a1_id].classification == "open"


async def test_dataset_parents_maps_only_the_ids_that_exist() -> None:
    """dataset_parents() resolves known ids and silently omits an unknown one."""
    store = InMemoryHierarchyStore()
    hierarchy = await seed_hierarchy(store, _TREE)
    parents = await store.dataset_parents(frozenset({hierarchy.datasets["ds-a1x"], uuid7()}))
    assert parents == {hierarchy.datasets["ds-a1x"]: hierarchy.projects["proj-a1"]}
