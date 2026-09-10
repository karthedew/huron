"""Frozen publication evidence under real PostgreSQL row-lock contention."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import asyncpg
import pytest
from alembic import command
from sqlalchemy.exc import DBAPIError
from testcontainers.postgres import PostgresContainer

from huron.core._ingest import IngestService
from huron.pkg.catalog.documents import (
    CommitIntent,
    CommitRecord,
    MetadataDocument,
    decode_manifest,
)
from huron.pkg.catalog.errors import (
    ContractMismatch,
    IngestSessionExpired,
    PreconditionFailed,
    ResourceNotFound,
)
from huron.pkg.catalog.ingest import IngestState
from huron.pkg.catalog.manifest import ManifestEntry, canonical_bytes
from huron.pkg.catalog.persistence import IdempotencyClaim
from huron.pkg.metastore import PostgresHierarchyStore, Visibility
from huron.pkg.rawstore import PosixRawStore
from tests.contract.test_hierarchy_store import (
    MIGRATIONS_DIR,
    _config,
    _migrate,
    _wait_until_a_backend_blocks_on,
)
from tests.hierarchy_contract import seed_hierarchy
from tests.unit.support import FakeClock

if TYPE_CHECKING:
    from pathlib import Path

    from huron.pkg.catalog.ingest import IngestSession

pytestmark = pytest.mark.contract


def test_commit_intents_serialize_and_remain_immutable(tmp_path: Path) -> None:
    """Contending commits retain one instant and byte set, rejecting mutation and lost ownership."""
    with PostgresContainer("postgres:16") as postgres:
        _migrate(postgres.get_connection_url(driver="asyncpg"))
        asyncio.run(_assert_frozen_evidence(postgres.get_connection_url(driver=None), tmp_path))


async def _assert_frozen_evidence(dsn: str, root: Path) -> None:
    pool = await asyncpg.create_pool(dsn)
    try:
        clock = FakeClock(datetime(2026, 1, 1, tzinfo=UTC))
        store = PostgresHierarchyStore(pool, clock=clock)
        hierarchy = await seed_hierarchy(store)
        dataset = await store.dataset(hierarchy.datasets["run-0001"], Visibility.ALL)
        project = await store.project(dataset.project_id, Visibility.ALL)
        organization = await store.organization(project.organization_id, Visibility.ALL)
        for read in (store.ingest_session, store.ingest_file):
            with pytest.raises(ResourceNotFound):
                await read(uuid4())
        with pytest.raises(ResourceNotFound):
            async with store.transaction() as writer:
                await writer.lock_ingest_session(uuid4())
        raw = PosixRawStore(root)
        raw.initialize()
        service = IngestService(raw, store, clock=clock)
        data = b"independent bytes"
        ledger = await service.create(
            dataset,
            files=(ManifestEntry("payload/file", len(data), hashlib.sha256(data).hexdigest()),),
            created_by="user:alice",
            claim=IdempotencyClaim("user:alice", "upload", "a" * 64),
        )
        await service.receive_part(ledger, ledger.files[0], 1, [data], content_length=len(data))
        ledger = await service.verify(await service.ledger(ledger.id))
        metadata = {"title": "Run", "creators": ["alice"]}
        manifest = raw.read_document(root / ".staging" / ledger.id.hex / "envelope/manifest.json")
        decoded = decode_manifest(manifest)
        document = MetadataDocument.compose(
            metadata,
            manifest=decoded,
            organization=organization,
            project=project,
            dataset=dataset,
            revision_number=ledger.revision_number,
            committed_by="user:alice",
            committed_at=clock.now(),
            data_classification="open",
        )
        marker = CommitRecord(
            ledger.revision_id,
            ledger.dataset_id,
            ledger.revision_number,
            decoded.sha256,
            document.sha256,
            1,
            len(data),
            "user:alice",
            clock.now(),
        )
        intent = CommitIntent(
            canonical_bytes(metadata), manifest, document.canonical, marker.canonical
        )
        proposed = ledger.session.begin_commit(manifest_sha256=decoded.sha256, now=clock.now())
        locked = asyncio.Event()

        async def first() -> tuple[IngestSession, CommitIntent]:
            async with store.transaction() as writer:
                result = await writer.freeze_commit(proposed, intent, expected_etag=ledger.etag)
                locked.set()
                await _wait_until_a_backend_blocks_on(pool, query_fragment="FOR UPDATE")
            return result

        async def second() -> tuple[IngestSession, CommitIntent]:
            await locked.wait()
            later_document = document.as_dict()
            later_document["committed_at"] = "2026-01-01T00:00:01Z"
            later_bytes = canonical_bytes(later_document)
            later_marker = replace(
                marker,
                committed_at=clock.now() + timedelta(seconds=1),
                metadata_sha256=hashlib.sha256(later_bytes).hexdigest(),
            )
            later = CommitIntent(intent.command, manifest, later_bytes, later_marker.canonical)
            async with store.transaction() as writer:
                return await writer.freeze_commit(proposed, later, expected_etag=ledger.etag)

        winner, replay = await asyncio.gather(first(), second())
        assert winner == replay == (proposed, intent)
        persisted = await pool.fetchrow(
            "SELECT * FROM ingest_commit_intents WHERE ingest_id = $1", ledger.id
        )
        assert persisted["committed_at"] == marker.committed_at
        for name in ("command", "manifest", "metadata", "committed"):
            assert persisted[name] == getattr(intent, name)
            assert persisted[f"{name}_sha256"] == hashlib.sha256(persisted[name]).hexdigest()
        changed_metadata = document.as_dict()
        changed_metadata["title"] = "Different"
        encoded = canonical_bytes(changed_metadata)
        changed_marker = replace(marker, metadata_sha256=hashlib.sha256(encoded).hexdigest())
        changed = replace(
            intent,
            command=canonical_bytes({**metadata, "title": "Different"}),
            metadata=encoded,
            committed=changed_marker.canonical,
        )
        with pytest.raises(ContractMismatch):
            async with store.transaction() as writer:
                await writer.freeze_commit(proposed, changed, expected_etag=ledger.etag)
        for statement in (
            "UPDATE ingest_commit_intents SET command = command WHERE ingest_id = $1",
            "DELETE FROM ingest_commit_intents WHERE ingest_id = $1",
        ):
            with pytest.raises(asyncpg.CheckViolationError, match="immutable"):
                await pool.execute(statement, ledger.id)
        async with store.transaction() as writer:
            await writer.update_ingest_session(proposed.recover(), expected_etag=proposed.etag)
        with pytest.raises(PreconditionFailed):
            async with store.transaction() as writer:
                await writer.freeze_commit(proposed, intent, expected_etag=proposed.etag)
        with pytest.raises(IngestSessionExpired):
            async with store.transaction() as writer:
                await writer.renew_ingest_session(proposed)
        await pool.execute(
            """INSERT INTO ingest_recoveries
               (ingest_id, attempt_id, original_path, candidate_path, checkpoint, actor,
                started_at, updated_at)
               VALUES ($1, $1, 'original', 'candidate', 'CLAIMED', 'operator', $2, $2)""",
            ledger.id,
            clock.now(),
        )
        for column, value in (
            ("original_path", "changed"),
            ("candidate_path", "changed"),
            ("actor", "other"),
        ):
            with pytest.raises(asyncpg.CheckViolationError, match="ownership is immutable"):
                await pool.execute(
                    f"UPDATE ingest_recoveries SET {column} = $1 WHERE ingest_id = $2",
                    value,
                    ledger.id,
                )
        await pool.execute(
            "UPDATE ingest_recoveries SET checkpoint = 'RELOCATED' WHERE ingest_id = $1", ledger.id
        )
        assert (await store.ingest_session(ledger.id)).state is IngestState.RECOVERING
        for index in ("one_open_ingest_per_dataset", "one_claim_per_revision_number"):
            predicate = await pool.fetchval(
                "SELECT pg_get_expr(indpred, indrelid) FROM pg_index "
                "WHERE indexrelid = $1::regclass",
                index,
            )
            assert await pool.fetchval(
                f"SELECT {predicate} FROM ingest_sessions WHERE id = $1", ledger.id
            )
        constraint = await pool.fetchval(
            "SELECT conname FROM pg_constraint WHERE conrelid = 'ingest_sessions'::regclass "
            "AND conname = 'ingest_sessions_state_check' AND contype = 'c'"
        )
        assert constraint == "ingest_sessions_state_check"
        assert f"-- [db] {constraint}:" in (MIGRATIONS_DIR / "schema.sql").read_text()
        assert await pool.fetchval("SELECT count(*) FROM ingest_commit_intents") == 1
        assert await pool.fetchval("SELECT count(*) FROM dataset_revisions") == 0
    finally:
        await pool.close()


def test_migration_refuses_every_nonterminal_legacy_state(tmp_path: Path) -> None:
    """The real migration refuses unfinished legacy writers and preserves terminal sessions."""
    with PostgresContainer("postgres:16") as postgres:
        url = postgres.get_connection_url(driver="asyncpg")
        command.upgrade(_config(url), "0010_independent_raw")
        asyncio.run(_assert_legacy_refusal(postgres.get_connection_url(driver=None), url))


async def _assert_legacy_refusal(dsn: str, url: str) -> None:
    pool = await asyncpg.create_pool(dsn)
    try:
        clock = FakeClock(datetime(2026, 1, 1, tzinfo=UTC))
        store = PostgresHierarchyStore(pool, clock=clock)
        hierarchy = await seed_hierarchy(store)
        async with store.transaction() as writer:
            session = await writer.begin_ingest(
                hierarchy.datasets["run-0001"],
                "a" * 64,
                created_by="user:alice",
                files=(),
            )
        for state in ("PREPARING", "UPLOADING", "VERIFYING", "COMMITTING"):
            await pool.execute(
                "UPDATE ingest_sessions SET state = $1 WHERE id = $2",
                state,
                session.lease.ingest_id,
            )
            with pytest.raises(DBAPIError, match="Nonterminal legacy ingests"):
                await asyncio.to_thread(command.upgrade, _config(url), "head")
            assert (
                await pool.fetchval("SELECT version_num FROM alembic_version")
                == "0010_independent_raw"
            )
            assert await pool.fetchval("SELECT to_regclass('ingest_commit_intents')") is None
        await pool.execute(
            "UPDATE ingest_sessions SET state = 'FAILED' WHERE id = $1", session.lease.ingest_id
        )
        await asyncio.to_thread(command.upgrade, _config(url), "head")
        assert await pool.fetchval("SELECT version_num FROM alembic_version") == "0011_verified_raw"
        assert await pool.fetchval("SELECT count(*) FROM ingest_sessions") == 1
    finally:
        await pool.close()


@pytest.mark.parametrize("same_key", [False, True])
def test_concurrent_commits_publish_once_with_distinct_attempt_clocks(
    tmp_path: Path, same_key: bool
) -> None:
    """Real filesystem and PostgreSQL writers converge on one immutable revision and audit event."""
    with PostgresContainer("postgres:16") as postgres:
        _migrate(postgres.get_connection_url(driver="asyncpg"))
        asyncio.run(
            _assert_concurrent_publication(
                postgres.get_connection_url(driver=None), tmp_path, same_key
            )
        )


async def _assert_concurrent_publication(dsn: str, root: Path, same_key: bool) -> None:
    pool = await asyncpg.create_pool(dsn)
    try:
        clock = FakeClock(datetime(2026, 1, 1, tzinfo=UTC))
        store = PostgresHierarchyStore(pool, clock=clock)
        hierarchy = await seed_hierarchy(store)
        dataset = await store.dataset(hierarchy.datasets["run-0001"], Visibility.ALL)
        raw = PosixRawStore(root)
        raw.initialize()
        service = IngestService(raw, store, clock=clock)
        data = b"concurrent publication"
        ledger = await service.create(
            dataset,
            files=(ManifestEntry("payload/file", len(data), hashlib.sha256(data).hexdigest()),),
            created_by="user:alice",
            claim=IdempotencyClaim("user:alice", "upload", "a" * 64),
        )
        await service.receive_part(ledger, ledger.files[0], 1, [data], content_length=len(data))
        ledger = await service.verify(await service.ledger(ledger.id))
        later = IngestService(raw, store, clock=FakeClock(clock.now() + timedelta(seconds=1)))
        metadata = {"title": "Run", "creators": ["alice"]}
        results = await asyncio.gather(
            *(
                operation.commit(
                    ledger,
                    expected_etag=ledger.etag,
                    manifest_sha256=ledger.manifest_sha256,
                    metadata=metadata,
                    committed_by="user:alice",
                    claim=IdempotencyClaim(
                        "user:alice", f"commit-{0 if same_key else index}", "b" * 64
                    ),
                )
                for index, operation in enumerate((service, later))
            )
        )
        assert results[0] == results[1]
        assert await pool.fetchval("SELECT count(*) FROM dataset_revisions") == 1
        assert (
            await pool.fetchval(
                "SELECT count(*) FROM audit_events WHERE kind = 'revision.committed'"
            )
            == 1
        )
        assert await pool.fetchval("SELECT count(*) FROM outbox_events") == 1
        assert (await store.ingest_session(ledger.id)).state is IngestState.COMMITTED
        marker = CommitRecord.decode(
            raw.read_document(root / results[0].revision_path / "COMMITTED")
        )
        assert marker.committed_at == results[0].committed_at
        assert raw.read_document(root / results[0].revision_path / "payload/file") == data
    finally:
        await pool.close()
