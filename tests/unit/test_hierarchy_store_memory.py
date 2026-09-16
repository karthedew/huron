"""Direct unit tests for ``InMemoryHierarchyStore``.

The transaction, uniqueness, optimistic-concurrency, idempotency,
revision-resolution and ingest contracts are pinned once, in
``tests/hierarchy_contract.py``, and run here against the in-memory store;
this module adds what is specific to this backend - the injectable clock's
24-hour TTL boundary and default, transactional revision insertion, direct
coverage of the reads window ordering and the three visibility predicates
the shared scenarios do not otherwise exercise, and the point reads' not-found
paths the ingest scenarios have no reason to hit.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from huron.core.foundation.errors import IdempotencyKeyReused, ResourceNotFound
from huron.core.foundation.identifiers import uuid7
from huron.core.raw.types import OutboxEvent, AuditEvent, Release
from huron.core.foundation.retry import IdempotencyClaim, Replay
from huron.core.catalog.types import PlatformRoot, Organization
from huron.core.metastore.hierarchy import InMemoryHierarchyStore, SystemClock
from huron.core.security.rules import Visibility
from tests.hierarchy_contract import (
    committed_revision,
    scenario_1_write_invisible_until_commit,
    scenario_2_uniqueness,
    scenario_3_optimistic_concurrency,
    scenario_4_idempotency,
    scenario_5_revisions,
    scenario_6_ordering,
    scenario_7_windows,
    scenario_8_visibility,
    scenario_9_visibility_inputs,
    scenario_10_begin_ingest_reserves_and_locks,
    scenario_11_a_dead_session_frees_its_number_and_a_commit_spends_it,
    scenario_12_state_edges_cas_on_etag_and_renew_does_not,
    scenario_13_file_ledger_updates_fence_on_pending_and_parts,
    scenario_14_the_commit_transaction_is_atomic_and_replays,
    scenario_15_expiry_flips_lapsed_sessions_only,
    scenario_16_a_hundred_sequential_ingests_number_gap_free,
    seed_hierarchy,
)
from tests.unit.support import FakeClock

if TYPE_CHECKING:
    from uuid import UUID

pytestmark = pytest.mark.unit

#: Two organizations, three projects and four datasets, deep enough to
#: exercise ordering and every visibility predicate's fallback branch.
_TREE = {
    "org-a": {"proj-a1": ("ds-a1x", "ds-a1y"), "proj-a2": ("ds-a2x",)},
    "org-b": {"proj-b1": ("ds-b1x",)},
}


def _release(dataset_id: UUID, tag: str, revision_id: UUID, revision_number: int) -> Release:
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


async def test_a_write_is_invisible_until_commit_and_vanishes_on_rollback() -> None:
    """Pins the transaction-atomicity contract against the in-memory store."""
    store = InMemoryHierarchyStore()
    await scenario_1_write_invisible_until_commit(store)


async def test_a_duplicate_slug_or_tag_under_the_same_parent_is_refused() -> None:
    """Pins the uniqueness contract against the in-memory store."""
    store = InMemoryHierarchyStore()
    await scenario_2_uniqueness(store)


async def test_update_succeeds_at_the_current_version_and_fails_at_a_stale_one() -> None:
    """Pins the optimistic-concurrency contract against the in-memory store."""
    store = InMemoryHierarchyStore()
    await scenario_3_optimistic_concurrency(store)


async def test_idempotency_claims_replay_reject_and_serialize_across_transactions() -> None:
    """Pins the idempotency contract against the in-memory store."""
    store = InMemoryHierarchyStore()
    await scenario_4_idempotency(store)


async def test_revision_ref_resolves_a_committed_revision_and_gates_release_creation() -> None:
    """Pins the revision-resolution contract against the in-memory store."""
    store = InMemoryHierarchyStore()
    await scenario_5_revisions(store)


async def test_organizations_projects_datasets_and_releases_sort_by_c_collation_order() -> None:
    """Pins the ordering contract against the in-memory store."""
    store = InMemoryHierarchyStore()
    await scenario_6_ordering(store)


async def test_windows_respect_limit_has_more_and_an_exclusive_after() -> None:
    """Pins the window-arithmetic contract against the in-memory store."""
    store = InMemoryHierarchyStore()
    await scenario_7_windows(store)


async def test_the_three_visibility_rules_hold_at_every_level() -> None:
    """Pins the visibility contract against the in-memory store."""
    store = InMemoryHierarchyStore()
    await scenario_8_visibility(store)


async def test_project_visibilities_and_dataset_parents_feed_visibility_computation() -> None:
    """Pins project_visibilities and dataset_parents against the in-memory store."""
    store = InMemoryHierarchyStore()
    await scenario_9_visibility_inputs(store)


async def test_an_expired_claim_is_taken_over_rather_than_rejected() -> None:
    """A claim older than 24 hours is silently replaced, even by a mismatched retry."""
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=UTC))
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

    replayed = await store.organizations.get(second_id, Visibility.ALL)
    assert replayed.id == second_id


async def test_an_unfinished_commit_claim_cannot_expire_before_its_revision_receipt() -> None:
    """Elapsed retry TTL cannot release a key while publication is still unresolved."""
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=UTC))
    store = InMemoryHierarchyStore(clock=clock)
    claim = IdempotencyClaim("user:alice", "commit", "a" * 64)
    pending = Replay(kind="ingest_commit", resource_id=uuid7())
    async with store.transaction() as writer:
        assert await writer.claim(claim) is None
        await writer.remember(claim, pending)
    clock.advance(timedelta(days=2))
    conflicting = IdempotencyClaim(claim.principal, claim.key, "b" * 64)
    with pytest.raises(IdempotencyKeyReused):
        async with store.transaction() as writer:
            await writer.claim(conflicting)
    async with store.transaction() as writer:
        assert await writer.claim(claim) == pending
        await writer.remember(claim, Replay(kind="revision", resource_id=uuid7()))
    async with store.transaction() as writer:
        assert await writer.claim(conflicting) is None
        await writer.remember(conflicting, Replay(kind="revision", resource_id=uuid7()))


async def test_insert_revision_accepts_repeated_content_with_a_new_identity() -> None:
    """Each revision has its own identity even when its manifest repeats earlier content."""
    store = InMemoryHierarchyStore()
    hierarchy = await seed_hierarchy(store)
    dataset_id = hierarchy.datasets["run-0001"]
    first = committed_revision(dataset_id, 1, manifest_sha256="a" * 64)
    async with store.transaction() as writer:
        await writer.insert_revision(first)
    duplicate = committed_revision(dataset_id, 2, manifest_sha256="a" * 64)
    async with store.transaction() as writer:
        await writer.insert_revision(duplicate)
    assert await store.revision(duplicate.id) == duplicate


async def test_revision_and_latest_committed_revision_read_the_inserted_row() -> None:
    """revision() and latest_committed_revision() both return what insert_revision wrote."""
    store = InMemoryHierarchyStore()
    hierarchy = await seed_hierarchy(store)
    dataset_id = hierarchy.datasets["run-0001"]
    first = committed_revision(dataset_id, 1, manifest_sha256="a" * 64)
    second = committed_revision(dataset_id, 2, manifest_sha256="b" * 64)
    async with store.transaction() as writer:
        await writer.insert_revision(first)
    async with store.transaction() as writer:
        await writer.insert_revision(second)

    assert await store.revision(first.id) == first
    assert await store.revision(second.id) == second
    with pytest.raises(ResourceNotFound):
        await store.revision(uuid7())

    assert await store.latest_committed_revision(dataset_id) == second
    assert await store.latest_committed_revision(uuid7()) is None


async def test_a_rolled_back_transaction_leaves_no_revision_audit_or_outbox_row() -> None:
    """insert_revision, insert_audit_event and insert_outbox_event all roll back together."""
    store = InMemoryHierarchyStore()
    hierarchy = await seed_hierarchy(store)
    dataset_id = hierarchy.datasets["run-0001"]
    revision = committed_revision(dataset_id, 1, manifest_sha256="a" * 64)
    audit = AuditEvent(
        id=uuid7(),
        kind="revision.committed",
        actor="user:alice",
        subject_kind="revision",
        subject_id=revision.id,
        payload={},
        created_at=datetime.now(UTC),
    )
    outbox = OutboxEvent(
        id=uuid7(),
        kind="revision.committed",
        subject_id=revision.id,
        payload={},
        created_at=datetime.now(UTC),
    )

    class _AbortedError(Exception):
        """Raised deliberately, from inside an open transaction, to force a rollback."""

    with pytest.raises(_AbortedError):
        async with store.transaction() as writer:
            await writer.insert_revision(revision)
            await writer.insert_audit_event(audit)
            await writer.insert_outbox_event(outbox)
            raise _AbortedError

    with pytest.raises(ResourceNotFound):
        await store.revision(revision.id)
    assert store._audit == []
    assert store._outbox == []


async def test_the_in_memory_store_reads_its_clock_when_none_is_injected() -> None:
    """With no clock injected, the store's clock is the system's UTC clock."""
    store = InMemoryHierarchyStore()
    assert isinstance(store._clock, SystemClock)
    before = datetime.now(UTC)
    now = store._clock.now()
    after = datetime.now(UTC)
    assert before <= now <= after


async def test_organization_point_read_raises_for_an_unknown_id() -> None:
    """organization() reports an id that names nothing as not found."""
    store = InMemoryHierarchyStore()
    with pytest.raises(ResourceNotFound):
        await store.organizations.get(uuid7(), Visibility.ALL)


async def test_project_point_read_raises_for_an_unknown_id() -> None:
    """project() reports an id that names nothing as not found."""
    store = InMemoryHierarchyStore()
    with pytest.raises(ResourceNotFound):
        await store.projects.get(uuid7(), Visibility.ALL)


async def test_dataset_point_read_raises_for_an_unknown_id() -> None:
    """dataset() reports an id that names nothing as not found."""
    store = InMemoryHierarchyStore()
    with pytest.raises(ResourceNotFound):
        await store.datasets.get(uuid7(), Visibility.ALL)


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
    window = await store.organizations.browse(PlatformRoot.ROOT, restricted, limit=10, after=None)
    assert [item.slug for item in window.items] == ["org-a"]
    assert window.has_more is False


async def test_projects_window_admits_a_project_named_directly() -> None:
    """projects() admits a project named by visibility.project_ids directly."""
    store = InMemoryHierarchyStore()
    hierarchy = await seed_hierarchy(store, _TREE)
    restricted = Visibility(project_ids=frozenset({hierarchy.projects["proj-a1"]}))
    window = await store.projects.browse(
        hierarchy.organizations["org-a"], restricted, limit=10, after=None
    )
    assert [item.slug for item in window.items] == ["proj-a1"]


async def test_datasets_window_admits_a_dataset_named_directly() -> None:
    """datasets() sorts by (slug, id) and admits a dataset named by visibility.dataset_ids."""
    store = InMemoryHierarchyStore()
    hierarchy = await seed_hierarchy(store, _TREE)
    restricted = Visibility(dataset_ids=frozenset({hierarchy.datasets["ds-a1y"]}))
    window = await store.datasets.browse(
        hierarchy.projects["proj-a1"], restricted, limit=10, after=None
    )
    assert [item.slug for item in window.items] == ["ds-a1y"]


async def test_a_project_is_visible_when_it_contains_a_directly_visible_dataset() -> None:
    """A project outside project_ids is still visible when one of its datasets is."""
    store = InMemoryHierarchyStore()
    hierarchy = await seed_hierarchy(store, _TREE)
    restricted = Visibility(dataset_ids=frozenset({hierarchy.datasets["ds-a1x"]}))
    project = await store.projects.get(hierarchy.projects["proj-a1"], restricted)
    assert project.slug == "proj-a1"
    with pytest.raises(ResourceNotFound):
        await store.projects.get(hierarchy.projects["proj-a2"], restricted)


async def test_an_organization_is_visible_when_it_contains_a_visible_project() -> None:
    """An organization outside organization_ids is still visible when one of its projects is."""
    store = InMemoryHierarchyStore()
    hierarchy = await seed_hierarchy(store, _TREE)
    restricted = Visibility(project_ids=frozenset({hierarchy.projects["proj-a1"]}))
    organization = await store.organizations.get(hierarchy.organizations["org-a"], restricted)
    assert organization.slug == "org-a"
    with pytest.raises(ResourceNotFound):
        await store.organizations.get(hierarchy.organizations["org-b"], restricted)


async def test_empty_visibility_admits_nothing() -> None:
    """Visibility() with every id set empty and unrestricted False admits nothing at any level."""
    store = InMemoryHierarchyStore()
    hierarchy = await seed_hierarchy(store, _TREE)
    empty = Visibility()
    with pytest.raises(ResourceNotFound):
        await store.organizations.get(hierarchy.organizations["org-a"], empty)
    with pytest.raises(ResourceNotFound):
        await store.projects.get(hierarchy.projects["proj-a1"], empty)
    with pytest.raises(ResourceNotFound):
        await store.datasets.get(hierarchy.datasets["ds-a1x"], empty)


async def test_releases_window_orders_by_tag_regardless_of_visibility() -> None:
    """releases() sorts by tag and lists every release of the named dataset."""
    store = InMemoryHierarchyStore()
    hierarchy = await seed_hierarchy(store)
    dataset_id = hierarchy.datasets["run-0001"]
    revision = committed_revision(dataset_id, 1, manifest_sha256="a" * 64)
    async with store.transaction() as writer:
        await writer.insert_revision(revision)
    async with store.transaction() as writer:
        await writer.insert_release(_release(dataset_id, "v2", revision.id, revision.number))
        await writer.insert_release(_release(dataset_id, "v1", revision.id, revision.number))
    window = await store.releases(dataset_id, Visibility.ALL, limit=10, after=None)
    assert [item.tag for item in window.items] == ["v1", "v2"]


async def test_a_limit_one_walk_visits_every_dataset_exactly_once() -> None:
    """A limit=1 walk, following has_more and the last row's key, visits every row exactly once."""
    store = InMemoryHierarchyStore()
    hierarchy = await seed_hierarchy(store, _TREE)
    seen: list[str] = []
    after: tuple[str, UUID] | None = None
    while True:
        window = await store.datasets.browse(
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


async def test_begin_ingest_reserves_and_locks() -> None:
    """Pins the allocator and dataset-lock contract against the in-memory store."""
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=UTC))
    store = InMemoryHierarchyStore(clock=clock)
    await scenario_10_begin_ingest_reserves_and_locks(store, clock)


async def test_a_dead_session_frees_its_number_and_a_commit_spends_it() -> None:
    """Pins gap-free numbering across an aborted, a committed and a failed session."""
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=UTC))
    store = InMemoryHierarchyStore(clock=clock)
    await scenario_11_a_dead_session_frees_its_number_and_a_commit_spends_it(store, clock)


async def test_state_edges_cas_on_etag_and_renew_does_not() -> None:
    """Pins the etag CAS on state edges and renew's separate, etag-free fence."""
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=UTC))
    store = InMemoryHierarchyStore(clock=clock)
    await scenario_12_state_edges_cas_on_etag_and_renew_does_not(store, clock)


async def test_file_ledger_updates_fence_on_pending_and_parts() -> None:
    """Pins the per-file ledger's fence on PENDING state and the expected parts."""
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=UTC))
    store = InMemoryHierarchyStore(clock=clock)
    await scenario_13_file_ledger_updates_fence_on_pending_and_parts(store, clock)


async def test_the_commit_transaction_is_atomic_and_replays() -> None:
    """Pins the commit transaction's atomicity and its idempotent replay."""
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=UTC))
    store = InMemoryHierarchyStore(clock=clock)
    await scenario_14_the_commit_transaction_is_atomic_and_replays(store, clock)


async def test_expiry_flips_lapsed_sessions_only() -> None:
    """Pins the sweep's listing and flip, never touching a renewed or COMMITTING session."""
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=UTC))
    store = InMemoryHierarchyStore(clock=clock)
    await scenario_15_expiry_flips_lapsed_sessions_only(store, clock)


async def test_a_hundred_sequential_ingests_number_gap_free() -> None:
    """Pins gap-free numbering across a hundred commits interleaved with failed attempts."""
    clock = FakeClock(datetime(2026, 1, 1, tzinfo=UTC))
    store = InMemoryHierarchyStore(clock=clock)
    await scenario_16_a_hundred_sequential_ingests_number_gap_free(store, clock)


async def test_ingest_session_point_read_raises_for_an_unknown_id() -> None:
    """ingest_session() reports an id that names nothing as not found."""
    store = InMemoryHierarchyStore()
    with pytest.raises(ResourceNotFound):
        await store.ingest_session(uuid7())


async def test_ingest_file_point_read_raises_for_an_unknown_id() -> None:
    """ingest_file() reports an id that names nothing as not found."""
    store = InMemoryHierarchyStore()
    with pytest.raises(ResourceNotFound):
        await store.ingest_file(uuid7())


async def test_ingest_files_returns_empty_for_an_unknown_session() -> None:
    """ingest_files() returns an empty tuple for a session that does not exist."""
    store = InMemoryHierarchyStore()
    assert await store.ingest_files(uuid7()) == ()
