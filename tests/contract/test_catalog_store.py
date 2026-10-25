"""PostgreSQL constraints for the surviving catalog and derived representations."""

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
    command.upgrade(_config(sqlalchemy_url), "0014_retire_legacy_raw")


async def _assert_against(dsn: str) -> None:
    """Runs every catalog schema constraint, trigger, and vocabulary assertion against one pool."""
    pool = await asyncpg.create_pool(dsn)
    try:
        await _assert_organizations_lifecycle_state_vocabulary(pool)
        await _assert_projects_lifecycle_state_vocabulary(pool)
        await _assert_datasets_lifecycle_state_vocabulary(pool)
        await _assert_products_lifecycle_state_vocabulary(pool)
        await _assert_snapshots_state_vocabulary(pool)
        await _assert_product_versions_state_vocabulary(pool)
        await _assert_science_profiles_document_sha256_format(pool)
        await _assert_jobs_kind_vocabulary(pool)
        await _assert_jobs_state_is_still_unconstrained(pool)
        await _assert_lineage_edges_kind_vocabulary(pool)
        await _assert_jsonb_object_shape_columns(pool)
        await _assert_projects_raw_retention_policy_rejects_non_objects(pool)
        await _assert_json_null_is_refused_where_sql_null_means_absent(pool)
    finally:
        await pool.close()


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


_JOB_KINDS = (
    "bronze_build",
    "canonicalize",
    "product_run",
    "validate",
    "polaris_sync",
    "retention",
    "reconcile",
)

_LINEAGE_KINDS = ("bronze_snapshot", "silver_snapshot", "gold_version")


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


async def _assert_lineage_edges_kind_vocabulary(pool: asyncpg.Pool) -> None:
    """``lineage_edges`` refuses 'gold_snapshot' on either end and accepts the three real kinds.

    Both ends of a lineage edge draw on the same three typed nodes.
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


async def _assert_jsonb_object_shape_columns(pool: asyncpg.Pool) -> None:
    """Surviving object columns refuse scalar, array and null JSON literals."""
    organization_id = await _insert_organization(pool, slug="jsonb-shape-generic")
    project_id = await _insert_project(pool, organization_id=organization_id, slug="jsonb-shape")
    dataset_id = await _insert_dataset(pool, project_id=project_id, slug="jsonb-shape")
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

    cases = (
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
    )
    await _assert_jsonb_shape_columns(pool, cases)


async def _assert_projects_raw_retention_policy_rejects_non_objects(pool: asyncpg.Pool) -> None:
    """Project retention policy refuses scalar and array JSON, and accepts an object."""
    organization_id = await _insert_organization(pool, slug="jsonb-shape-projects")
    project_id = await _insert_project(pool, organization_id=organization_id, slug="jsonb-shape")

    for literal in ('"just a string"', "[]"):
        with pytest.raises(asyncpg.exceptions.CheckViolationError):
            await pool.execute(
                "UPDATE projects SET raw_retention_policy = $1::jsonb WHERE id = $2",
                literal,
                project_id,
            )

    await pool.execute(
        "UPDATE projects SET raw_retention_policy = $1::jsonb WHERE id = $2",
        json.dumps({"days": 30}),
        project_id,
    )


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


def test_postgres_catalog_constraints_at_head() -> None:
    """Existing catalog constraints also hold after a clean upgrade to head."""
    with PostgresContainer("postgres:16") as postgres:
        _migrate(postgres.get_connection_url(driver="asyncpg"))
        asyncio.run(_assert_against(postgres.get_connection_url(driver=None)))
