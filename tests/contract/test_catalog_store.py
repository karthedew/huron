"""PostgreSQL catalog constraints and guarded migration contracts.

Checks authoritative ancestry, lifecycle vocabulary, reservations, audit indexes,
independent Raw uploads and the retirement of release tags against a disposable
PostgreSQL database. Downgrade round trips preserve seeded records while restoring
the preceding schema.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from testcontainers.postgres import PostgresContainer

from huron.core.foundation.identifiers import uuid7
from huron.core.security.roles import CAPABILITIES, ROLES

if TYPE_CHECKING:
    from uuid import UUID

pytestmark = pytest.mark.contract

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


def _config(sqlalchemy_url: str) -> Config:
    """Builds an Alembic Config pointed at this project's migrations, for the given database."""
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", sqlalchemy_url)
    return config


def _migrate(sqlalchemy_url: str) -> None:
    """Upgrades the target database to the latest Alembic migration head."""
    command.upgrade(_config(sqlalchemy_url), "head")


def test_postgres_catalog_store_against_a_migrated_database() -> None:
    """The catalog schema's constraints hold, and its downgrade/upgrade round trip is exact."""
    with PostgresContainer("postgres:16") as postgres:
        asyncpg_sqlalchemy_url = postgres.get_connection_url(driver="asyncpg")
        dsn = postgres.get_connection_url(driver=None)
        command.upgrade(_config(asyncpg_sqlalchemy_url), "0010_independent_raw")
        asyncio.run(_assert_against(dsn))
        _assert_round_trip(asyncpg_sqlalchemy_url, dsn)


async def _assert_against(dsn: str) -> None:
    """Runs every catalog schema constraint, trigger, and vocabulary assertion against one pool."""
    pool = await asyncpg.create_pool(dsn)
    try:
        await _assert_organizations_lifecycle_state_vocabulary(pool)
        await _assert_projects_lifecycle_state_vocabulary(pool)
        await _assert_datasets_lifecycle_state_vocabulary(pool)
        await _assert_products_lifecycle_state_vocabulary(pool)
        await _assert_dataset_revisions_state_vocabulary(pool)
        await _assert_snapshots_state_vocabulary(pool)
        await _assert_product_versions_state_vocabulary(pool)
        await _assert_purge_records_state_vocabulary(pool)
        await _assert_science_profiles_document_sha256_format(pool)
        await _assert_jobs_kind_vocabulary(pool)
        await _assert_jobs_state_is_still_unconstrained(pool)
        await _assert_outbox_events_kind_format(pool)
        await _assert_lineage_edges_kind_vocabulary(pool)
        await _assert_jsonb_object_shape_columns(pool)
        await _assert_projects_raw_retention_policy_rejects_a_bare_string(pool)
        await _assert_completed_parts_is_the_one_array_column(pool)
        await _assert_json_null_is_refused_where_sql_null_means_absent(pool)
        await _assert_trigger_rejects_a_committed_session_naming_no_revision(pool)
        await _assert_trigger_rejects_a_cross_dataset_revision(pool)
        await _assert_trigger_rejects_a_wrong_revision_number(pool)
        await _assert_trigger_accepts_the_reserved_revision(pool)
        await _assert_trigger_does_not_fire_on_terminal_failure_transitions(pool)
        await _assert_the_retry_succeeds(pool)
        await _assert_the_dead_row_survives_the_retry(pool)
        await _assert_a_committed_number_is_spent(pool)
        await _assert_the_dataset_lock_still_holds(pool)
        await _assert_the_empty_dataset(pool)
        await _assert_gap_free_end_to_end(pool)
        await _assert_ingest_files_state_vocabulary(pool)
        await _assert_ingest_files_part_count_matches_action(pool)
        await _assert_ingest_sessions_dataset_index_serves_a_bare_dataset_lookup(pool)
        await _assert_ingest_sessions_lapsing_index_serves_the_sweep_predicate(pool)
        await _assert_audit_events_kind_format(pool)
        await _assert_audit_events_payload_is_an_object(pool)
        await _assert_audit_events_id_is_globally_unique(pool)
    finally:
        await pool.close()


# -- fixtures inserted directly, standing in for the not-yet-Postgres --------
# -- organization/project/dataset hierarchy -----------------------------------


async def _insert_organization(pool: asyncpg.Pool, *, slug: str) -> UUID:
    """Inserts an organization row directly, standing in for the not-yet-Postgres catalog store."""
    organization_id = uuid7()
    now = datetime.now(UTC)
    await pool.execute(
        """
        INSERT INTO organizations (id, slug, title, generation, version, created_at, updated_at)
        VALUES ($1, $2, $3, 1, 1, $4, $4)
        """,
        organization_id,
        slug,
        slug.title(),
        now,
    )
    return organization_id


async def _insert_project(pool: asyncpg.Pool, *, organization_id: UUID, slug: str) -> UUID:
    """Inserts a project row directly, standing in for the not-yet-Postgres catalog store."""
    project_id = uuid7()
    now = datetime.now(UTC)
    await pool.execute(
        """
        INSERT INTO projects (id, organization_id, slug, title, classification_default,
                               generation, version, created_at, updated_at)
        VALUES ($1, $2, $3, $4, 'open', 1, 1, $5, $5)
        """,
        project_id,
        organization_id,
        slug,
        slug.title(),
        now,
    )
    return project_id


async def _insert_dataset(pool: asyncpg.Pool, *, project_id: UUID, slug: str) -> UUID:
    """Inserts a dataset row directly, standing in for the not-yet-Postgres catalog store."""
    dataset_id = uuid7()
    now = datetime.now(UTC)
    await pool.execute(
        """
        INSERT INTO datasets (id, project_id, slug, title, profile_name, profile_version,
                               data_classification, generation, version, created_at, updated_at)
        VALUES ($1, $2, $3, $4, 'generic', '1', 'internal', 1, 1, $5, $5)
        """,
        dataset_id,
        project_id,
        slug,
        slug.title(),
        now,
    )
    return dataset_id


async def _insert_dataset_revision(
    pool: asyncpg.Pool,
    *,
    dataset_id: UUID,
    revision_number: int,
    manifest_sha256: str | None = None,
) -> UUID:
    """Inserts a committed dataset_revisions row, deriving a unique digest unless one is given.

    `manifest_sha256` defaults to a digest derived from the fresh
    `revision_id`, unique per call; the S7 guard tests pass one explicitly so
    the same digest can be declared on the claiming session.
    """
    revision_id = uuid7()
    now = datetime.now(UTC)
    digest = manifest_sha256 if manifest_sha256 is not None else f"{revision_id.hex}" * 2
    await pool.execute(
        """
        INSERT INTO dataset_revisions
            (id, dataset_id, revision_number, manifest_sha256, metadata_sha256, revision_path,
             file_count, total_bytes, committed_by, committed_at)
        VALUES ($1, $2, $3, $4, $4, $5, 1, 1, 'contract-test', $6)
        """,
        revision_id,
        dataset_id,
        revision_number,
        digest,
        f"revisions/{revision_number:06d}--{revision_id}",
        now,
    )
    return revision_id


async def _insert_product(
    pool: asyncpg.Pool, *, project_id: UUID, slug: str, lifecycle_state: str
) -> UUID:
    """Inserts a product row directly, standing in for the not-yet-Postgres catalog store."""
    product_id = uuid7()
    now = datetime.now(UTC)
    await pool.execute(
        """
        INSERT INTO products (id, project_id, slug, title, shape, lifecycle_state, created_at)
        VALUES ($1, $2, $3, $4, 'tabular', $5, $6)
        """,
        product_id,
        project_id,
        slug,
        slug.title(),
        lifecycle_state,
        now,
    )
    return product_id


async def _insert_snapshot(
    pool: asyncpg.Pool, *, dataset_id: UUID, snapshot_ref: str, state: str
) -> UUID:
    """Inserts a snapshot row directly, standing in for the not-yet-Postgres catalog store."""
    snapshot_id = uuid7()
    await pool.execute(
        """
        INSERT INTO snapshots (id, dataset_id, layer, repo_uri, snapshot_id, state, provenance)
        VALUES ($1, $2, 'bronze', $3, $4, $5, $6::jsonb)
        """,
        snapshot_id,
        dataset_id,
        f"s3://bronze/{snapshot_ref}",
        snapshot_ref,
        state,
        json.dumps({"kind": "external"}),
    )
    return snapshot_id


# -- closed state and lifecycle vocabularies -----------------------------------


async def _assert_organizations_lifecycle_state_vocabulary(pool: asyncpg.Pool) -> None:
    """``organizations.lifecycle_state`` refuses 'SUSPENDED' and accepts 'ACTIVE'."""
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        await pool.execute(
            """
            INSERT INTO organizations (id, slug, title, lifecycle_state, generation, version,
                                        created_at, updated_at)
            VALUES ($1, 'suspended-org', 'Suspended Org', 'SUSPENDED', 1, 1, now(), now())
            """,
            uuid7(),
        )

    await pool.execute(
        """
        INSERT INTO organizations (id, slug, title, lifecycle_state, generation, version,
                                    created_at, updated_at)
        VALUES ($1, 'active-org', 'Active Org', 'ACTIVE', 1, 1, now(), now())
        """,
        uuid7(),
    )


async def _assert_projects_lifecycle_state_vocabulary(pool: asyncpg.Pool) -> None:
    """``projects.lifecycle_state`` refuses an empty string and accepts 'ACTIVE'.

    Replays the schema audit's own proof: an empty-string ``lifecycle_state``
    is exactly the case a format regex would also catch, and this vocabulary
    ``CHECK`` catches it for free.
    """
    organization_id = await _insert_organization(pool, slug="lifecycle-projects")
    project_id = await _insert_project(pool, organization_id=organization_id, slug="lifecycle")

    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        await pool.execute("UPDATE projects SET lifecycle_state = '' WHERE id = $1", project_id)

    await pool.execute("UPDATE projects SET lifecycle_state = 'ACTIVE' WHERE id = $1", project_id)


async def _assert_datasets_lifecycle_state_vocabulary(pool: asyncpg.Pool) -> None:
    """Replays the schema audit's own proof against ``lifecycle_state``."""
    organization_id = await _insert_organization(pool, slug="lifecycle-datasets")
    project_id = await _insert_project(pool, organization_id=organization_id, slug="lifecycle")
    dataset_id = await _insert_dataset(pool, project_id=project_id, slug="lifecycle")

    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        await pool.execute(
            "UPDATE datasets SET lifecycle_state = 'BANANA' WHERE id = $1", dataset_id
        )

    await pool.execute("UPDATE datasets SET lifecycle_state = 'RETIRED' WHERE id = $1", dataset_id)


async def _assert_products_lifecycle_state_vocabulary(pool: asyncpg.Pool) -> None:
    """``products.lifecycle_state`` refuses 'ARCHIVED' and accepts 'DEPRECATED'."""
    organization_id = await _insert_organization(pool, slug="lifecycle-products")
    project_id = await _insert_project(pool, organization_id=organization_id, slug="lifecycle")

    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        await _insert_product(
            pool, project_id=project_id, slug="broken-product", lifecycle_state="ARCHIVED"
        )

    await _insert_product(
        pool, project_id=project_id, slug="deprecated-product", lifecycle_state="DEPRECATED"
    )


async def _assert_dataset_revisions_state_vocabulary(pool: asyncpg.Pool) -> None:
    """Replays the schema audit's own proof against ``state``."""
    organization_id = await _insert_organization(pool, slug="lifecycle-revisions")
    project_id = await _insert_project(pool, organization_id=organization_id, slug="lifecycle")
    dataset_id = await _insert_dataset(pool, project_id=project_id, slug="lifecycle")
    revision_id = await _insert_dataset_revision(pool, dataset_id=dataset_id, revision_number=1)

    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        await pool.execute(
            "UPDATE dataset_revisions SET state = 'NOT_A_STATE' WHERE id = $1", revision_id
        )

    await pool.execute(
        "UPDATE dataset_revisions SET state = 'EXPIRED_PARTIAL' WHERE id = $1", revision_id
    )


async def _assert_snapshots_state_vocabulary(pool: asyncpg.Pool) -> None:
    """``snapshots.state`` refuses 'DRAFT' and accepts 'CANDIDATE'."""
    organization_id = await _insert_organization(pool, slug="lifecycle-snapshots")
    project_id = await _insert_project(pool, organization_id=organization_id, slug="lifecycle")
    dataset_id = await _insert_dataset(pool, project_id=project_id, slug="lifecycle")

    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        await _insert_snapshot(
            pool, dataset_id=dataset_id, snapshot_ref="broken-snap", state="DRAFT"
        )

    await _insert_snapshot(
        pool, dataset_id=dataset_id, snapshot_ref="candidate-snap", state="CANDIDATE"
    )


async def _assert_product_versions_state_vocabulary(pool: asyncpg.Pool) -> None:
    """``product_versions.state`` refuses 'ARCHIVED' and accepts 'CANDIDATE'."""
    organization_id = await _insert_organization(pool, slug="lifecycle-product-versions")
    project_id = await _insert_project(pool, organization_id=organization_id, slug="lifecycle")
    product_id = await _insert_product(
        pool, project_id=project_id, slug="versioned-product", lifecycle_state="ACTIVE"
    )

    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        await pool.execute(
            """
            INSERT INTO product_versions (id, product_id, semver, state, derivation_record)
            VALUES ($1, $2, '1.0.0', 'ARCHIVED', $3::jsonb)
            """,
            uuid7(),
            product_id,
            json.dumps({}),
        )

    await pool.execute(
        """
        INSERT INTO product_versions (id, product_id, semver, state, derivation_record)
        VALUES ($1, $2, '1.0.0', 'CANDIDATE', $3::jsonb)
        """,
        uuid7(),
        product_id,
        json.dumps({}),
    )


async def _assert_purge_records_state_vocabulary(pool: asyncpg.Pool) -> None:
    """``purge_records.state`` refuses 'REJECTED' and accepts 'APPROVED'."""
    organization_id = await _insert_organization(pool, slug="lifecycle-purge")
    project_id = await _insert_project(pool, organization_id=organization_id, slug="lifecycle")
    dataset_id = await _insert_dataset(pool, project_id=project_id, slug="lifecycle")
    revision_id = await _insert_dataset_revision(pool, dataset_id=dataset_id, revision_number=1)

    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        await pool.execute(
            """
            INSERT INTO purge_records (id, revision_id, reason, requested_by, requested_at, state)
            VALUES ($1, $2, 'contract test', 'requester', now(), 'REJECTED')
            """,
            uuid7(),
            revision_id,
        )

    await pool.execute(
        """
        INSERT INTO purge_records
            (id, revision_id, reason, requested_by, requested_at, approved_by, state)
        VALUES ($1, $2, 'contract test', 'requester', now(), 'approver', 'APPROVED')
        """,
        uuid7(),
        revision_id,
    )


async def _assert_science_profiles_document_sha256_format(pool: asyncpg.Pool) -> None:
    """``science_profiles.document_sha256`` refuses an uppercase digest and accepts a lowercase one.

    An uppercase 64-character digest is refused - the same shape check the
    lowercase-only pattern already applies to every sibling ``*_sha256``
    column - and a valid lowercase hex-64 digest is accepted.
    """
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        await pool.execute(
            """
            INSERT INTO science_profiles
                (name, version, document, document_sha256, published_by, published_at)
            VALUES ('contract-profile', 'v1-bad', $1::jsonb, $2, 'contract-test', now())
            """,
            json.dumps({"schema": "urn:huron:science-profile:1"}),
            "A" * 64,
        )

    await pool.execute(
        """
        INSERT INTO science_profiles
            (name, version, document, document_sha256, published_by, published_at)
        VALUES ('contract-profile', 'v1-good', $1::jsonb, $2, 'contract-test', now())
        """,
        json.dumps({"schema": "urn:huron:science-profile:1"}),
        "a" * 64,
    )


# -- kind vocabularies outside audit_events ------------------------------------

_JOB_KINDS = (
    "bronze_build",
    "canonicalize",
    "product_run",
    "validate",
    "polaris_sync",
    "retention",
    "reconcile",
)

_LINEAGE_KINDS = ("raw_revision", "bronze_snapshot", "silver_snapshot", "gold_version")


async def _insert_job(pool: asyncpg.Pool, *, kind: str) -> UUID:
    """Inserts a jobs row directly, with a zero image digest and the given kind."""
    job_id = uuid7()
    now = datetime.now(UTC)
    await pool.execute(
        """
        INSERT INTO jobs (id, kind, subject_id, image_digest, available_at, created_at)
        VALUES ($1, $2, $3, 'sha256:' || repeat('0', 64), $4, $4)
        """,
        job_id,
        kind,
        uuid7(),
        now,
    )
    return job_id


async def _insert_outbox_event(pool: asyncpg.Pool, *, kind: str) -> UUID:
    """Inserts an outbox_events row directly, with an empty jsonb payload and the given kind."""
    event_id = uuid7()
    now = datetime.now(UTC)
    await pool.execute(
        """
        INSERT INTO outbox_events (id, kind, subject_id, payload, created_at)
        VALUES ($1, $2, $3, $4::jsonb, $5)
        """,
        event_id,
        kind,
        uuid7(),
        json.dumps({}),
        now,
    )
    return event_id


async def _insert_lineage_edge(
    pool: asyncpg.Pool, *, upstream_kind: str, downstream_kind: str
) -> UUID:
    """Inserts a lineage_edges row directly, with fresh upstream and downstream ids."""
    edge_id = uuid7()
    now = datetime.now(UTC)
    await pool.execute(
        """
        INSERT INTO lineage_edges
            (id, upstream_kind, upstream_id, downstream_kind, downstream_id, created_at)
        VALUES ($1, $2, $3, $4, $5, $6)
        """,
        edge_id,
        upstream_kind,
        uuid7(),
        downstream_kind,
        uuid7(),
        now,
    )
    return edge_id


async def _assert_jobs_kind_vocabulary(pool: asyncpg.Pool) -> None:
    """``jobs.kind`` refuses an unknown or empty value and accepts each of the seven real workers.

    ``jobs.kind`` is closed to the seven documented workers - a deliberate
    tripwire against an eighth (the layer-intake worker ``design/architecture.html``
    names but ``design/catalog-search.html`` §2 never spells a kind for).
    """
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        await _insert_job(pool, kind="BANANA")

    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        await _insert_job(pool, kind="")

    for kind in _JOB_KINDS:
        await _insert_job(pool, kind=kind)


async def _assert_jobs_state_is_still_unconstrained(pool: asyncpg.Pool) -> None:
    """``jobs.state`` still accepts an arbitrary value; only ``jobs.kind`` is constrained so far.

    ``jobs.state`` is a deliberate deferral, not an oversight -
    ``SCHEMA_DESIGN.md`` § "S2 - ... ### Open questions" item 3 records why:
    ``jobs`` already has ``claimed_at``, ``completed_at`` and ``attempts``,
    and whether ``state`` is the truth or a denormalization of those three is
    a question a future phase must answer, so constraining the column now
    would freeze whichever answer happens to be wrong. ``jobs.kind`` is what
    ``jobs_kind_vocabulary`` above closes; this is the audit's own fourth
    proof, ``INSERT INTO jobs ... state = 'WAT'``, kept green on purpose.
    """
    job_id = uuid7()
    now = datetime.now(UTC)
    await pool.execute(
        """
        INSERT INTO jobs (id, kind, subject_id, image_digest, state, available_at, created_at)
        VALUES ($1, 'reconcile', $2, 'sha256:' || repeat('0', 64), 'WAT', $3, $3)
        """,
        job_id,
        uuid7(),
        now,
    )


async def _assert_outbox_events_kind_format(pool: asyncpg.Pool) -> None:
    """``outbox_events.kind`` refuses a malformed value but accepts any well-formed dotted name.

    ``outbox_events.kind`` is format-checked, not enumerated: an undesigned
    kind - one no consumer has been written for yet - must still be accepted,
    or narrowing this column to a closed list later would be a green-test
    change. The refused shapes are the same four the format regex was proved
    against on a live PostgreSQL 16.
    """
    for bad_kind in ("BANANA", "", "has space", "a" * 64):
        with pytest.raises(asyncpg.exceptions.CheckViolationError):
            await _insert_outbox_event(pool, kind=bad_kind)

    await _insert_outbox_event(pool, kind="revision.committed")
    await _insert_outbox_event(pool, kind="something.nobody.designed")


async def _assert_lineage_edges_kind_vocabulary(pool: asyncpg.Pool) -> None:
    """``lineage_edges`` refuses 'gold_snapshot' on either end and accepts the four real kinds.

    Both ends of a lineage edge draw on the same four typed nodes.
    ``gold_snapshot`` is a plausible near-miss - a Gold snapshot is real, but
    the citable Gold identity is the *version* - and must be refused on
    both ``upstream_kind`` and ``downstream_kind``. The permitted set
    includes a ``gold_version -> gold_version`` supersession edge, which is
    why neither column may be narrowed to a layer-ordering CHECK.
    """
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        await _insert_lineage_edge(
            pool, upstream_kind="gold_snapshot", downstream_kind="gold_version"
        )

    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        await _insert_lineage_edge(
            pool, upstream_kind="silver_snapshot", downstream_kind="gold_snapshot"
        )

    for upstream_kind in _LINEAGE_KINDS:
        for downstream_kind in _LINEAGE_KINDS:
            await _insert_lineage_edge(
                pool, upstream_kind=upstream_kind, downstream_kind=downstream_kind
            )


# -- jsonb top-level type constraints outside audit_events --------------------

_BAD_OBJECT_LITERALS = ('"just a string"', "42", "true", "[]", "null")


@dataclass(frozen=True)
class _JsonbShapeColumn:
    """One jsonb column's refused-and-permitted literal pair, checked against a fixture row.

    One jsonb column's refused/permitted pair, checked by ``UPDATE`` against
    a fixture row already holding a legal value - `where`/`key` locate that
    row, with `key` bound starting at `$2`.
    """

    table: str
    column: str
    where: str
    key: tuple[object, ...]
    accepted: str = "{}"
    bad: tuple[str, ...] = _BAD_OBJECT_LITERALS


async def _assert_jsonb_shape_columns(
    pool: asyncpg.Pool, cases: tuple[_JsonbShapeColumn, ...]
) -> None:
    """Asserts each column's bad literals are refused and its accepted literal is stored."""
    for case in cases:
        update = f"UPDATE {case.table} SET {case.column} = $1::jsonb WHERE {case.where}"
        for literal in case.bad:
            with pytest.raises(asyncpg.exceptions.CheckViolationError):
                await pool.execute(update, literal, *case.key)
        await pool.execute(update, case.accepted, *case.key)


async def _insert_revision_amendment(pool: asyncpg.Pool, *, revision_id: UUID) -> UUID:
    """Inserts a revision_amendments row directly, with an empty jsonb document."""
    amendment_id = uuid7()
    now = datetime.now(UTC)
    await pool.execute(
        """
        INSERT INTO revision_amendments
            (id, revision_id, sequence, changed_keys, document, created_by, created_at)
        VALUES ($1, $2, 1, ARRAY['title'], $3::jsonb, 'contract-test', $4)
        """,
        amendment_id,
        revision_id,
        json.dumps({}),
        now,
    )
    return amendment_id


async def _insert_ingest_session(pool: asyncpg.Pool, *, dataset_id: UUID) -> UUID:
    """Inserts a minimal ingest_sessions row directly, in state 'UPLOADING'."""
    session_id = uuid7()
    now = datetime.now(UTC)
    await pool.execute(
        """
        INSERT INTO ingest_sessions
            (id, dataset_id, revision_id, revision_number, manifest_sha256, state, expires_at,
             created_by, created_at, updated_at)
        VALUES ($1, $2, $3, 1, $4, 'UPLOADING', $5, 'contract-test', $6, $6)
        """,
        session_id,
        dataset_id,
        uuid7(),
        f"{session_id.hex}" * 2,
        now + timedelta(hours=1),
        now,
    )
    return session_id


async def _insert_ingest_session_claiming(
    pool: asyncpg.Pool,
    *,
    dataset_id: UUID,
    revision_number: int,
    revision_id: UUID,
    manifest_sha256: str,
    state: str = "PREPARING",
) -> UUID:
    """Inserts an ingest_sessions row with every begin_ingest-reserved column caller-controlled.

    Inserts an ingest session with every ``begin_ingest``-reserved column
    under the caller's control - the raw-SQL stand-in ``_insert_ingest_session``
    already is, widened for the S7/S7a guard tests, which need to construct
    the exact correspondence (or mismatch) the trigger and the partial
    indexes check.
    """
    session_id = uuid7()
    now = datetime.now(UTC)
    await pool.execute(
        """
        INSERT INTO ingest_sessions
            (id, dataset_id, revision_id, revision_number, manifest_sha256, state, expires_at,
             created_by, created_at, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, 'contract-test', $8, $8)
        """,
        session_id,
        dataset_id,
        revision_id,
        revision_number,
        manifest_sha256,
        state,
        now + timedelta(hours=1),
        now,
    )
    return session_id


async def _set_ingest_session_state(pool: asyncpg.Pool, *, session_id: UUID, state: str) -> None:
    """Updates an ingest_sessions row's state directly, bumping its etag and updated_at."""
    await pool.execute(
        "UPDATE ingest_sessions SET state = $1, etag = etag + 1, updated_at = now() WHERE id = $2",
        state,
        session_id,
    )


async def _delete_ingest_sessions(pool: asyncpg.Pool, *, session_ids: tuple[UUID, ...]) -> None:
    """Deletes the given ingest_sessions rows outright, leaving no residue for a later test.

    Leaves the database clean of the rows the S7a assertions create - this
    module shares one container with the later round-trip test, and a
    dead/live pair sharing a revision_number is lawful under 0008 and
    unlawful under 0007's total UNIQUE, which the downgrade half of that
    round trip restores.
    """
    await pool.execute("DELETE FROM ingest_sessions WHERE id = ANY($1::uuid[])", list(session_ids))


async def _insert_ingest_file(
    pool: asyncpg.Pool, *, ingest_id: UUID, action: str = "upload", part_count: int = 1
) -> UUID:
    """Inserts an ingest_files row directly, with the given action and part_count.

    Args:
        pool: The connection pool to insert through.
        ingest_id: The ingest session this file's ledger row belongs to.
        action: The upload plan's disposition for this file, ``'upload'`` or ``'hardlink'``.
        part_count: The number of parts the upload plan reserved for this file.

    Returns:
        The freshly generated ``file_id`` of the inserted row.
    """
    file_id = uuid7()
    await pool.execute(
        """
        INSERT INTO ingest_files (file_id, ingest_id, path, size, expected_sha256, action,
                                   part_count)
        VALUES ($1, $2, $3, 1024, $4, $5, $6)
        """,
        file_id,
        ingest_id,
        f"data/{file_id.hex}.bin",
        f"{file_id.hex}" * 2,
        action,
        part_count,
    )
    return file_id


async def _insert_idempotency_record(pool: asyncpg.Pool, *, principal: str, key: str) -> None:
    """Inserts an idempotency_records row directly, expiring one hour after now."""
    now = datetime.now(UTC)
    await pool.execute(
        """
        INSERT INTO idempotency_records
            (principal, key, request_sha256, status_code, response, created_at, expires_at)
        VALUES ($1, $2, $3, 200, $4::jsonb, $5, $6)
        """,
        principal,
        key,
        "0" * 64,
        json.dumps({}),
        now,
        now + timedelta(hours=1),
    )


async def _insert_science_profile(pool: asyncpg.Pool, *, version: str) -> None:
    """Inserts a science_profiles row directly, under the shared 'contract-profile' name."""
    now = datetime.now(UTC)
    await pool.execute(
        """
        INSERT INTO science_profiles
            (name, version, document, document_sha256, published_by, published_at)
        VALUES ('contract-profile', $1, $2::jsonb, $3, 'contract-test', $4)
        """,
        version,
        json.dumps({"schema": "urn:huron:science-profile:1"}),
        "b" * 64,
        now,
    )


async def _insert_product_version(pool: asyncpg.Pool, *, product_id: UUID) -> UUID:
    """Inserts a product_versions row directly, state 'CANDIDATE', derivation record empty."""
    version_id = uuid7()
    await pool.execute(
        """
        INSERT INTO product_versions (id, product_id, semver, state, derivation_record)
        VALUES ($1, $2, '1.0.0', 'CANDIDATE', $3::jsonb)
        """,
        version_id,
        product_id,
        json.dumps({}),
    )
    return version_id


async def _insert_reconciliation_finding(pool: asyncpg.Pool) -> UUID:
    """Inserts a reconciliation_findings row directly, with an empty jsonb detail."""
    finding_id = uuid7()
    now = datetime.now(UTC)
    await pool.execute(
        """
        INSERT INTO reconciliation_findings (id, code, severity, detail, found_at)
        VALUES ($1, 'contract-test-finding', 'info', $2::jsonb, $3)
        """,
        finding_id,
        json.dumps({}),
        now,
    )
    return finding_id


async def _assert_jsonb_object_shape_columns(pool: asyncpg.Pool) -> None:
    """Eight jsonb columns each refuse a non-object literal and accept an empty object.

    Eight of the twelve jsonb columns this module owns: the generic
    pairing - a bare string, number, boolean, array and JSON ``null`` all
    refused, an object accepted. The remaining four
    (``projects.raw_retention_policy``, ``ingest_files.completed_parts``,
    ``snapshots.validation_evidence``, ``lineage_edges.region``) each pin a
    design decision the generic pairing does not, and are asserted
    explicitly below instead.
    """
    organization_id = await _insert_organization(pool, slug="jsonb-shape-generic")
    project_id = await _insert_project(pool, organization_id=organization_id, slug="jsonb-shape")
    dataset_id = await _insert_dataset(pool, project_id=project_id, slug="jsonb-shape")
    revision_id = await _insert_dataset_revision(pool, dataset_id=dataset_id, revision_number=1)
    amendment_id = await _insert_revision_amendment(pool, revision_id=revision_id)
    outbox_event_id = await _insert_outbox_event(pool, kind="revision.committed")
    await _insert_idempotency_record(pool, principal="jsonb-shape", key="k1")
    await _insert_science_profile(pool, version="jsonb-shape")
    job_id = await _insert_job(pool, kind="bronze_build")
    snapshot_id = await _insert_snapshot(
        pool, dataset_id=dataset_id, snapshot_ref="jsonb-shape-generic", state="CANDIDATE"
    )
    product_id = await _insert_product(
        pool, project_id=project_id, slug="jsonb-shape", lifecycle_state="ACTIVE"
    )
    product_version_id = await _insert_product_version(pool, product_id=product_id)
    finding_id = await _insert_reconciliation_finding(pool)

    cases = (
        _JsonbShapeColumn(
            table="revision_amendments", column="document", where="id = $2", key=(amendment_id,)
        ),
        _JsonbShapeColumn(
            table="outbox_events", column="payload", where="id = $2", key=(outbox_event_id,)
        ),
        _JsonbShapeColumn(
            table="idempotency_records",
            column="response",
            where="principal = $2 AND key = $3",
            key=("jsonb-shape", "k1"),
        ),
        _JsonbShapeColumn(
            table="science_profiles",
            column="document",
            where="name = $2 AND version = $3",
            key=("contract-profile", "jsonb-shape"),
        ),
        _JsonbShapeColumn(table="jobs", column="payload", where="id = $2", key=(job_id,)),
        _JsonbShapeColumn(
            table="snapshots",
            column="provenance",
            where="id = $2",
            key=(snapshot_id,),
            accepted=json.dumps({"kind": "external"}),
        ),
        _JsonbShapeColumn(
            table="product_versions",
            column="derivation_record",
            where="id = $2",
            key=(product_version_id,),
        ),
        _JsonbShapeColumn(
            table="reconciliation_findings", column="detail", where="id = $2", key=(finding_id,)
        ),
    )
    await _assert_jsonb_shape_columns(pool, cases)


async def _assert_projects_raw_retention_policy_rejects_a_bare_string(pool: asyncpg.Pool) -> None:
    """``projects.raw_retention_policy`` refuses a bare jsonb string and accepts an object.

    F5's own proof, replayed: this exact ``UPDATE`` succeeded against
    ``0007`` and must fail now that ``projects_raw_retention_policy_is_an_object``
    exists.
    """
    organization_id = await _insert_organization(pool, slug="jsonb-shape-projects")
    project_id = await _insert_project(pool, organization_id=organization_id, slug="jsonb-shape")

    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        await pool.execute(
            "UPDATE projects SET raw_retention_policy = '\"just a string\"'::jsonb WHERE id = $1",
            project_id,
        )

    await pool.execute(
        "UPDATE projects SET raw_retention_policy = $1::jsonb WHERE id = $2",
        json.dumps({"days": 30}),
        project_id,
    )


async def _assert_completed_parts_is_the_one_array_column(pool: asyncpg.Pool) -> None:
    """``ingest_files.completed_parts`` is the one column refusing an object, accepting an array.

    ``ingest_files.completed_parts`` is the resume ledger for a multipart
    upload, an array - refused by ``'{}'::jsonb`` and accepted by
    ``'[]'::jsonb`` - the converse of every other jsonb column, which refuses
    an array and accepts an object. ``projects.raw_retention_policy`` stands
    in for "any object column" for that converse.
    """
    organization_id = await _insert_organization(pool, slug="jsonb-shape-array")
    project_id = await _insert_project(pool, organization_id=organization_id, slug="jsonb-shape")
    dataset_id = await _insert_dataset(pool, project_id=project_id, slug="jsonb-shape")
    ingest_id = await _insert_ingest_session(pool, dataset_id=dataset_id)
    file_id = await _insert_ingest_file(pool, ingest_id=ingest_id)

    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        await pool.execute(
            "UPDATE ingest_files SET completed_parts = '{}'::jsonb WHERE file_id = $1", file_id
        )
    await pool.execute(
        "UPDATE ingest_files SET completed_parts = '[1, 2]'::jsonb WHERE file_id = $1", file_id
    )

    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        await pool.execute(
            "UPDATE projects SET raw_retention_policy = '[]'::jsonb WHERE id = $1", project_id
        )

    await _delete_ingest_sessions(pool, session_ids=(ingest_id,))


async def _assert_json_null_is_refused_where_sql_null_means_absent(pool: asyncpg.Pool) -> None:
    """Two nullable jsonb columns accept SQL NULL but refuse the JSON ``null`` literal.

    SQL NULL and the JSON ``null`` literal are different values.
    ``snapshots.validation_evidence`` (not yet validated) and
    ``lineage_edges.region`` (the whole upstream contributes) both accept SQL
    NULL and both refuse ``'null'::jsonb``, which ``jsonb_typeof`` reports as
    ``'null'``, not as absence.
    """
    organization_id = await _insert_organization(pool, slug="jsonb-shape-null")
    project_id = await _insert_project(pool, organization_id=organization_id, slug="jsonb-shape")
    dataset_id = await _insert_dataset(pool, project_id=project_id, slug="jsonb-shape")
    snapshot_id = await _insert_snapshot(
        pool, dataset_id=dataset_id, snapshot_ref="jsonb-shape-null", state="CANDIDATE"
    )

    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        await pool.execute(
            "UPDATE snapshots SET validation_evidence = 'null'::jsonb WHERE id = $1", snapshot_id
        )
    await pool.execute(
        "UPDATE snapshots SET validation_evidence = $1::jsonb WHERE id = $2",
        json.dumps({"checked": True}),
        snapshot_id,
    )
    await pool.execute("UPDATE snapshots SET validation_evidence = NULL WHERE id = $1", snapshot_id)

    edge_id = await _insert_lineage_edge(
        pool, upstream_kind="silver_snapshot", downstream_kind="gold_version"
    )
    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        await pool.execute("UPDATE lineage_edges SET region = 'null'::jsonb WHERE id = $1", edge_id)
    await pool.execute(
        "UPDATE lineage_edges SET region = $1::jsonb WHERE id = $2",
        json.dumps({"run": "run-0042"}),
        edge_id,
    )
    await pool.execute("UPDATE lineage_edges SET region = NULL WHERE id = $1", edge_id)


# -- ingest_sessions_revision_guard (S7) ---------------------------------------
#
# A session reports success only about the revision it reserved at
# begin_ingest: the same id, dataset, revision_number and manifest_sha256.
# The trigger fires only WHEN (NEW.state = 'COMMITTED'), so every path below
# is paired to isolate one clause of the four-column match, plus a control
# that proves the terminal-failure paths are untouched.


async def _assert_trigger_rejects_a_committed_session_naming_no_revision(
    pool: asyncpg.Pool,
) -> None:
    """The commit guard trigger refuses a COMMITTED session whose revision_id names no revision row.

    The audit's own proof case: a session driven to COMMITTING and then
    flipped to COMMITTED while its revision_id names no dataset_revisions
    row at all.
    """
    organization_id = await _insert_organization(pool, slug="guard-no-revision")
    project_id = await _insert_project(pool, organization_id=organization_id, slug="guard")
    dataset_id = await _insert_dataset(pool, project_id=project_id, slug="guard")
    session_id = await _insert_ingest_session_claiming(
        pool,
        dataset_id=dataset_id,
        revision_number=1,
        revision_id=uuid7(),
        manifest_sha256="a" * 64,
        state="COMMITTING",
    )

    with pytest.raises(asyncpg.exceptions.RaiseError):
        await _set_ingest_session_state(pool, session_id=session_id, state="COMMITTED")

    await _delete_ingest_sessions(pool, session_ids=(session_id,))


async def _assert_trigger_rejects_a_cross_dataset_revision(pool: asyncpg.Pool) -> None:
    """The commit guard trigger refuses a COMMITTED session whose revision is another dataset's.

    A real revision, but of another dataset: the session must not claim a
    revision outside its own dataset's tree.
    """
    organization_id = await _insert_organization(pool, slug="guard-cross-dataset")
    project_id = await _insert_project(pool, organization_id=organization_id, slug="guard")
    claiming_dataset_id = await _insert_dataset(pool, project_id=project_id, slug="claiming")
    foreign_dataset_id = await _insert_dataset(pool, project_id=project_id, slug="foreign")
    manifest_sha256 = "b" * 64
    foreign_revision_id = await _insert_dataset_revision(
        pool,
        dataset_id=foreign_dataset_id,
        revision_number=1,
        manifest_sha256=manifest_sha256,
    )
    session_id = await _insert_ingest_session_claiming(
        pool,
        dataset_id=claiming_dataset_id,
        revision_number=1,
        revision_id=foreign_revision_id,
        manifest_sha256=manifest_sha256,
        state="COMMITTING",
    )

    with pytest.raises(asyncpg.exceptions.RaiseError):
        await _set_ingest_session_state(pool, session_id=session_id, state="COMMITTED")

    await _delete_ingest_sessions(pool, session_ids=(session_id,))


async def _assert_trigger_rejects_a_wrong_revision_number(pool: asyncpg.Pool) -> None:
    """The commit guard trigger refuses a COMMITTED session whose revision_number doesn't match.

    The right dataset and id, but a revision_number that differs from the
    session's own - the number the ingest lock allocated is not the number
    that landed.
    """
    organization_id = await _insert_organization(pool, slug="guard-wrong-number")
    project_id = await _insert_project(pool, organization_id=organization_id, slug="guard")
    dataset_id = await _insert_dataset(pool, project_id=project_id, slug="guard")
    manifest_sha256 = "c" * 64
    revision_id = await _insert_dataset_revision(
        pool, dataset_id=dataset_id, revision_number=1, manifest_sha256=manifest_sha256
    )
    session_id = await _insert_ingest_session_claiming(
        pool,
        dataset_id=dataset_id,
        revision_number=2,
        revision_id=revision_id,
        manifest_sha256=manifest_sha256,
        state="COMMITTING",
    )

    with pytest.raises(asyncpg.exceptions.RaiseError):
        await _set_ingest_session_state(pool, session_id=session_id, state="COMMITTED")

    await _delete_ingest_sessions(pool, session_ids=(session_id,))


async def _assert_trigger_accepts_the_reserved_revision(pool: asyncpg.Pool) -> None:
    """The commit guard trigger accepts a COMMITTED session naming the exact revision it reserved.

    The positive control: the same flip, against the revision the session
    actually reserved, succeeds. Without this, a guard that rejected every
    write would pass every case above.
    """
    organization_id = await _insert_organization(pool, slug="guard-positive")
    project_id = await _insert_project(pool, organization_id=organization_id, slug="guard")
    dataset_id = await _insert_dataset(pool, project_id=project_id, slug="guard")
    manifest_sha256 = "d" * 64
    revision_id = await _insert_dataset_revision(
        pool, dataset_id=dataset_id, revision_number=1, manifest_sha256=manifest_sha256
    )
    session_id = await _insert_ingest_session_claiming(
        pool,
        dataset_id=dataset_id,
        revision_number=1,
        revision_id=revision_id,
        manifest_sha256=manifest_sha256,
        state="COMMITTING",
    )

    await _set_ingest_session_state(pool, session_id=session_id, state="COMMITTED")

    state = await pool.fetchval("SELECT state FROM ingest_sessions WHERE id = $1", session_id)
    assert state == "COMMITTED"

    await _delete_ingest_sessions(pool, session_ids=(session_id,))


async def _assert_trigger_does_not_fire_on_terminal_failure_transitions(
    pool: asyncpg.Pool,
) -> None:
    """The commit guard trigger never fires on an ABORTED or FAILED transition, whatever it names.

    The terminal-state control: PREPARING -> ABORTED and
    UPLOADING -> FAILED, both on a session whose revision_id names nothing,
    both succeed - the guard's WHEN clause is false for every state but
    COMMITTED, so it never sees an abort. This is the ABORTED/FAILED path
    proven rather than merely asserted.
    """
    organization_id = await _insert_organization(pool, slug="guard-terminal")
    project_id = await _insert_project(pool, organization_id=organization_id, slug="guard")
    dataset_id = await _insert_dataset(pool, project_id=project_id, slug="guard")

    aborted_session_id = await _insert_ingest_session_claiming(
        pool,
        dataset_id=dataset_id,
        revision_number=1,
        revision_id=uuid7(),
        manifest_sha256="e" * 64,
        state="PREPARING",
    )
    await _set_ingest_session_state(pool, session_id=aborted_session_id, state="ABORTED")

    failed_session_id = await _insert_ingest_session_claiming(
        pool,
        dataset_id=dataset_id,
        revision_number=2,
        revision_id=uuid7(),
        manifest_sha256="f" * 64,
        state="UPLOADING",
    )
    await _set_ingest_session_state(pool, session_id=failed_session_id, state="FAILED")

    rows = await pool.fetch(
        "SELECT id, state FROM ingest_sessions WHERE id = ANY($1::uuid[])",
        [aborted_session_id, failed_session_id],
    )
    assert {row["id"]: row["state"] for row in rows} == {
        aborted_session_id: "ABORTED",
        failed_session_id: "FAILED",
    }

    await _delete_ingest_sessions(pool, session_ids=(aborted_session_id, failed_session_id))


# -- one_claim_per_revision_number / the reservation lifecycle (S7a) ----------
#
# A session reserves its revision number at begin_ingest, hours before the
# revision exists. ABORTED and FAILED free the number for a retry to take
# again; COMMITTED spends it forever. Every assertion below deletes the
# session rows it creates - this module shares one container with the later
# round-trip test, and a dead/live pair sharing a revision_number is lawful
# under 0008 and unlawful under 0007's total UNIQUE the downgrade half restores.


async def _assert_the_retry_succeeds(pool: asyncpg.Pool) -> None:
    """A retry reusing an ABORTED or FAILED session's revision_number succeeds; 0007 refused it.

    The point of S7a. A session driven to ABORTED, then a new session
    inserted for the same (dataset_id, revision_number): succeeds - the exact
    insert that fails against 0007 with `duplicate key value violates unique
    constraint "ingest_sessions_dataset_id_revision_number_key"`. The same
    again with FAILED, on a session that reached COMMITTING first.
    """
    organization_id = await _insert_organization(pool, slug="retry-aborted")
    project_id = await _insert_project(pool, organization_id=organization_id, slug="retry")
    aborted_dataset_id = await _insert_dataset(pool, project_id=project_id, slug="aborted")

    dead_session_id = await _insert_ingest_session_claiming(
        pool,
        dataset_id=aborted_dataset_id,
        revision_number=1,
        revision_id=uuid7(),
        manifest_sha256="1" * 64,
        state="PREPARING",
    )
    await _set_ingest_session_state(pool, session_id=dead_session_id, state="ABORTED")

    retry_session_id = await _insert_ingest_session_claiming(
        pool,
        dataset_id=aborted_dataset_id,
        revision_number=1,
        revision_id=uuid7(),
        manifest_sha256="2" * 64,
        state="PREPARING",
    )

    failed_dataset_id = await _insert_dataset(pool, project_id=project_id, slug="failed")
    stuck_session_id = await _insert_ingest_session_claiming(
        pool,
        dataset_id=failed_dataset_id,
        revision_number=1,
        revision_id=uuid7(),
        manifest_sha256="3" * 64,
        state="COMMITTING",
    )
    await _set_ingest_session_state(pool, session_id=stuck_session_id, state="FAILED")

    failed_retry_session_id = await _insert_ingest_session_claiming(
        pool,
        dataset_id=failed_dataset_id,
        revision_number=1,
        revision_id=uuid7(),
        manifest_sha256="4" * 64,
        state="PREPARING",
    )

    await _delete_ingest_sessions(
        pool,
        session_ids=(
            dead_session_id,
            retry_session_id,
            stuck_session_id,
            failed_retry_session_id,
        ),
    )


async def _assert_the_dead_row_survives_the_retry(pool: asyncpg.Pool) -> None:
    """A dead session's row survives a successful retry unchanged, the record of what was attempted.

    After a successful retry, the ABORTED row is still present, unchanged,
    still carrying its original revision_number and revision_id - the record
    of what was attempted, which is Karl's decision.
    """
    organization_id = await _insert_organization(pool, slug="dead-row-survives")
    project_id = await _insert_project(pool, organization_id=organization_id, slug="survives")
    dataset_id = await _insert_dataset(pool, project_id=project_id, slug="survives")
    original_revision_id = uuid7()

    dead_session_id = await _insert_ingest_session_claiming(
        pool,
        dataset_id=dataset_id,
        revision_number=5,
        revision_id=original_revision_id,
        manifest_sha256="5" * 64,
        state="PREPARING",
    )
    await _set_ingest_session_state(pool, session_id=dead_session_id, state="ABORTED")

    retry_session_id = await _insert_ingest_session_claiming(
        pool,
        dataset_id=dataset_id,
        revision_number=5,
        revision_id=uuid7(),
        manifest_sha256="6" * 64,
        state="PREPARING",
    )

    row = await pool.fetchrow(
        "SELECT state, revision_number, revision_id FROM ingest_sessions WHERE id = $1",
        dead_session_id,
    )
    assert row is not None
    assert row["state"] == "ABORTED"
    assert row["revision_number"] == 5
    assert row["revision_id"] == original_revision_id

    await _delete_ingest_sessions(pool, session_ids=(dead_session_id, retry_session_id))


async def _assert_a_committed_number_is_spent(pool: asyncpg.Pool) -> None:
    """A revision_number already COMMITTED is refused for a new session, unlike ABORTED or FAILED.

    A session committed at number n, then a new PREPARING session at
    (dataset_id, n): rejected. This is the assertion that pins COMMITTED
    inside the predicate - a predicate excluding all three terminal states
    passes every other case here and fails this one.
    """
    organization_id = await _insert_organization(pool, slug="committed-is-spent")
    project_id = await _insert_project(pool, organization_id=organization_id, slug="spent")
    dataset_id = await _insert_dataset(pool, project_id=project_id, slug="spent")
    manifest_sha256 = "7" * 64
    revision_id = await _insert_dataset_revision(
        pool, dataset_id=dataset_id, revision_number=1, manifest_sha256=manifest_sha256
    )
    committed_session_id = await _insert_ingest_session_claiming(
        pool,
        dataset_id=dataset_id,
        revision_number=1,
        revision_id=revision_id,
        manifest_sha256=manifest_sha256,
        state="COMMITTING",
    )
    await _set_ingest_session_state(pool, session_id=committed_session_id, state="COMMITTED")

    with pytest.raises(asyncpg.exceptions.UniqueViolationError) as exc_info:
        await _insert_ingest_session_claiming(
            pool,
            dataset_id=dataset_id,
            revision_number=1,
            revision_id=uuid7(),
            manifest_sha256="8" * 64,
            state="PREPARING",
        )
    assert "one_claim_per_revision_number" in str(exc_info.value)

    await _delete_ingest_sessions(pool, session_ids=(committed_session_id,))


async def _assert_the_dataset_lock_still_holds(pool: asyncpg.Pool) -> None:
    """A second live session on the same dataset at another number is refused by the ingest lock.

    A second live session on the same dataset at a *different* number is
    rejected naming one_open_ingest_per_dataset, not the new index -
    asserting on the index name is what stops the two guarantees being
    mistaken for one.
    """
    organization_id = await _insert_organization(pool, slug="dataset-lock-holds")
    project_id = await _insert_project(pool, organization_id=organization_id, slug="lock")
    dataset_id = await _insert_dataset(pool, project_id=project_id, slug="lock")

    open_session_id = await _insert_ingest_session_claiming(
        pool,
        dataset_id=dataset_id,
        revision_number=1,
        revision_id=uuid7(),
        manifest_sha256="9" * 64,
        state="PREPARING",
    )

    with pytest.raises(asyncpg.exceptions.UniqueViolationError) as exc_info:
        await _insert_ingest_session_claiming(
            pool,
            dataset_id=dataset_id,
            revision_number=2,
            revision_id=uuid7(),
            manifest_sha256="0" * 64,
            state="PREPARING",
        )
    assert "one_open_ingest_per_dataset" in str(exc_info.value)

    await _delete_ingest_sessions(pool, session_ids=(open_session_id,))


async def _assert_the_empty_dataset(pool: asyncpg.Pool) -> None:
    """A dataset whose only ingest aborted stays ACTIVE, empty, and ready to allocate revision 1.

    A dataset whose only ingest aborted is still ACTIVE, holds zero
    revisions, and the next allocation still lands on 1 - the dataset
    survives an aborted ingest, empty.
    """
    organization_id = await _insert_organization(pool, slug="empty-dataset")
    project_id = await _insert_project(pool, organization_id=organization_id, slug="empty")
    dataset_id = await _insert_dataset(pool, project_id=project_id, slug="empty")

    session_id = await _insert_ingest_session_claiming(
        pool,
        dataset_id=dataset_id,
        revision_number=1,
        revision_id=uuid7(),
        manifest_sha256="a" * 63 + "1",
        state="PREPARING",
    )
    await _set_ingest_session_state(pool, session_id=session_id, state="ABORTED")

    lifecycle_state = await pool.fetchval(
        "SELECT lifecycle_state FROM datasets WHERE id = $1", dataset_id
    )
    assert lifecycle_state == "ACTIVE"

    revision_count = await pool.fetchval(
        "SELECT count(*) FROM dataset_revisions WHERE dataset_id = $1", dataset_id
    )
    assert revision_count == 0

    next_number = await pool.fetchval(
        "SELECT coalesce(max(revision_number), 0) + 1 FROM dataset_revisions WHERE dataset_id = $1",
        dataset_id,
    )
    assert next_number == 1

    await _delete_ingest_sessions(pool, session_ids=(session_id,))


async def _assert_gap_free_end_to_end(pool: asyncpg.Pool) -> None:
    """Two dead attempts at the same number don't burn it: committed revisions still number 1 and 2.

    Two dead attempts at 1, a third committing 1, a fourth committing 2:
    dataset_revisions holds exactly {1, 2} - the retry re-derives the same
    number the allocator would have produced the first time, which is what
    keeps max(committed) + 1 gap-free rather than one number burned per dead
    attempt.
    """
    organization_id = await _insert_organization(pool, slug="gap-free-end-to-end")
    project_id = await _insert_project(pool, organization_id=organization_id, slug="gap-free")
    dataset_id = await _insert_dataset(pool, project_id=project_id, slug="gap-free")

    first_dead_id = await _insert_ingest_session_claiming(
        pool,
        dataset_id=dataset_id,
        revision_number=1,
        revision_id=uuid7(),
        manifest_sha256="b" * 63 + "1",
        state="PREPARING",
    )
    await _set_ingest_session_state(pool, session_id=first_dead_id, state="ABORTED")

    second_dead_id = await _insert_ingest_session_claiming(
        pool,
        dataset_id=dataset_id,
        revision_number=1,
        revision_id=uuid7(),
        manifest_sha256="b" * 63 + "2",
        state="PREPARING",
    )
    await _set_ingest_session_state(pool, session_id=second_dead_id, state="ABORTED")

    manifest_one = "b" * 63 + "3"
    revision_one_id = await _insert_dataset_revision(
        pool, dataset_id=dataset_id, revision_number=1, manifest_sha256=manifest_one
    )
    committed_one_id = await _insert_ingest_session_claiming(
        pool,
        dataset_id=dataset_id,
        revision_number=1,
        revision_id=revision_one_id,
        manifest_sha256=manifest_one,
        state="COMMITTING",
    )
    await _set_ingest_session_state(pool, session_id=committed_one_id, state="COMMITTED")

    manifest_two = "b" * 63 + "4"
    revision_two_id = await _insert_dataset_revision(
        pool, dataset_id=dataset_id, revision_number=2, manifest_sha256=manifest_two
    )
    committed_two_id = await _insert_ingest_session_claiming(
        pool,
        dataset_id=dataset_id,
        revision_number=2,
        revision_id=revision_two_id,
        manifest_sha256=manifest_two,
        state="COMMITTING",
    )
    await _set_ingest_session_state(pool, session_id=committed_two_id, state="COMMITTED")

    revision_numbers = await pool.fetch(
        "SELECT revision_number FROM dataset_revisions "
        "WHERE dataset_id = $1 ORDER BY revision_number",
        dataset_id,
    )
    assert [row["revision_number"] for row in revision_numbers] == [1, 2]

    await _delete_ingest_sessions(
        pool,
        session_ids=(first_dead_id, second_dead_id, committed_one_id, committed_two_id),
    )


# -- 0009: the ingest ledger's vocabulary, part count and parent citation -----


async def _assert_ingest_files_state_vocabulary(pool: asyncpg.Pool) -> None:
    """``ingest_files_state_vocabulary`` refuses an unrecognized state and accepts the real two."""
    organization_id = await _insert_organization(pool, slug="ingest-files-state")
    project_id = await _insert_project(pool, organization_id=organization_id, slug="state")
    dataset_id = await _insert_dataset(pool, project_id=project_id, slug="state")
    ingest_id = await _insert_ingest_session(pool, dataset_id=dataset_id)
    file_id = await _insert_ingest_file(pool, ingest_id=ingest_id)

    with pytest.raises(asyncpg.exceptions.CheckViolationError) as exc_info:
        await pool.execute(
            "UPDATE ingest_files SET state = 'MISMATCHED' WHERE file_id = $1", file_id
        )
    assert "ingest_files_state_vocabulary" in str(exc_info.value)

    await pool.execute("UPDATE ingest_files SET state = 'COMPLETE' WHERE file_id = $1", file_id)
    await pool.execute("UPDATE ingest_files SET state = 'PENDING' WHERE file_id = $1", file_id)

    await _delete_ingest_sessions(pool, session_ids=(ingest_id,))


async def _assert_ingest_files_part_count_matches_action(pool: asyncpg.Pool) -> None:
    """Raw files require upload actions and at least one part, even when empty."""
    organization_id = await _insert_organization(pool, slug="ingest-files-part-count")
    project_id = await _insert_project(pool, organization_id=organization_id, slug="part-count")
    dataset_id = await _insert_dataset(pool, project_id=project_id, slug="part-count")
    ingest_id = await _insert_ingest_session(pool, dataset_id=dataset_id)
    for parts in (0, 1):
        with pytest.raises(
            asyncpg.exceptions.CheckViolationError, match="ingest_files_action_check"
        ):
            await _insert_ingest_file(
                pool, ingest_id=ingest_id, action="hardlink", part_count=parts
            )
    with pytest.raises(
        asyncpg.exceptions.CheckViolationError, match="ingest_files_part_count_positive"
    ):
        await _insert_ingest_file(pool, ingest_id=ingest_id, action="upload", part_count=0)
    await _insert_ingest_file(pool, ingest_id=ingest_id, action="upload", part_count=1)
    await _delete_ingest_sessions(pool, session_ids=(ingest_id,))


async def _assert_ingest_sessions_dataset_index_serves_a_bare_dataset_lookup(
    pool: asyncpg.Pool,
) -> None:
    """``ingest_sessions_dataset`` serves a bare dataset_id lookup instead of a sequential scan.

    Neither partial unique index on this table leads with a predicate-free
    ``dataset_id``, so without a plain index the ``datasets`` foreign key's
    own delete check and a per-dataset listing would sequential-scan every
    session ever opened.
    """
    async with pool.acquire() as connection, connection.transaction():
        await connection.execute("SET LOCAL enable_seqscan = off")
        rows = await connection.fetch(
            "EXPLAIN SELECT id FROM ingest_sessions WHERE dataset_id = $1", uuid7()
        )
    plan = "\n".join(row["QUERY PLAN"] for row in rows)
    assert "ingest_sessions_dataset" in plan


async def _assert_ingest_sessions_lapsing_index_serves_the_sweep_predicate(
    pool: asyncpg.Pool,
) -> None:
    """``ingest_sessions_lapsing`` serves the expiry sweep's listing instead of a sequential scan.

    The sweep's predicate - open sessions whose lease has lapsed, oldest
    first - is served by neither the plain dataset index nor the two
    partial unique indexes, none of which carry ``expires_at`` or are
    ordered by it; without this index every pass, on every replica, would
    walk every session ever opened.
    """
    async with pool.acquire() as connection, connection.transaction():
        await connection.execute("SET LOCAL enable_seqscan = off")
        rows = await connection.fetch(
            "EXPLAIN SELECT id FROM ingest_sessions "
            "WHERE state IN ('PREPARING', 'UPLOADING', 'VERIFYING') AND expires_at <= now() "
            "ORDER BY expires_at, id LIMIT 100"
        )
    plan = "\n".join(row["QUERY PLAN"] for row in rows)
    assert "ingest_sessions_lapsing" in plan


# -- audit_events: the rebuilt table's two constraints and its new key --------


async def _insert_audit_event(
    pool: asyncpg.Pool, *, kind: str = "revision.committed", payload: str = "{}"
) -> UUID:
    """Inserts an audit_events row directly, with the given kind and jsonb payload."""
    event_id = uuid7()
    now = datetime.now(UTC)
    await pool.execute(
        """
        INSERT INTO audit_events (id, kind, actor, subject_kind, subject_id, payload, created_at)
        VALUES ($1, $2, 'contract-test', 'dataset_revision', $3, $4::jsonb, $5)
        """,
        event_id,
        kind,
        uuid7(),
        payload,
        now,
    )
    return event_id


async def _assert_audit_events_kind_format(pool: asyncpg.Pool) -> None:
    """``audit_events.kind`` refuses a malformed value but accepts any well-formed dotted name.

    ``audit_events.kind`` carries the same lowercase dotted-name format
    ``outbox_events.kind`` does, applied against the plain table the rebuild
    leaves behind rather than the partitioned parent it was written for.
    ``something.nobody.designed`` accepted alongside ``revision.committed`` is
    what makes the open-vocabulary verdict a tested decision rather than an
    assumption.
    """
    for bad_kind in ("BANANA", "", "has space", "a" * 64):
        with pytest.raises(asyncpg.exceptions.CheckViolationError):
            await _insert_audit_event(pool, kind=bad_kind)

    await _insert_audit_event(pool, kind="revision.committed")
    await _insert_audit_event(pool, kind="something.nobody.designed")


async def _assert_audit_events_payload_is_an_object(pool: asyncpg.Pool) -> None:
    """``audit_events.payload`` refuses a non-object jsonb value and accepts an empty object.

    ``audit_events.payload`` states its own top-level type, on the plain
    table the rebuild leaves behind rather than the partitioned parent the
    constraint would otherwise have recursed onto.
    """
    for bad_payload in ('"just a string"', "[]", "null"):
        with pytest.raises(asyncpg.exceptions.CheckViolationError):
            await _insert_audit_event(pool, payload=bad_payload)

    await _insert_audit_event(pool, payload="{}")


async def _assert_audit_events_id_is_globally_unique(pool: asyncpg.Pool) -> None:
    """``audit_events``'s primary key refuses a second row sharing an id at a different created_at.

    ``PRIMARY KEY (id)`` is the guarantee the rebuild bought that the
    partitioned shape's composite ``PRIMARY KEY (id, created_at)`` never
    could: two different partitions could each hold a row with the same
    ``id`` as long as their ``created_at`` values landed in different
    ranges. A second row sharing an ``id`` at a different ``created_at``
    must now be refused outright, by the primary key alone.
    """
    event_id = uuid7()
    first_created_at = datetime.now(UTC)

    await pool.execute(
        """
        INSERT INTO audit_events (id, kind, actor, subject_kind, subject_id, payload, created_at)
        VALUES ($1, 'revision.committed', 'contract-test', 'dataset_revision', $2, '{}'::jsonb, $3)
        """,
        event_id,
        uuid7(),
        first_created_at,
    )

    with pytest.raises(asyncpg.exceptions.UniqueViolationError):
        await pool.execute(
            """
            INSERT INTO audit_events
                (id, kind, actor, subject_kind, subject_id, payload, created_at)
            VALUES ($1, 'revision.committed', 'contract-test', 'dataset_revision', $2,
                    '{}'::jsonb, $3)
            """,
            event_id,
            uuid7(),
            first_created_at + timedelta(hours=1),
        )


# -- the round trip: downgrade() is upgrade()'s exact inverse -----------------

_INGEST_LEDGER_INDEXES = (
    "ingest_sessions_dataset",
    "ingest_sessions_lapsing",
)
_INGEST_LEDGER_ADDITIONS = frozenset({"ingest_files.part_count", *_INGEST_LEDGER_INDEXES})


async def _present_ingest_ledger_additions(pool: asyncpg.Pool) -> frozenset[str]:
    """Returns which of The current ledger column and two indexes currently exist."""
    column_rows = await pool.fetch(
        """
        SELECT table_name || '.' || column_name AS name
        FROM information_schema.columns
        WHERE (table_name, column_name) IN
              (('ingest_files', 'part_count'))
        """
    )
    index_rows = await pool.fetch(
        "SELECT name FROM unnest($1::text[]) AS name WHERE to_regclass(name) IS NOT NULL",
        list(_INGEST_LEDGER_INDEXES),
    )
    return frozenset({row["name"] for row in column_rows} | {row["name"] for row in index_rows})


async def _assert_ingest_ledger_additions_present(dsn: str) -> None:
    """The current ledger column and two indexes all exist."""
    pool = await asyncpg.create_pool(dsn)
    try:
        assert await _present_ingest_ledger_additions(pool) == _INGEST_LEDGER_ADDITIONS
    finally:
        await pool.close()


async def _assert_ingest_ledger_additions_absent(dsn: str) -> None:
    """The current ledger column and two indexes are all gone after downgrading one revision."""
    pool = await asyncpg.create_pool(dsn)
    try:
        assert await _present_ingest_ledger_additions(pool) == frozenset()
    finally:
        await pool.close()


_ROUND_TRIP_PROBES = (
    "releases_revision_dataset_fk",  # block 1
    "role_bindings_scope",  # block 2
    "datasets_lifecycle_state_vocabulary",  # block 3
    "jobs_kind_vocabulary",  # block 4
    "projects_raw_retention_policy_is_an_object",  # block 5
    "ingest_sessions_revision_guard",  # block 6
    "one_claim_per_revision_number",  # block 7
    "audit_events_created_at",  # block 8 - block 9's two CHECKs ride on the
    # same rebuilt relation and share this probe rather than adding a tenth
)


async def _present_probe_names(pool: asyncpg.Pool) -> set[str]:
    """Returns which round-trip probe names currently exist, as a constraint, index, or trigger.

    Each probe names a constraint, an index or a trigger - three different
    system catalogs - so presence is checked uniformly rather than by kind:
    a name that shows up in any of the three is an object `0008` installed.
    """
    rows = await pool.fetch(
        """
        SELECT name
        FROM unnest($1::text[]) AS name
        WHERE EXISTS (SELECT 1 FROM pg_constraint WHERE conname = name)
           OR EXISTS (SELECT 1 FROM pg_class WHERE relname = name AND relkind = 'i')
           OR EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = name AND NOT tgisinternal)
        """,
        list(_ROUND_TRIP_PROBES),
    )
    return {row["name"] for row in rows}


async def _assert_ingest_sessions_holds_no_duplicate_reservation(pool: asyncpg.Pool) -> None:
    """No two live ingest_sessions rows share a (dataset_id, revision_number) pair before downgrade.

    The downgrade restores ``0001``'s total ``UNIQUE (dataset_id,
    revision_number)``, which a dead/live pair sharing a number - lawful
    under ``0008``'s partial index, unlawful under the restored total one -
    would refuse to recreate. Every assertion above that creates such a pair
    deletes its own rows before returning; this checks that promise rather
    than trusting it, since this module shares one container across every
    assertion registered before it.
    """
    duplicates = await pool.fetch(
        """
        SELECT dataset_id, revision_number
        FROM ingest_sessions
        GROUP BY dataset_id, revision_number
        HAVING count(*) > 1
        """
    )
    assert duplicates == []


def _assert_round_trip(asyncpg_sqlalchemy_url: str, dsn: str) -> None:
    """``downgrade()`` undoes exactly what ``upgrade()`` added, at two grains.

    First downgrade to ``0008`` to remove the current ledger additions, then
    upgrade to ``0010`` and check the column and two surviving indexes.
    Then the broader trip across all nine of ``0008``'s ``DDL`` blocks:
    downgrading to ``0007_roleless_service_accounts`` and upgrading to ``0010``
    again, against the one container this module's other assertions already
    populated. Alembic's ``command.downgrade``/``command.upgrade`` block the
    thread they run on, so they run here, between short-lived asyncpg pools,
    rather than inside ``_assert_against``'s single long-lived one.
    """
    config = _config(asyncpg_sqlalchemy_url)

    asyncio.run(_assert_ingest_ledger_additions_present(dsn))
    command.downgrade(config, "0008_schema_conformance")
    asyncio.run(_assert_ingest_ledger_additions_absent(dsn))
    command.upgrade(config, "0010_independent_raw")
    asyncio.run(_assert_ingest_ledger_additions_present(dsn))

    event_id = asyncio.run(_prepare_round_trip(dsn))
    command.downgrade(config, "0007_roleless_service_accounts")
    asyncio.run(_assert_round_trip_downgraded(dsn, event_id))
    command.upgrade(config, "0010_independent_raw")
    asyncio.run(_assert_round_trip_reupgraded(dsn, event_id))


async def _prepare_round_trip(dsn: str) -> UUID:
    """Confirms every 0008 object is present, then inserts an audit event to track the trip."""
    pool = await asyncpg.create_pool(dsn)
    try:
        assert await _present_probe_names(pool) == set(_ROUND_TRIP_PROBES)
        await _assert_ingest_sessions_holds_no_duplicate_reservation(pool)
        return await _insert_audit_event(pool, kind="revision.committed")
    finally:
        await pool.close()


async def _assert_round_trip_downgraded(dsn: str, event_id: UUID) -> None:
    """After downgrade, every 0008 object is gone but the pre-existing audit event row survives."""
    pool = await asyncpg.create_pool(dsn)
    try:
        assert await _present_probe_names(pool) == set()
        row = await pool.fetchrow("SELECT id FROM audit_events WHERE id = $1", event_id)
        assert row is not None
    finally:
        await pool.close()


async def _assert_round_trip_reupgraded(dsn: str, event_id: UUID) -> None:
    """After the second upgrade, every 0008 object is back and the audit event still survives."""
    pool = await asyncpg.create_pool(dsn)
    try:
        assert await _present_probe_names(pool) == set(_ROUND_TRIP_PROBES)
        row = await pool.fetchrow("SELECT id FROM audit_events WHERE id = $1", event_id)
        assert row is not None
    finally:
        await pool.close()


def test_independent_raw_migration_refuses_legacy_links_and_lossy_downgrades() -> None:
    """Unsafe schema transitions fail atomically; clean upgrades retain revision records."""
    from sqlalchemy.exc import DBAPIError

    with PostgresContainer("postgres:16") as postgres:
        config = _config(postgres.get_connection_url(driver="asyncpg"))
        dsn = postgres.get_connection_url(driver=None)
        command.upgrade(config, "0009_ingest_ledger")
        file_id, dataset_id = asyncio.run(_seed_legacy_link(dsn))
        with pytest.raises(DBAPIError, match="Legacy hardlinks"):
            command.upgrade(config, "0010_independent_raw")
        asyncio.run(_remove_legacy_fixture(dsn, file_id))
        command.upgrade(config, "0010_independent_raw")
        first, second = asyncio.run(_seed_identical_revisions(dsn, dataset_id))
        with pytest.raises(DBAPIError, match="dataset_revisions_dataset_id_manifest_sha256_key"):
            command.downgrade(config, "0009_ingest_ledger")
        asyncio.run(_assert_failed_downgrade_preserves_revisions(dsn, first, second))


def test_postgres_catalog_constraints_at_head() -> None:
    """Existing catalog constraints also hold after a clean upgrade to head."""
    with PostgresContainer("postgres:16") as postgres:
        _migrate(postgres.get_connection_url(driver="asyncpg"))
        asyncio.run(_assert_against(postgres.get_connection_url(driver=None)))


@pytest.mark.parametrize("state", ["PREPARING", "UPLOADING", "VERIFYING", "COMMITTING"])
def test_verified_raw_migration_guards_are_atomic(state: str) -> None:
    """Each unfinished legacy state blocks upgrade; resolved data upgrades but cannot downgrade."""
    with PostgresContainer("postgres:16") as postgres:
        config = _config(postgres.get_connection_url(driver="asyncpg"))
        command.upgrade(config, "0010_independent_raw")
        asyncio.run(
            _assert_verified_raw_migration(config, postgres.get_connection_url(driver=None), state)
        )


async def _assert_verified_raw_migration(config: Config, dsn: str, state: str) -> None:
    """Verify upgrade refusal, unchanged evidence, terminal-session upgrade and rollback refusal."""
    from sqlalchemy.exc import DBAPIError

    pool = await asyncpg.create_pool(dsn)
    try:
        organization = await _insert_organization(pool, slug="verified-raw")
        project = await _insert_project(pool, organization_id=organization, slug="verified")
        dataset = await _insert_dataset(pool, project_id=project, slug="verified")
        revision = await _insert_dataset_revision(
            pool, dataset_id=dataset, revision_number=1, manifest_sha256="a" * 64
        )
        for terminal in ("COMMITTED", "ABORTED", "FAILED"):
            await _insert_ingest_session_claiming(
                pool,
                dataset_id=dataset,
                revision_number=1,
                revision_id=revision if terminal == "COMMITTED" else uuid7(),
                manifest_sha256="a" * 64,
                state=terminal,
            )
        session = await _insert_ingest_session_claiming(
            pool,
            dataset_id=dataset,
            revision_number=2,
            revision_id=uuid7(),
            manifest_sha256="b" * 64,
            state=state,
        )
        await _insert_ingest_file(pool, ingest_id=session)
        before = await _verified_raw_migration_snapshot(pool)
        with pytest.raises(DBAPIError, match="Nonterminal legacy ingests require fenced offline"):
            await asyncio.to_thread(command.upgrade, config, "0011_verified_raw")
        assert await _verified_raw_migration_snapshot(pool) == before
        for relation in ("ingest_commit_intents", "ingest_recoveries"):
            assert await pool.fetchval("SELECT to_regclass($1)", relation) is None
        assert (
            await pool.fetchval("SELECT to_regprocedure('reject_commit_intent_mutation()')") is None
        )
        with pytest.raises(asyncpg.CheckViolationError, match="ingest_sessions_state_check"):
            await _set_ingest_session_state(pool, session_id=session, state="RECOVERING")

        await _set_ingest_session_state(pool, session_id=session, state="FAILED")
        resolved = await _verified_raw_migration_snapshot(pool)
        await asyncio.to_thread(command.upgrade, config, "0011_verified_raw")
        upgraded = await _verified_raw_migration_snapshot(pool)
        assert upgraded["version"] == "0011_verified_raw"
        for table in ("ingest_sessions", "ingest_files", "dataset_revisions"):
            assert upgraded[table] == resolved[table]
        for relation in ("ingest_commit_intents", "ingest_recoveries"):
            assert await pool.fetchval("SELECT to_regclass($1)::text", relation) == relation
            assert await pool.fetchval(f"SELECT count(*) FROM {relation}") == 0
        assert await pool.fetchval("SELECT to_regprocedure('reject_commit_intent_mutation()')")
        await _set_ingest_session_state(pool, session_id=session, state="RECOVERING")
        before_downgrade = await _verified_raw_migration_snapshot(pool)
        with pytest.raises(
            RuntimeError, match="verified Raw publication cannot be downgraded online"
        ):
            await asyncio.to_thread(command.downgrade, config, "0010_independent_raw")
        assert await _verified_raw_migration_snapshot(pool) == before_downgrade
    finally:
        await pool.close()


async def _verified_raw_migration_snapshot(pool: asyncpg.Pool) -> dict[str, object]:
    """Capture persisted legacy rows, migration version and schema objects for atomicity checks."""
    snapshot: dict[str, object] = {
        "version": await pool.fetchval("SELECT version_num FROM alembic_version"),
        "columns": await pool.fetch(
            "SELECT * FROM information_schema.columns WHERE table_schema = 'public' "
            "ORDER BY table_name, ordinal_position"
        ),
        "constraints": await pool.fetch(
            "SELECT conrelid, conname, pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE connamespace = 'public'::regnamespace ORDER BY conrelid, conname"
        ),
        "triggers": await pool.fetch(
            "SELECT tgrelid, tgname, pg_get_triggerdef(oid) FROM pg_trigger "
            "WHERE NOT tgisinternal ORDER BY tgrelid, tgname"
        ),
    }
    for table in ("ingest_sessions", "ingest_files", "dataset_revisions"):
        snapshot[table] = await pool.fetchval(
            f"SELECT jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text) FROM {table} t"
        )
    return snapshot


async def _seed_legacy_link(dsn: str) -> tuple[UUID, UUID]:
    """Create one historical hardlink ledger in a disposable migration-test database."""
    pool = await asyncpg.create_pool(dsn)
    try:
        organization = await _insert_organization(pool, slug="legacy-links")
        project = await _insert_project(pool, organization_id=organization, slug="legacy")
        dataset = await _insert_dataset(pool, project_id=project, slug="legacy")
        session = await _insert_ingest_session(pool, dataset_id=dataset)
        file = await _insert_ingest_file(pool, ingest_id=session, action="hardlink", part_count=0)
        return file, dataset
    finally:
        await pool.close()


async def _remove_legacy_fixture(dsn: str, file_id: UUID) -> None:
    """Prove the refused upgrade rolled back, then remove its synthetic blocking fixture."""
    pool = await asyncpg.create_pool(dsn)
    try:
        assert (
            await pool.fetchval("SELECT version_num FROM alembic_version") == "0009_ingest_ledger"
        )
        assert (
            await pool.fetchval("SELECT action FROM ingest_files WHERE file_id = $1", file_id)
            == "hardlink"
        )
        await pool.execute("DELETE FROM ingest_files WHERE file_id = $1", file_id)
    finally:
        await pool.close()


async def _seed_identical_revisions(dsn: str, dataset_id: UUID) -> tuple[UUID, UUID]:
    """Distinct committed revision identities may have identical content after upgrading."""
    pool = await asyncpg.create_pool(dsn)
    try:
        first = await _insert_dataset_revision(
            pool, dataset_id=dataset_id, revision_number=1, manifest_sha256="a" * 64
        )
        second = await _insert_dataset_revision(
            pool, dataset_id=dataset_id, revision_number=2, manifest_sha256="a" * 64
        )
        return first, second
    finally:
        await pool.close()


async def _assert_failed_downgrade_preserves_revisions(dsn: str, first: UUID, second: UUID) -> None:
    """A refused downgrade leaves both repeated-content revisions and the current schema intact."""
    pool = await asyncpg.create_pool(dsn)
    try:
        assert (
            await pool.fetchval("SELECT version_num FROM alembic_version") == "0010_independent_raw"
        )
        assert (
            await pool.fetchval(
                "SELECT count(*) FROM dataset_revisions WHERE id = ANY($1::uuid[])", [first, second]
            )
            == 2
        )
        assert not await pool.fetchval(
            "SELECT EXISTS (SELECT FROM information_schema.columns "
            "WHERE table_name = 'ingest_sessions' AND column_name = 'parent_revision_id')"
        )
    finally:
        await pool.close()


#: Every relation, constraint, trigger and function release tags owned at
#: ``0012_raw_web_catalogs``: the table with its key, uniqueness and citation
#: indexes, its checks and foreign keys, and the immutability trigger with
#: the function it runs.
_RELEASE_OBJECTS = frozenset(
    {
        "releases",
        "releases_pkey",
        "releases_dataset_id_tag_key",
        "releases_revision",
        "releases_tag_check",
        "releases_check",
        "releases_dataset_id_fkey",
        "releases_revision_dataset_fk",
        "releases_immutable_before_update",
        "releases_immutable",
    }
)

#: The capability codes of the release-tag family, as a ``LIKE`` pattern.
_RELEASE_CAPABILITIES = "release.%"


def test_retiring_release_tags_drops_their_objects_and_capability_and_refuses_a_downgrade() -> None:
    """Upgrading to head drops release tags and their capability but keeps every revision."""
    with PostgresContainer("postgres:16") as postgres:
        config = _config(postgres.get_connection_url(driver="asyncpg"))
        command.upgrade(config, "0012_raw_web_catalogs")
        asyncio.run(_assert_release_retirement(config, postgres.get_connection_url(driver=None)))


async def _assert_release_retirement(config: Config, dsn: str) -> None:
    """Seed a tagged revision, upgrade to head, then check what was dropped and what remains.

    The capability vocabulary left at head is exactly the one the role model
    declares, and the developer role no longer describes tagging. Downgrading
    is refused and leaves the upgraded schema in place.
    """
    pool = await asyncpg.create_pool(dsn)
    try:
        organization = await _insert_organization(pool, slug="tagged-catalog")
        project = await _insert_project(pool, organization_id=organization, slug="tagged")
        dataset = await _insert_dataset(pool, project_id=project, slug="tagged")
        revision = await _insert_dataset_revision(pool, dataset_id=dataset, revision_number=1)
        await pool.execute(
            """
            INSERT INTO releases (id, dataset_id, tag, revision_id, created_by, created_at)
            VALUES ($1, $2, 'v1', $3, 'migration-test', now())
            """,
            uuid7(),
            dataset,
            revision,
        )
        assert await _release_objects(pool) == _RELEASE_OBJECTS
        assert await _release_capability_rows(pool) == (1, 3)

        await asyncio.to_thread(command.upgrade, config, "head")

        assert await _release_objects(pool) == frozenset()
        assert await _release_capability_rows(pool) == (0, 0)
        codes = {row["code"] for row in await pool.fetch("SELECT code FROM capabilities")}
        assert codes == CAPABILITIES
        developer = await pool.fetchval("SELECT description FROM roles WHERE code = 'developer'")
        assert developer == ROLES["developer"].description
        kept = await pool.fetchval(
            "SELECT revision_number FROM dataset_revisions WHERE id = $1", revision
        )
        assert kept == 1

        head = await pool.fetchval("SELECT version_num FROM alembic_version")
        with pytest.raises(RuntimeError, match="retired release tags cannot be restored online"):
            await asyncio.to_thread(command.downgrade, config, "0012_raw_web_catalogs")
        assert await pool.fetchval("SELECT version_num FROM alembic_version") == head
        assert await _release_objects(pool) == frozenset()
    finally:
        await pool.close()


async def _release_objects(pool: asyncpg.Pool) -> frozenset[str]:
    """Name every public relation, constraint, trigger and function named for release tags."""
    rows = await pool.fetch(
        """
        SELECT relname AS name FROM pg_class
        WHERE relnamespace = 'public'::regnamespace AND relname LIKE 'releases%'
        UNION SELECT conname FROM pg_constraint
        WHERE connamespace = 'public'::regnamespace AND conname LIKE 'releases%'
        UNION SELECT tgname FROM pg_trigger
        WHERE NOT tgisinternal AND tgname LIKE 'releases%'
        UNION SELECT proname FROM pg_proc
        WHERE pronamespace = 'public'::regnamespace AND proname LIKE 'releases%'
        """
    )
    return frozenset(row["name"] for row in rows)


async def _release_capability_rows(pool: asyncpg.Pool) -> tuple[int, int]:
    """Count the release capabilities and the role grants that name them."""
    capabilities = await pool.fetchval(
        "SELECT count(*) FROM capabilities WHERE code LIKE $1", _RELEASE_CAPABILITIES
    )
    grants = await pool.fetchval(
        "SELECT count(*) FROM role_capabilities WHERE capability_code LIKE $1",
        _RELEASE_CAPABILITIES,
    )
    return capabilities, grants
