"""Schema-0010 maintenance preserves identity, terminalizes sessions and records findings."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import PurePosixPath
from uuid import UUID, uuid4

import asyncpg
import pytest
from alembic import command
from testcontainers.postgres import PostgresContainer

from huron.core.catalog.types import EntityRef
from huron.core.raw.types import RevisionRecord
from huron.core.raw.paths import parse_revision_dir, revision_dir
from huron.core.metastore.legacy import PostgresLegacyMaintenance
from tests.contract.test_catalog_store import (
    _config,
    _insert_dataset,
    _insert_ingest_session_claiming,
    _insert_organization,
    _insert_project,
)

pytestmark = pytest.mark.contract


def test_legacy_maintenance_resolves_only_verified_committing_sessions_before_migration() -> None:
    """Healthy finals commit matching sessions; corrupt and incomplete work fails with audit."""
    with PostgresContainer("postgres:16") as postgres:
        url = postgres.get_connection_url(driver="asyncpg")
        command.upgrade(_config(url), "0010_independent_raw")
        asyncio.run(_exercise_legacy(postgres.get_connection_url(driver=None)))
        command.upgrade(_config(url), "head")
        asyncio.run(_refuse_current_schema(postgres.get_connection_url(driver=None)))


async def _exercise_legacy(dsn: str) -> None:
    async with asyncpg.create_pool(dsn) as pool:
        instant = datetime(2026, 1, 1, tzinfo=UTC)
        maintenance = PostgresLegacyMaintenance(pool, lambda: instant)
        assert await maintenance.revision_paths() == ()
        organization = await _insert_organization(pool, slug="organization")
        project = await _insert_project(pool, organization_id=organization, slug="project")
        records = []
        sessions = []
        for number, (state, findings) in enumerate(
            (("COMMITTING", ()), ("COMMITTING", ("PAYLOAD_CORRUPT",)), ("UPLOADING", ()))
        ):
            dataset = await _insert_dataset(pool, project_id=project, slug=f"dataset-{number}")
            record = _revision(organization, project, dataset, number, instant)
            identity = parse_revision_dir(
                PurePosixPath("/data"), PurePosixPath(record.revision_path)
            )
            assert await maintenance.lookup(identity) is None
            with pytest.raises(ValueError, match="parents"):
                await maintenance.lookup(identity._replace(org_slug="other"))
            sessions.append(
                await _insert_ingest_session_claiming(
                    pool,
                    dataset_id=dataset,
                    revision_number=1,
                    revision_id=record.id,
                    manifest_sha256=record.manifest_sha256,
                    state=state,
                )
            )
            records.append((record, findings))
        unfinished_dataset = await _insert_dataset(pool, project_id=project, slug="unfinished")
        sessions.append(
            await _insert_ingest_session_claiming(
                pool,
                dataset_id=unfinished_dataset,
                revision_number=1,
                revision_id=uuid4(),
                manifest_sha256="a" * 64,
                state="UPLOADING",
            )
        )
        hierarchy = await maintenance.generation_records()
        assert len(hierarchy) == 6
        assert {item.id for item in hierarchy} >= {organization, project, unfinished_dataset}
        root_id, run_id = uuid4(), uuid4()
        await maintenance.resolve("operator", root_id, run_id, tuple(records))
        states = [
            await pool.fetchval("SELECT state FROM ingest_sessions WHERE id=$1", session)
            for session in sessions
        ]
        assert states == ["COMMITTED", "FAILED", "FAILED", "FAILED"]
        assert await pool.fetchval("SELECT count(*) FROM reconciliation_findings") == 1
        assert await pool.fetchval("SELECT count(*) FROM audit_events") == 7
        assert await maintenance.revision_paths() == tuple(
            sorted(r.revision_path for r, _ in records)
        )
        for record, _ in records:
            identity = parse_revision_dir(
                PurePosixPath("/data"), PurePosixPath(record.revision_path)
            )
            assert await maintenance.lookup(identity) == record
        await maintenance.resolve("operator", root_id, run_id, tuple(records))
        assert await pool.fetchval("SELECT count(*) FROM audit_events") == 7
        assert await pool.fetchval("SELECT count(*) FROM reconciliation_findings") == 1


def _revision(
    organization: UUID, project: UUID, dataset: UUID, number: int, instant: datetime
) -> RevisionRecord:
    identifier = uuid4()
    path = revision_dir(
        PurePosixPath("/data"),
        EntityRef(organization, "organization"),
        EntityRef(project, "project"),
        EntityRef(dataset, f"dataset-{number}"),
        1,
        identifier,
    )
    return RevisionRecord(
        identifier, dataset, 1, "a" * 64, "b" * 64, str(path), "scientist", instant, 1, 7
    )


async def _refuse_current_schema(dsn: str) -> None:
    async with asyncpg.create_pool(dsn) as pool:
        with pytest.raises(ValueError, match="exactly schema 0010"):
            await PostgresLegacyMaintenance(pool, lambda: datetime.now(UTC)).revision_paths()


@pytest.mark.parametrize("case", ["changed_record", "session_digest", "session_identity"])
def test_legacy_ambiguity_rolls_back_import_findings_audit_and_session_updates(case: str) -> None:
    """Real rollback preserves prior state when final or session identity conflicts."""
    with PostgresContainer("postgres:16") as postgres:
        command.upgrade(
            _config(postgres.get_connection_url(driver="asyncpg")), "0010_independent_raw"
        )
        asyncio.run(_exercise_ambiguity(postgres.get_connection_url(driver=None), case))


async def _exercise_ambiguity(dsn: str, case: str) -> None:
    async with asyncpg.create_pool(dsn) as pool:
        instant = datetime(2026, 1, 1, tzinfo=UTC)
        maintenance = PostgresLegacyMaintenance(pool, lambda: instant)
        organization = await _insert_organization(pool, slug="organization")
        project = await _insert_project(pool, organization_id=organization, slug="project")
        dataset = await _insert_dataset(pool, project_id=project, slug="dataset-0")
        record = _revision(organization, project, dataset, 0, instant)
        root_id = uuid4()
        await maintenance.resolve("local:0", root_id, uuid4(), ((record, ()),))
        session = await _insert_ingest_session_claiming(
            pool,
            dataset_id=dataset,
            revision_number=1,
            revision_id=uuid4() if case == "session_identity" else record.id,
            manifest_sha256="c" * 64 if case == "session_digest" else record.manifest_sha256,
            state="COMMITTING",
        )
        supplied = replace(record, manifest_sha256="c" * 64) if case == "changed_record" else record
        with pytest.raises(ValueError):
            await maintenance.resolve("local:0", root_id, uuid4(), ((supplied, ("CORRUPT",)),))
        assert (
            await pool.fetchval("SELECT state FROM ingest_sessions WHERE id=$1", session)
            == "COMMITTING"
        )
        assert (
            await pool.fetchval("SELECT state FROM dataset_revisions WHERE id=$1", record.id)
            == "COMMITTED"
        )
        assert await pool.fetchval("SELECT count(*) FROM reconciliation_findings") == 0
        assert await pool.fetchval("SELECT count(*) FROM audit_events") == 1
