"""Proves ``PostgresHierarchyStore`` against a migrated PostgreSQL, and against its own reference.

Every write-side and window/visibility scenario in ``tests/hierarchy_contract.py`` runs here against
a real, migrated ``postgres:16`` database, driven through ``PostgresHierarchyStore`` exactly as
``tests/unit/test_hierarchy_store_memory.py`` drives them against the in-memory reference. Several
scenarios reuse the same fixture slugs (``astro``, ``org-a``...), and an organization's slug is
unique platform-wide, so each scenario here runs against freshly truncated hierarchy tables rather
than an ever-growing shared set of rows - the same fresh start the in-memory suite gets from
constructing a new store per scenario.

Beyond the shared scenarios, this module pins what only a real database can prove: that both
backends admit the identical set of ids under every ``Visibility`` value, on one fixture built once
and shared between them; that a window's order is the ``COLLATE "C"`` order the store's SQL asks
for, not whatever the cluster's own default collation would produce; that two concurrent, identical
idempotency claims serialize on the claim row rather than racing to create two resources; and that a
rolled-back claim leaves no trace at all, while an expired one is silently taken over by a later,
different request.
"""

from __future__ import annotations

import asyncio
import dataclasses
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from testcontainers.postgres import PostgresContainer

from huron.core.ports import HierarchyStore
from huron.pkg.catalog.errors import DatasetLocked, ResourceNotFound
from huron.pkg.catalog.ids import uuid7
from huron.pkg.catalog.ingest import LEASE_TTL
from huron.pkg.catalog.layers import Layer
from huron.pkg.catalog.lifecycle import DatasetLifecycle
from huron.pkg.catalog.records import Dataset, Organization, Project, Release
from huron.pkg.metastore import (
    IdempotencyClaim,
    InMemoryHierarchyStore,
    PostgresHierarchyStore,
    Replay,
    Visibility,
)
from tests.hierarchy_contract import (
    VisibleIds,
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
    from collections.abc import Awaitable, Callable
    from uuid import UUID

    from huron.pkg.catalog.ingest import IngestSession
    from huron.pkg.catalog.models import RevisionRecord

pytestmark = pytest.mark.contract

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"

#: Every table one hierarchy fixture can touch, in an order ``TRUNCATE ... CASCADE`` accepts
#: together regardless of their foreign-key dependencies.
_HIERARCHY_TABLES = (
    "audit_events",
    "outbox_events",
    "ingest_files",
    "ingest_sessions",
    "releases",
    "dataset_revisions",
    "idempotency_records",
    "datasets",
    "projects",
    "organizations",
)

#: Six slugs a folding collation orders differently from Python's sorted().
_RECEIPT_ONE_SLUGS = ("a-1", "a1", "a-b", "ab", "abc", "a-c")


def _config(sqlalchemy_url: str) -> Config:
    """Builds an Alembic Config pointed at this project's migrations, for the given database."""
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", sqlalchemy_url)
    return config


def _migrate(sqlalchemy_url: str) -> None:
    """Upgrades the target database to the latest Alembic migration head."""
    command.upgrade(_config(sqlalchemy_url), "head")


class _AbortedError(Exception):
    """Raised deliberately, from inside an open transaction, to force a rollback."""


def _organization(slug: str) -> Organization:
    """Build an Organization ready to insert, at generation and version 1.

    Args:
        slug: The organization's slug.

    Returns:
        A fully formed organization with a fresh id.
    """
    return Organization(
        id=uuid7(),
        slug=slug,
        title=slug,
        description="",
        generation=1,
        version=1,
        created_at=datetime.now(UTC),
    )


def _project(organization_id: UUID, slug: str) -> Project:
    """Build a Project ready to insert, at generation and version 1.

    Args:
        organization_id: The owning organization's id.
        slug: The project's slug.

    Returns:
        A fully formed project with a fresh id.
    """
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


def _dataset(project_id: UUID, slug: str) -> Dataset:
    """Build a Dataset ready to insert, at generation and version 1.

    Args:
        project_id: The owning project's id.
        slug: The dataset's slug.

    Returns:
        A fully formed dataset with a fresh id.
    """
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


async def _reset_hierarchy_tables(pool: asyncpg.Pool) -> None:
    """Empty every hierarchy table, so the next scenario starts as empty as a freshly built store.

    Args:
        pool: The connection pool to truncate through.
    """
    await pool.execute(f"TRUNCATE {', '.join(_HIERARCHY_TABLES)} CASCADE")


# -- 1. every hierarchy_contract scenario, against a migrated database -------


_SCENARIOS = (
    scenario_1_write_invisible_until_commit,
    scenario_2_uniqueness,
    scenario_3_optimistic_concurrency,
    scenario_4_idempotency,
    scenario_5_revisions,
    scenario_6_ordering,
    scenario_7_windows,
    scenario_8_visibility,
    scenario_9_visibility_inputs,
)

#: The instant every ingest scenario below is reset to before it runs, so a
#: clock advance made by one scenario never leaks into the next.
_INGEST_SCENARIOS_EPOCH = datetime(2026, 1, 1, tzinfo=UTC)

_INGEST_SCENARIOS: tuple[Callable[[HierarchyStore, FakeClock], Awaitable[None]], ...] = (
    scenario_10_begin_ingest_reserves_and_locks,
    scenario_11_a_dead_session_frees_its_number_and_a_commit_spends_it,
    scenario_12_state_edges_cas_on_etag_and_renew_does_not,
    scenario_13_file_ledger_updates_fence_on_pending_and_parts,
    scenario_14_the_commit_transaction_is_atomic_and_replays,
    scenario_15_expiry_flips_lapsed_sessions_only,
    scenario_16_a_hundred_sequential_ingests_number_gap_free,
)


def test_the_postgres_hierarchy_store_against_a_migrated_database() -> None:
    """Every hierarchy_contract scenario holds against PostgresHierarchyStore on a real database."""
    with PostgresContainer("postgres:16") as postgres:
        _migrate(postgres.get_connection_url(driver="asyncpg"))
        asyncio.run(_assert_every_scenario(postgres.get_connection_url(driver=None)))


async def _assert_every_scenario(dsn: str) -> None:
    """Runs each hierarchy_contract scenario against one pool, resetting the tables between them.

    Several scenarios seed the same fixture slugs (``astro``, ``org-a``...), and an organization's
    slug is unique platform-wide, so each scenario runs against freshly truncated tables here - the
    same fresh start the in-memory reference suite gets by constructing a new
    ``InMemoryHierarchyStore`` per scenario. The ingest scenarios run second, over the same pool
    and store, with the clock reset to their shared epoch and the tables truncated between each.

    Args:
        dsn: The migrated database's plain connection string.
    """
    pool = await asyncpg.create_pool(dsn)
    try:
        clock = FakeClock(_INGEST_SCENARIOS_EPOCH)
        store = PostgresHierarchyStore(pool, clock=clock)
        for scenario in _SCENARIOS:
            await scenario(store)
            await _reset_hierarchy_tables(pool)
        for ingest_scenario in _INGEST_SCENARIOS:
            clock.set(_INGEST_SCENARIOS_EPOCH)
            await ingest_scenario(store, clock)
            await _reset_hierarchy_tables(pool)
    finally:
        await pool.close()


# -- 2. both backends agree on every visible id, on one shared fixture -------


@dataclasses.dataclass(slots=True)
class _VisibilityFixture:
    """One organization/project/dataset/release tree, built once and shared by both backends.

    Attributes:
        organizations: Every organization, keyed by slug.
        projects: Every project, keyed by slug.
        datasets: Every dataset, keyed by slug.
        release: The one release in the fixture.
        revision: The revision the release cites.
    """

    organizations: dict[str, Organization]
    projects: dict[str, Project]
    datasets: dict[str, Dataset]
    release: Release
    revision: RevisionRecord


def _build_visibility_fixture() -> _VisibilityFixture:
    """Build the org-a/org-b/org-c tree ``scenario_8_visibility`` seeds, once, for both backends.

    Building it once and inserting the identical records into both stores is what makes their
    visibility-filtered id sets comparable at all: ``seed_hierarchy`` mints a fresh id on every
    call, so two separate calls - one per backend - would never produce ids a caller could compare.

    Returns:
        The fixture's organizations, projects, datasets, release and the revision it cites.
    """
    organizations = {slug: _organization(slug) for slug in ("org-a", "org-b", "org-c")}
    projects = {
        "a1": _project(organizations["org-a"].id, "a1"),
        "a2": _project(organizations["org-a"].id, "a2"),
        "b1": _project(organizations["org-b"].id, "b1"),
        "c1": _project(organizations["org-c"].id, "c1"),
    }
    datasets = {
        "a1-ds": _dataset(projects["a1"].id, "a1-ds"),
        "a2-ds": _dataset(projects["a2"].id, "a2-ds"),
        "a2-dt": _dataset(projects["a2"].id, "a2-dt"),
        "a2-du": _dataset(projects["a2"].id, "a2-du"),
        "b1-ds": _dataset(projects["b1"].id, "b1-ds"),
        "c1-ds": _dataset(projects["c1"].id, "c1-ds"),
    }
    revision = committed_revision(datasets["a1-ds"].id, 1, manifest_sha256="f" * 64)
    release = Release(
        id=uuid7(),
        dataset_id=datasets["a1-ds"].id,
        tag="v1",
        revision_id=revision.id,
        revision_number=revision.number,
        title=None,
        created_by="user:test",
        created_at=datetime.now(UTC),
    )
    return _VisibilityFixture(
        organizations=organizations,
        projects=projects,
        datasets=datasets,
        release=release,
        revision=revision,
    )


async def _seed_fixture(store: HierarchyStore, fixture: _VisibilityFixture) -> None:
    """Insert one shared fixture's organizations, projects, datasets and release into a store.

    Args:
        store: The store to seed.
        fixture: The records to insert, identical in both id and shape to whatever the other
            backend was seeded with.
    """
    async with store.transaction() as writer:
        for organization in fixture.organizations.values():
            await writer.insert_organization(organization)
        for project in fixture.projects.values():
            await writer.insert_project(project)
        for dataset in fixture.datasets.values():
            await writer.insert_dataset(dataset, data_classification="open")
        await writer.insert_revision(fixture.revision)
    async with store.transaction() as writer:
        await writer.insert_release(fixture.release)


async def _visible_ids(
    store: HierarchyStore, fixture: _VisibilityFixture, visibility: Visibility
) -> VisibleIds:
    """Compute the ids ``visibility`` admits at every level of the shared fixture.

    Args:
        store: The store to query.
        fixture: The seeded fixture whose ids are being classified.
        visibility: The discovery rights to evaluate.

    Returns:
        The ids ``visibility`` admits, one set per hierarchy level.
    """
    organizations_window = await store.organizations(visibility, limit=200, after=None)
    projects_windows = [
        await store.projects(organization.id, visibility, limit=200, after=None)
        for organization in fixture.organizations.values()
    ]
    datasets_windows = [
        await store.datasets(project.id, visibility, limit=200, after=None)
        for project in fixture.projects.values()
    ]
    try:
        await store.release(fixture.release.dataset_id, fixture.release.tag, visibility)
        releases = frozenset({fixture.release.id})
    except ResourceNotFound:
        releases = frozenset()
    return VisibleIds(
        organizations=frozenset(item.id for item in organizations_window.items),
        projects=frozenset(item.id for window in projects_windows for item in window.items),
        datasets=frozenset(item.id for window in datasets_windows for item in window.items),
        releases=releases,
    )


def test_both_backends_admit_the_same_ids_under_every_visibility() -> None:
    """InMemoryHierarchyStore and PostgresHierarchyStore agree on every id, under every Visibility.

    Both backends must apply the same visibility predicate, so the same fixture must yield the
    same ids through either one. The fixture is built exactly once, by
    ``_build_visibility_fixture``, and the identical ``Organization``/``Project``/``Dataset``/
    ``Release`` records - the same objects, so the same ids - are inserted into both stores; only
    then are the two backends' visibility-filtered id sets meaningfully comparable, level by
    level, for the five ``Visibility`` values ``scenario_8_visibility`` itself exercises against
    the in-memory store alone.
    """
    with PostgresContainer("postgres:16") as postgres:
        _migrate(postgres.get_connection_url(driver="asyncpg"))
        asyncio.run(_assert_backends_agree_on_visibility(postgres.get_connection_url(driver=None)))


async def _assert_backends_agree_on_visibility(dsn: str) -> None:
    """Seeds both backends with one identical fixture and compares their visibility-filtered ids.

    Args:
        dsn: The migrated database's plain connection string.
    """
    fixture = _build_visibility_fixture()
    memory_store = InMemoryHierarchyStore()
    await _seed_fixture(memory_store, fixture)

    pool = await asyncpg.create_pool(dsn)
    try:
        postgres_store = PostgresHierarchyStore(pool)
        await _seed_fixture(postgres_store, fixture)

        visibilities = {
            "all": Visibility.ALL,
            "project_ids": Visibility(project_ids=frozenset({fixture.projects["a1"].id})),
            "dataset_ids": Visibility(
                dataset_ids=frozenset(
                    {
                        fixture.datasets["a2-ds"].id,
                        fixture.datasets["a2-du"].id,
                        fixture.datasets["c1-ds"].id,
                    }
                )
            ),
            "organization_ids": Visibility(
                organization_ids=frozenset({fixture.organizations["org-a"].id})
            ),
            "empty": Visibility(),
        }
        for label, visibility in visibilities.items():
            memory_result = await _visible_ids(memory_store, fixture, visibility)
            postgres_result = await _visible_ids(postgres_store, fixture, visibility)
            assert memory_result == postgres_result, label
    finally:
        await pool.close()


# -- 3. window order is COLLATE "C", not the cluster's own default -----------


def test_windows_order_by_the_c_collation_not_the_cluster_default() -> None:
    """The store's window order is Python's ``sorted()``, which the cluster's default is not."""
    with PostgresContainer("postgres:16") as postgres:
        _migrate(postgres.get_connection_url(driver="asyncpg"))
        asyncio.run(_assert_c_collation_order(postgres.get_connection_url(driver=None)))


async def _assert_c_collation_order(dsn: str) -> None:
    """Compares the store's ``COLLATE "C"`` window order to the cluster's own default ``ORDER BY``.

    A future image whose default collation happens to already be ``C`` would make the first
    assertion below vacuous - it would pass whether or not ``COLLATE "C"`` was ever applied - so the
    second assertion demands the cluster's own default disagree with it, which is what a folding
    default such as ``en_US.utf8`` does to these six slugs.

    Args:
        dsn: The migrated database's plain connection string.
    """
    pool = await asyncpg.create_pool(dsn)
    try:
        store = PostgresHierarchyStore(pool)
        async with store.transaction() as writer:
            for slug in _RECEIPT_ONE_SLUGS:
                await writer.insert_organization(_organization(slug))

        cluster_collation = await pool.fetchval(
            "SELECT datcollate FROM pg_database WHERE datname = current_database()"
        )
        window = await store.organizations(Visibility.ALL, limit=200, after=None)
        c_collation_order = [item.slug for item in window.items]
        assert c_collation_order == sorted(_RECEIPT_ONE_SLUGS), (
            f'COLLATE "C" order {c_collation_order} did not match Python sorted() order under '
            f"cluster collation {cluster_collation!r}"
        )

        default_order = [
            row["slug"] for row in await pool.fetch("SELECT slug FROM organizations ORDER BY slug")
        ]
        assert default_order != c_collation_order, (
            f"the cluster's default collation {cluster_collation!r} already agrees with "
            'COLLATE "C" on these slugs, so this receipt no longer demonstrates anything'
        )
    finally:
        await pool.close()


# -- 4. two concurrent, identical claims serialize on the row ----------------


async def _wait_until_a_backend_blocks_on(
    pool: asyncpg.Pool, *, query_fragment: str, timeout: float = 5.0
) -> None:
    """Poll until a backend is genuinely lock-blocked on a query containing ``query_fragment``.

    Args:
        pool: The pool to poll through, on a connection distinct from either of the two
            transactions under contention.
        query_fragment: A substring the blocked backend's own query text must contain.
        timeout: How long to poll, in seconds, before giving up.

    Raises:
        AssertionError: If no backend was ever observed lock-blocked on a query containing
            ``query_fragment`` within ``timeout`` seconds, meaning the two transactions never
            actually contended for the same row.
    """
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        blocked = await pool.fetchval(
            """
            SELECT count(*) FROM pg_stat_activity
            WHERE wait_event_type = 'Lock' AND query LIKE $1
            """,
            f"%{query_fragment}%",
        )
        if blocked:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(
        f"no backend was ever observed lock-blocked on a query containing {query_fragment!r} "
        f"within {timeout} seconds; the two transactions never actually contended for the same row"
    )


def test_concurrent_identical_claims_serialize_on_the_row() -> None:
    """Two concurrent, identical claims serialize on the row: one creates, the other replays."""
    with PostgresContainer("postgres:16") as postgres:
        _migrate(postgres.get_connection_url(driver="asyncpg"))
        asyncio.run(
            _assert_concurrent_identical_claims_serialize(postgres.get_connection_url(driver=None))
        )


async def _assert_concurrent_identical_claims_serialize(dsn: str) -> None:
    """Forces a second identical claim to be issued while the first's transaction is still open.

    The first transaction stakes the claim, inserts the organization it authorizes, and then holds
    the transaction open - deliberately not committing - until a third connection observes, in
    ``pg_stat_activity``, that the second transaction's own ``claim()`` call is genuinely blocked
    waiting for the same ``(principal, key)`` row. Postgres's own row lock is what forces that
    second call to wait, rather than any application-level coordination between the two
    transactions; only once that wait is confirmed does the first transaction commit. The second
    call's own completion is then checked against a third, independent connection's view of the
    first transaction's write, so the ordering is proven from data actually made visible, not from
    the relative timing of two Python coroutines resuming on their own connections.

    Args:
        dsn: The migrated database's plain connection string.
    """
    pool = await asyncpg.create_pool(dsn)
    try:
        store = PostgresHierarchyStore(pool)
        claim = IdempotencyClaim(principal="user:alice", key="create-race", request_sha256="a" * 64)
        first_staked = asyncio.Event()

        async def first_attempt() -> Replay:
            """Stake the claim, insert the organization it authorizes, then hold the row open."""
            async with store.transaction() as writer:
                assert await writer.claim(claim) is None
                organization = _organization("race")
                await writer.insert_organization(organization)
                won = Replay(kind="organization", resource_id=organization.id)
                await writer.remember(claim, won)
                first_staked.set()
                await _wait_until_a_backend_blocks_on(
                    pool, query_fragment="INSERT INTO idempotency_records"
                )
            return won

        async def second_attempt() -> Replay | None:
            """Issue the identical claim once it is certain to contend for the first's row."""
            await first_staked.wait()
            async with store.transaction() as writer:
                replay = await writer.claim(claim)
            committed = await pool.fetchval(
                "SELECT count(*) FROM organizations WHERE slug = 'race'"
            )
            assert committed == 1, (
                "the second claim returned before the first transaction's write was visible"
            )
            return replay

        first_replay, second_replay = await asyncio.gather(first_attempt(), second_attempt())
        assert second_replay == first_replay

        count = await pool.fetchval("SELECT count(*) FROM organizations WHERE slug = 'race'")
        assert count == 1
    finally:
        await pool.close()


# -- 5. a rolled-back claim leaves no trace; an expired one is taken over ----


def test_a_rolled_back_claim_leaves_no_row_and_an_expired_one_is_taken_over() -> None:
    """A raised transaction leaves no idempotency row; an expired claim is silently taken over."""
    with PostgresContainer("postgres:16") as postgres:
        _migrate(postgres.get_connection_url(driver="asyncpg"))
        asyncio.run(
            _assert_rolled_back_claim_and_expired_takeover(postgres.get_connection_url(driver=None))
        )


async def _assert_rolled_back_claim_and_expired_takeover(dsn: str) -> None:
    """Runs the rollback and expired-takeover assertions against one pool.

    Args:
        dsn: The migrated database's plain connection string.
    """
    pool = await asyncpg.create_pool(dsn)
    try:
        clock = FakeClock(datetime(2026, 1, 1, tzinfo=UTC))
        store = PostgresHierarchyStore(pool, clock=clock)

        doomed = IdempotencyClaim(principal="user:carol", key="doomed", request_sha256="c" * 64)
        with pytest.raises(_AbortedError):
            async with store.transaction() as writer:
                assert await writer.claim(doomed) is None
                raise _AbortedError
        remaining = await pool.fetchval("SELECT count(*) FROM idempotency_records")
        assert remaining == 0

        original = IdempotencyClaim(
            principal="user:dana", key="create-astro", request_sha256="a" * 64
        )
        async with store.transaction() as writer:
            assert await writer.claim(original) is None
            organization = _organization("expires")
            await writer.insert_organization(organization)
            await writer.remember(
                original, Replay(kind="organization", resource_id=organization.id)
            )

        clock.advance(timedelta(hours=24, seconds=1))

        retry = IdempotencyClaim(principal="user:dana", key="create-astro", request_sha256="b" * 64)
        async with store.transaction() as writer:
            assert await writer.claim(retry) is None

        stored_digest = await pool.fetchval(
            "SELECT request_sha256 FROM idempotency_records WHERE principal = $1 AND key = $2",
            "user:dana",
            "create-astro",
        )
        assert stored_digest == "b" * 64
    finally:
        await pool.close()


# -- 6. two concurrent begin_ingest calls serialize on the dataset row -------


def test_two_concurrent_begin_ingest_calls_serialize_on_the_dataset_row() -> None:
    """Two concurrent begin_ingest calls on one dataset serialize on the datasets row lock."""
    with PostgresContainer("postgres:16") as postgres:
        _migrate(postgres.get_connection_url(driver="asyncpg"))
        asyncio.run(
            _assert_concurrent_begin_ingest_calls_serialize(
                postgres.get_connection_url(driver=None)
            )
        )


async def _assert_concurrent_begin_ingest_calls_serialize(dsn: str) -> None:
    """Forces a second begin_ingest to block on the first's row lock, then checks exactly one wins.

    The first transaction reserves a session and holds its transaction open - deliberately not
    committing - until a third connection observes, in ``pg_stat_activity``, that the second
    transaction's own ``begin_ingest`` call is genuinely blocked on the ``datasets`` row's ``FOR
    UPDATE`` lock. Only once that wait is confirmed does the first transaction commit, so the
    ordering is proven from an observed lock wait, never from the relative timing of two Python
    coroutines resuming on their own connections.

    Args:
        dsn: The migrated database's plain connection string.
    """
    pool = await asyncpg.create_pool(dsn)
    try:
        store = PostgresHierarchyStore(pool)
        hierarchy = await seed_hierarchy(store)
        dataset_id = hierarchy.datasets["run-0001"]
        locked = asyncio.Event()

        async def first_attempt() -> IngestSession:
            """Open the first session and hold its transaction open until the second one blocks."""
            async with store.transaction() as writer:
                session = await writer.begin_ingest(
                    dataset_id,
                    "a" * 64,
                    created_by="user:alice",
                    files=(),
                )
                locked.set()
                await _wait_until_a_backend_blocks_on(
                    pool, query_fragment="FROM datasets WHERE id = $1 FOR UPDATE"
                )
            return session

        async def second_attempt() -> DatasetLocked:
            """Attempt a second session once the first is certain to hold the row lock."""
            await locked.wait()
            with pytest.raises(DatasetLocked) as excinfo:
                async with store.transaction() as writer:
                    await writer.begin_ingest(
                        dataset_id,
                        "b" * 64,
                        created_by="user:bob",
                        files=(),
                    )
            return excinfo.value

        winner, loser = await asyncio.gather(first_attempt(), second_attempt())
        assert loser.context["session_id"] == str(winner.lease.ingest_id)
        count = await pool.fetchval(
            "SELECT count(*) FROM ingest_sessions WHERE dataset_id = $1", dataset_id
        )
        assert count == 1
    finally:
        await pool.close()


# -- 7. begin_ingest binds every stamped column to one read of the clock -----


class _IncrementingClock:
    """A ``Clock`` whose ``now()`` returns a later instant on every call.

    A store method that reads the clock more than once when it should read
    it exactly once ends up stamping its columns from different instants;
    this exposes that as two stamps disagreeing by the clock's step instead
    of a subtler timing race.
    """

    def __init__(self, start: datetime, *, step: timedelta) -> None:
        """Start the clock at ``start``, advancing by ``step`` on every read.

        Args:
            start: The instant the first call to ``now()`` returns.
            step: How far the clock moves forward after each call.
        """
        self._next = start
        self._step = step

    def now(self) -> datetime:
        """Return the current instant, then advance the clock by one step.

        Returns:
            The instant this call observed.
        """
        current = self._next
        self._next += self._step
        return current


def test_begin_ingest_binds_expires_at_created_at_and_updated_at_to_one_instant() -> None:
    """begin_ingest stamps expires_at, created_at and updated_at from a single now() read."""
    with PostgresContainer("postgres:16") as postgres:
        _migrate(postgres.get_connection_url(driver="asyncpg"))
        asyncio.run(
            _assert_begin_ingest_binds_one_instant(postgres.get_connection_url(driver=None))
        )


async def _assert_begin_ingest_binds_one_instant(dsn: str) -> None:
    """Reserves a session through a clock that moves on every read, then checks its stamps agree.

    Args:
        dsn: The migrated database's plain connection string.
    """
    pool = await asyncpg.create_pool(dsn)
    try:
        clock = _IncrementingClock(datetime(2026, 1, 1, tzinfo=UTC), step=timedelta(seconds=1))
        store = PostgresHierarchyStore(pool, clock=clock)
        hierarchy = await seed_hierarchy(store)
        dataset_id = hierarchy.datasets["run-0001"]
        async with store.transaction() as writer:
            session = await writer.begin_ingest(
                dataset_id, "a" * 64, created_by="user:alice", files=()
            )
        row = await pool.fetchrow(
            "SELECT created_at, updated_at, expires_at FROM ingest_sessions WHERE id = $1",
            session.lease.ingest_id,
        )
        assert row["created_at"] == row["updated_at"]
        assert row["expires_at"] - row["created_at"] == LEASE_TTL
    finally:
        await pool.close()


# -- 8. structural conformance, not inheritance -------------------------------


def test_stores_conform_to_their_ports_structurally_not_by_inheritance() -> None:
    """Neither store inherits HierarchyStore; conformance to the port stays purely structural."""
    assert HierarchyStore not in PostgresHierarchyStore.__mro__
    assert HierarchyStore not in InMemoryHierarchyStore.__mro__
