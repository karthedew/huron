"""Prove irreversible legacy retirement against disposable PostgreSQL databases."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path
from uuid import UUID

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from testcontainers.postgres import PostgresContainer

pytestmark = pytest.mark.contract

_ROOT = Path(__file__).resolve().parents[2]
_REVISION = "0014_retire_legacy_raw"
_TABLES = (
    "raw_catalog_publications",
    "raw_external_datasets",
    "ingest_recoveries",
    "ingest_commit_intents",
    "ingest_files",
    "purge_records",
    "revision_amendments",
    "ingest_sessions",
    "dataset_revisions",
    "audit_events",
    "outbox_events",
    "sessions",
    "local_credentials",
    "reconciliation_findings",
)
_FUNCTIONS = (
    "reject_raw_external_mutation",
    "reject_commit_intent_mutation",
    "protect_recovery_ownership",
    "ingest_session_revision_guard",
    "local_credentials_kind_guard",
)


def _config(sqlalchemy_url: str) -> Config:
    """Point Alembic at the disposable database and repository migrations."""
    config = Config()
    config.set_main_option("script_location", str(_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", sqlalchemy_url)
    return config


def _migrate(sqlalchemy_url: str) -> None:
    """Upgrade the disposable database to head without flags or data guards."""
    command.upgrade(_config(sqlalchemy_url), "head")


async def _assert_retired(dsn: str) -> None:
    """All retired objects are absent and both lineage endpoints reject Raw revisions."""
    connection = await asyncpg.connect(dsn)
    try:
        assert await connection.fetchval("SELECT version_num FROM alembic_version") == _REVISION
        for table in _TABLES:
            assert await connection.fetchval("SELECT to_regclass($1)", f"public.{table}") is None
        assert not await connection.fetchval(
            "SELECT EXISTS (SELECT FROM pg_proc WHERE pronamespace = 'public'::regnamespace "
            "AND proname = ANY($1::text[]))",
            list(_FUNCTIONS),
        )
        for upstream, downstream, constraint in (
            ("raw_revision", "bronze_snapshot", "lineage_edges_upstream_kind_vocabulary"),
            ("bronze_snapshot", "raw_revision", "lineage_edges_downstream_kind_vocabulary"),
        ):
            with pytest.raises(asyncpg.CheckViolationError, match=constraint) as error:
                await connection.execute(
                    "INSERT INTO lineage_edges "
                    "(id, upstream_kind, upstream_id, downstream_kind, downstream_id, created_at) "
                    "VALUES ($1, $2, $1, $3, $1, now())",
                    UUID(int=100),
                    upstream,
                    downstream,
                )
            assert error.value.sqlstate == "23514"
    finally:
        await connection.close()


def test_upgrade_drops_every_legacy_table_and_function() -> None:
    """A fresh database reaches head without any legacy objects or Raw lineage vocabulary."""
    with PostgresContainer("postgres:16") as postgres:
        _migrate(postgres.get_connection_url(driver="asyncpg"))
        asyncio.run(_assert_retired(postgres.get_connection_url(driver=None)))


_SEED = """
INSERT INTO organizations (id, slug, title, created_at, updated_at)
VALUES ('00000000-0000-0000-0000-000000000001', 'retirement', 'Retirement', now(), now());
INSERT INTO projects (id, organization_id, slug, title, classification_default,
    created_at, updated_at)
VALUES ('00000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000001',
        'retirement', 'Retirement', 'open', now(), now());
INSERT INTO datasets (id, project_id, slug, title, profile_name, profile_version,
                      data_classification, created_at, updated_at)
VALUES ('00000000-0000-0000-0000-000000000003', '00000000-0000-0000-0000-000000000002',
        'retirement', 'Retirement', 'generic', '1', 'open', now(), now());
INSERT INTO dataset_revisions (id, dataset_id, revision_number, manifest_sha256, metadata_sha256,
                              revision_path, file_count, total_bytes, committed_by, committed_at)
VALUES ('00000000-0000-0000-0000-000000000004', '00000000-0000-0000-0000-000000000003',
        1, repeat('a',64), repeat('b',64), 'retirement/r000001', 1, 0, 'scientist', now());
INSERT INTO ingest_sessions (id, dataset_id, revision_id, revision_number, manifest_sha256,
                             state, expires_at, created_by, created_at, updated_at)
VALUES ('00000000-0000-0000-0000-000000000005', '00000000-0000-0000-0000-000000000003',
        '00000000-0000-0000-0000-000000000004', 1, repeat('a',64),
        'COMMITTED', now(), 'scientist', now(), now());
INSERT INTO ingest_files (file_id, ingest_id, path, size, expected_sha256, action, part_count)
VALUES ('00000000-0000-0000-0000-000000000006', '00000000-0000-0000-0000-000000000005',
        'data.bin', 0, repeat('a',64), 'upload', 1);
INSERT INTO ingest_commit_intents
    (ingest_id, command, manifest, metadata, committed, committed_by, committed_at)
VALUES ('00000000-0000-0000-0000-000000000005', '\\x00', '\\x00', '\\x00', '\\x00',
    'scientist', now());
INSERT INTO ingest_recoveries
    (ingest_id, attempt_id, original_path, candidate_path, checkpoint, actor,
    started_at, updated_at)
VALUES ('00000000-0000-0000-0000-000000000005', '00000000-0000-0000-0000-000000000007',
        'original', 'candidate', 'RECORDED', 'scientist', now(), now());
INSERT INTO revision_amendments
    (id, revision_id, sequence, changed_keys, document, created_by, created_at)
VALUES ('00000000-0000-0000-0000-000000000008', '00000000-0000-0000-0000-000000000004',
        1, '{}', '{}', 'scientist', now());
INSERT INTO purge_records (id, revision_id, reason, requested_by, requested_at)
VALUES ('00000000-0000-0000-0000-000000000009', '00000000-0000-0000-0000-000000000004',
        'expired', 'scientist', now());
INSERT INTO raw_external_datasets (target_key, endpoint, realm, catalog, namespace,
    name, dataset_id)
VALUES (repeat('a',64), 'https://catalog.invalid', 'realm', 'catalog', '{}', 'data',
        '00000000-0000-0000-0000-000000000003');
INSERT INTO raw_catalog_publications (revision_id)
VALUES ('00000000-0000-0000-0000-000000000004');
INSERT INTO audit_events (id, kind, actor, subject_kind, payload, created_at)
VALUES ('00000000-0000-0000-0000-000000000010', 'revision.committed', 'scientist',
    'dataset', '{}', now());
INSERT INTO outbox_events (id, kind, subject_id, payload, created_at)
VALUES ('00000000-0000-0000-0000-000000000011', 'revision.committed',
        '00000000-0000-0000-0000-000000000004', '{}', now());
INSERT INTO principals (id, kind, subject, created_at)
VALUES ('00000000-0000-0000-0000-000000000012', 'user', 'scientist', now());
INSERT INTO local_credentials (principal_id, password_hash, updated_at, updated_by)
VALUES ('00000000-0000-0000-0000-000000000012', '$argon2id$fixture', now(), 'operator');
INSERT INTO sessions (id, secret_sha256, csrf_token, subject, authentication_method,
                      created_at, last_seen_at, idle_expires_at, absolute_expires_at)
VALUES ('00000000-0000-0000-0000-000000000013', repeat('a',64), 'csrf', 'scientist',
        'password', now(), now(), now(), now());
INSERT INTO reconciliation_findings (id, code, severity, detail, found_at)
VALUES ('00000000-0000-0000-0000-000000000014', 'missing', 'warning', '{}', now());
INSERT INTO lineage_edges (id, upstream_kind, upstream_id, downstream_kind,
    downstream_id, created_at)
VALUES ('00000000-0000-0000-0000-000000000015', 'raw_revision',
        '00000000-0000-0000-0000-000000000004', 'bronze_snapshot',
        '00000000-0000-0000-0000-000000000020', now()),
       ('00000000-0000-0000-0000-000000000016', 'bronze_snapshot',
        '00000000-0000-0000-0000-000000000020', 'raw_revision',
        '00000000-0000-0000-0000-000000000004', now()),
       ('00000000-0000-0000-0000-000000000017', 'bronze_snapshot',
        '00000000-0000-0000-0000-000000000020', 'silver_snapshot',
        '00000000-0000-0000-0000-000000000021', now());
"""


async def _seed_legacy_rows(dsn: str) -> dict[str, list[asyncpg.Record]]:
    """Populate every retired table and capture surviving data before migration."""
    connection = await asyncpg.connect(dsn)
    try:
        await connection.execute(_SEED)
        for table in _TABLES:
            assert await connection.fetchval(f"SELECT count(*) FROM {table}") == 1
        return await _surviving_rows(connection)
    finally:
        await connection.close()


async def _surviving_rows(connection: asyncpg.Connection) -> dict[str, list[asyncpg.Record]]:
    """Capture hierarchy, principal and role seeds that retirement must leave unchanged."""
    return {
        table: await connection.fetch(f"SELECT * FROM {table} ORDER BY 1, 2")
        for table in (
            "organizations",
            "projects",
            "datasets",
            "principals",
            "roles",
            "capabilities",
            "role_capabilities",
        )
    }


async def _assert_survivors(dsn: str, before: dict[str, list[asyncpg.Record]]) -> None:
    """Retirement preserves hierarchy and RBAC, and deletes only obsolete lineage edges."""
    connection = await asyncpg.connect(dsn)
    try:
        assert await _surviving_rows(connection) == before
        assert await connection.fetchval("SELECT array_agg(id) FROM lineage_edges") == [
            UUID("00000000-0000-0000-0000-000000000017")
        ]
    finally:
        await connection.close()


def test_upgrade_drops_populated_legacy_tables() -> None:
    """An unconditional upgrade discards every legacy row while preserving unrelated data."""
    with PostgresContainer("postgres:16") as postgres:
        url = postgres.get_connection_url(driver="asyncpg")
        dsn = postgres.get_connection_url(driver=None)
        command.upgrade(_config(url), "0013_retire_releases")
        before = asyncio.run(_seed_legacy_rows(dsn))
        _migrate(url)
        asyncio.run(_assert_retired(dsn))
        asyncio.run(_assert_survivors(dsn, before))


def test_offline_sql_renders_the_drops() -> None:
    """The Alembic CLI renders the entire retirement in one offline transaction."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "upgrade",
            "0013_retire_releases:0014_retire_legacy_raw",
            "--sql",
        ],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    sql = result.stdout
    assert sql.count("BEGIN;") == sql.count("COMMIT;") == 1
    for table in _TABLES:
        assert table in sql
    for statement in (
        "DROP TABLE raw_catalog_publications, raw_external_datasets, ingest_recoveries,",
        "DROP TABLE audit_events;",
        "DROP TABLE outbox_events;",
        "DROP TABLE sessions, local_credentials;",
        "DROP TABLE reconciliation_findings;",
        "DROP FUNCTION reject_raw_external_mutation(), reject_commit_intent_mutation(),",
        "DROP FUNCTION local_credentials_kind_guard();",
        "DELETE FROM lineage_edges",
        "ALTER TABLE lineage_edges",
    ):
        assert statement in sql
    for function in _FUNCTIONS:
        assert f"{function}()" in sql


def test_downgrade_from_the_retirement_raises() -> None:
    """A downgrade refuses discarded data restoration and leaves head intact."""
    with PostgresContainer("postgres:16") as postgres:
        url = postgres.get_connection_url(driver="asyncpg")
        _migrate(url)
        with pytest.raises(
            RuntimeError, match=r"^legacy Raw and credential tables cannot be restored$"
        ):
            command.downgrade(_config(url), "-1")
        asyncio.run(_assert_retired(postgres.get_connection_url(driver=None)))
