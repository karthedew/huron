"""Abrupt writer death preserves publication intent across real storage and PostgreSQL."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import asyncpg
import pytest
from testcontainers.postgres import PostgresContainer

from huron.core.raw._impl.ingest import IngestService
from huron.core.raw.types import SessionLedger
from huron.core.raw import ingest as ingest_module
from huron.core.raw.documents import CommitRecord
from huron.core.foundation.errors import IdempotencyKeyReused
from huron.core.raw.ingest import FileState, IngestState
from huron.core.raw.manifest import ManifestEntry
from huron.core.foundation.retry import IdempotencyClaim
from huron.core.metastore import PostgresHierarchyStore
from huron.core.security.rules import Visibility
from huron.core.rawstore import PosixRawStore
from tests.contract.test_hierarchy_store import _migrate
from tests.hierarchy_contract import seed_hierarchy
from tests.unit.support import FakeClock

pytestmark = pytest.mark.contract
_DATA = b"durable publication evidence"
_NOW = datetime(2026, 1, 1, tzinfo=UTC)


async def _commit(service: IngestService, ledger: SessionLedger) -> None:
    await service.commit(
        ledger,
        expected_etag=ledger.etag,
        manifest_sha256=ledger.manifest_sha256,
        metadata={"title": "Run", "creators": ["alice"]},
        committed_by="user:alice",
        claim=IdempotencyClaim("user:alice", "commit", "b" * 64),
    )


async def killed_commit(dsn: str, root_value: str, session_value: str, boundary: str) -> None:
    """Exit without cleanup at a persisted publication boundary.

    Args:
        dsn: Disposable database connection string.
        root_value: Existing storage root.
        session_value: Verified session identity.
        boundary: Intent, document installation, or final publication boundary.
    """
    pool = await asyncpg.create_pool(dsn)
    root = Path(root_value)
    store = PostgresHierarchyStore(pool, clock=FakeClock(_NOW))
    service = IngestService(PosixRawStore(root), store, clock=FakeClock(_NOW))
    ledger = await service.ledger(UUID(session_value))
    metadata = root / ".staging" / ledger.id.hex / "envelope/metadata.json"
    final_name = f"{ledger.revision_number:06d}--{ledger.revision_id.hex}"
    original_open, original_fsync = os.open, os.fsync

    def open_file(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if boundary == "intent" and flags & os.O_CREAT:
            os._exit(91)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    def flush(descriptor: int) -> None:
        original_fsync(descriptor)
        if (boundary == "document" and metadata.exists()) or (
            boundary == "final" and any(root.rglob(final_name))
        ):
            os._exit(91)

    os.open, os.fsync = open_file, flush
    await _commit(service, ledger)
    os._exit(92)


@pytest.mark.parametrize("boundary", ["intent", "document", "final"])
def test_abrupt_commit_death_retains_the_claim_and_replays_frozen_evidence(
    tmp_path: Path, boundary: str
) -> None:
    """Death before row recording leaves COMMITTING and retries publish the original evidence."""
    with PostgresContainer("postgres:16") as postgres:
        _migrate(postgres.get_connection_url(driver="asyncpg"))
        asyncio.run(
            _assert_commit_death(postgres.get_connection_url(driver=None), tmp_path, boundary)
        )


async def _assert_commit_death(dsn: str, root: Path, boundary: str) -> None:
    pool = await asyncpg.create_pool(dsn)
    try:
        store = PostgresHierarchyStore(pool, clock=FakeClock(_NOW))
        hierarchy = await seed_hierarchy(store)
        dataset = await store.datasets.get(hierarchy.datasets["run-0001"], Visibility.ALL)
        raw = PosixRawStore(root)
        raw.initialize()
        service = IngestService(raw, store, clock=FakeClock(_NOW))
        ledger = await service.create(
            dataset,
            files=(ManifestEntry("payload/file", len(_DATA), hashlib.sha256(_DATA).hexdigest()),),
            created_by="user:alice",
            claim=IdempotencyClaim("user:alice", "upload", "a" * 64),
        )
        await service.receive_part(ledger, ledger.files[0], 1, [_DATA], content_length=len(_DATA))
        ledger = await service.verify(await service.ledger(ledger.id))
        result = await asyncio.to_thread(
            subprocess.run,
            [
                sys.executable,
                "-c",
                "import asyncio,sys; from tests.contract.test_ingest_process_death import "
                "killed_commit; asyncio.run(killed_commit(*sys.argv[1:]))",
                dsn,
                str(root),
                str(ledger.id),
                boundary,
            ],
            capture_output=True,
            check=False,
            timeout=30,
        )
        assert result.returncode == 91, result.stderr.decode()
        assert (await store.ingest_session(ledger.id)).state is IngestState.COMMITTING
        assert await pool.fetchval("SELECT count(*) FROM dataset_revisions") == 0
        assert (
            await pool.fetchval(
                "SELECT count(*) FROM ingest_sessions WHERE dataset_id = $1 "
                "AND revision_number = 1 AND state NOT IN ('ABORTED', 'FAILED')",
                dataset.id,
            )
            == 1
        )
        frozen = await pool.fetchrow(
            "SELECT * FROM ingest_commit_intents WHERE ingest_id = $1", ledger.id
        )
        session = root / ".staging" / ledger.id.hex
        leftovers = {path.name: path.read_bytes() for path in (session / "completion").iterdir()}
        assert (session / "envelope").exists() == (boundary != "final")
        assert (session / "envelope/metadata.json").exists() == (boundary == "document")
        late_clock = FakeClock(_NOW + timedelta(days=2))
        late_store = PostgresHierarchyStore(pool, clock=late_clock)
        with pytest.raises(IdempotencyKeyReused):
            async with late_store.transaction() as writer:
                await writer.claim(IdempotencyClaim("user:alice", "commit", "c" * 64))
        pending = json.loads(
            await pool.fetchval(
                "SELECT response FROM idempotency_records "
                "WHERE principal = 'user:alice' AND key = 'commit'"
            )
        )
        assert pending == {"kind": "ingest_commit", "id": str(ledger.id)}
        later = IngestService(raw, late_store, clock=late_clock)
        await _commit(later, await later.ledger(ledger.id))
        assert (await store.ingest_session(ledger.id)).state is IngestState.COMMITTED
        record = await pool.fetchrow("SELECT * FROM dataset_revisions")
        final = root / record["revision_path"]
        for name in ("manifest", "metadata", "committed"):
            filename = "COMMITTED" if name == "committed" else f"{name}.json"
            assert (final / filename).read_bytes() == frozen[name]
        assert CommitRecord.decode(frozen["committed"]).committed_at == _NOW
        assert (final / "payload/file").read_bytes() == _DATA
        assert (final / "payload/file").stat().st_nlink == 1
        assert {
            path.name: path.read_bytes() for path in (session / "completion").iterdir()
        } == leftovers
        assert await pool.fetchval("SELECT count(*) FROM dataset_revisions") == 1
        assert (
            await pool.fetchval(
                "SELECT count(*) FROM audit_events WHERE kind = 'revision.committed'"
            )
            == 1
        )
        assert await pool.fetchval("SELECT count(*) FROM outbox_events") == 1
    finally:
        await pool.close()


async def _killed_file_completion(
    dsn: str, root_value: str, session_value: str, boundary: str
) -> None:
    pool = await asyncpg.create_pool(dsn)
    store = PostgresHierarchyStore(pool, clock=FakeClock(_NOW))
    service = IngestService(PosixRawStore(Path(root_value)), store, clock=FakeClock(_NOW))
    ledger = await service.ledger(UUID(session_value))
    file = ledger.files[0]
    execute = asyncpg.Connection.execute

    async def execute_and_exit(
        connection: asyncpg.Connection, query: str, *args: object, timeout: float | None = None
    ) -> str:
        completing = query.strip().upper() == "COMMIT;" and await connection.fetchval(
            "SELECT state = 'COMPLETE' FROM ingest_files WHERE file_id = $1", file.file_id
        )
        if completing and boundary == "before":
            os._exit(91)
        result = await execute(connection, query, *args, timeout=timeout)
        if completing and boundary == "after":
            os._exit(91)
        return result

    asyncpg.Connection.execute = execute_and_exit
    await service.receive_part(ledger, file, 1, [_DATA], content_length=len(_DATA))
    os._exit(92)


@pytest.mark.parametrize("boundary", ["before", "after"])
def test_abrupt_file_completion_death_preserves_installed_bytes_and_retries_once(
    tmp_path: Path, boundary: str
) -> None:
    """Death around COMPLETE commit leaves truthful rows and one immutable published inode."""
    with PostgresContainer("postgres:16") as postgres:
        _migrate(postgres.get_connection_url(driver="asyncpg"))
        asyncio.run(
            _assert_file_completion_death(
                postgres.get_connection_url(driver=None), tmp_path, boundary
            )
        )


async def _assert_file_completion_death(dsn: str, root: Path, boundary: str) -> None:
    pool = await asyncpg.create_pool(dsn)
    try:
        store = PostgresHierarchyStore(pool, clock=FakeClock(_NOW))
        hierarchy = await seed_hierarchy(store)
        dataset = await store.datasets.get(hierarchy.datasets["run-0001"], Visibility.ALL)
        raw = PosixRawStore(root)
        raw.initialize()
        service = IngestService(raw, store, clock=FakeClock(_NOW))
        ledger = await service.create(
            dataset,
            files=(ManifestEntry("payload/file", len(_DATA), hashlib.sha256(_DATA).hexdigest()),),
            created_by="user:alice",
            claim=IdempotencyClaim("user:alice", "upload", "a" * 64),
        )
        session = root / ".staging" / ledger.id.hex
        abandoned = session / "completion/abandoned"
        abandoned.write_bytes(b"unpublished candidate")
        result = await asyncio.to_thread(
            subprocess.run,
            [
                sys.executable,
                "-c",
                "import asyncio,sys; from tests.contract.test_ingest_process_death import "
                "_killed_file_completion; asyncio.run(_killed_file_completion(*sys.argv[1:]))",
                dsn,
                str(root),
                str(ledger.id),
                boundary,
            ],
            capture_output=True,
            check=False,
            timeout=30,
        )
        assert result.returncode == 91, result.stderr.decode()
        fresh = await asyncpg.connect(dsn)
        try:
            persisted = await fresh.fetchrow(
                "SELECT state, completed_parts FROM ingest_files WHERE file_id = $1",
                ledger.files[0].file_id,
            )
            assert persisted["state"] == ("PENDING" if boundary == "before" else "COMPLETE")
            assert json.loads(persisted["completed_parts"]) == ([] if boundary == "before" else [1])
            assert await fresh.fetchval("SELECT count(*) FROM dataset_revisions") == 0
        finally:
            await fresh.close()
        installed = session / "envelope/payload/file"
        info = installed.stat()
        upload = session / "upload" / str(ledger.files[0].file_id)
        assert installed.read_bytes() == _DATA
        assert info.st_nlink == 1
        assert info.st_mode & 0o222 == 0
        assert info.st_ino != upload.stat().st_ino
        assert upload.read_bytes() == _DATA
        current = await service.ledger(ledger.id)
        if boundary == "before":
            await service.receive_part(
                current, current.files[0], 1, [_DATA], content_length=len(_DATA)
            )
        else:
            await service.complete_file(current, current.files[0])
        current = await service.ledger(ledger.id)
        assert current.files[0].state is FileState.COMPLETE
        assert current.files[0].completed_parts == frozenset({1})
        assert installed.stat().st_ino == info.st_ino
        verified = await service.verify(current)
        await _commit(service, verified)
        await _commit(service, await service.ledger(ledger.id))
        record = await pool.fetchrow("SELECT * FROM dataset_revisions")
        final = root / record["revision_path"]
        assert (final / "payload/file").stat().st_ino == info.st_ino
        assert (final / "payload/file").read_bytes() == _DATA
        assert {str(path.relative_to(final)) for path in final.rglob("*")} == {
            "manifest.json",
            "metadata.json",
            "COMMITTED",
            "payload",
            "payload/file",
        }
        assert abandoned.read_bytes() == b"unpublished candidate"
        assert (await store.ingest_session(ledger.id)).state is IngestState.COMMITTED
        assert await pool.fetchval("SELECT count(*) FROM dataset_revisions") == 1
        assert (
            await pool.fetchval(
                "SELECT count(*) FROM audit_events WHERE kind = 'revision.committed'"
            )
            == 1
        )
        assert await pool.fetchval("SELECT count(*) FROM outbox_events") == 1
    finally:
        await pool.close()


@pytest.mark.parametrize("corrupt", [False, True])
def test_competing_completions_cannot_regress_a_complete_database_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, corrupt: bool
) -> None:
    """A real PostgreSQL loser cannot reset or replace a completed filesystem winner."""
    monkeypatch.setattr(ingest_module, "PART_BYTES", 4)
    with PostgresContainer("postgres:16") as postgres:
        _migrate(postgres.get_connection_url(driver="asyncpg"))
        asyncio.run(
            _completion_race(
                postgres.get_connection_url(driver=None), tmp_path, monkeypatch, corrupt
            )
        )


async def _completion_race(
    dsn: str, root: Path, monkeypatch: pytest.MonkeyPatch, corrupt: bool
) -> None:
    pool = await asyncpg.create_pool(dsn)
    try:
        store = PostgresHierarchyStore(pool, clock=FakeClock(_NOW))
        hierarchy = await seed_hierarchy(store)
        dataset = await store.datasets.get(hierarchy.datasets["run-0001"], Visibility.ALL)
        raw = PosixRawStore(root)
        raw.initialize()
        service = IngestService(raw, store, clock=FakeClock(_NOW))
        data = b"abcdefgh"
        ledger = await service.create(
            dataset,
            files=(ManifestEntry("payload/file", len(data), hashlib.sha256(data).hexdigest()),),
            created_by="user:alice",
            claim=IdempotencyClaim("user:alice", "upload", "a" * 64),
        )
        initial = b"xxxxxxxx" if corrupt else data
        for part in (1, 2):
            ledger = await service.ledger(ledger.id)
            await service.receive_part(
                ledger,
                ledger.files[0],
                part,
                [initial[(part - 1) * 4 : part * 4]],
                content_length=4,
            )
        ledger = await service.ledger(ledger.id)
        waiting, resume = asyncio.Event(), asyncio.Event()
        execute = asyncpg.Connection.execute

        async def delayed_update(
            connection: asyncpg.Connection, query: str, *args: object, timeout: float | None = None
        ) -> str:
            if "UPDATE ingest_files SET state" in query and not waiting.is_set():
                waiting.set()
                await asyncio.wait_for(resume.wait(), 10)
            return await execute(connection, query, *args, timeout=timeout)

        with monkeypatch.context() as patch:
            patch.setattr(asyncpg.Connection, "execute", delayed_update)
            loser = asyncio.create_task(service.complete_file(ledger, ledger.files[0]))
            try:
                await asyncio.wait_for(waiting.wait(), 10)
                if corrupt:
                    for part in (1, 2):
                        current = await service.ledger(ledger.id)
                        await service.receive_part(
                            current,
                            current.files[0],
                            part,
                            [data[(part - 1) * 4 : part * 4]],
                            content_length=4,
                        )
                current = await service.ledger(ledger.id)
                winner = await service.complete_file(current, current.files[0])
                installed = root / ".staging" / ledger.id.hex / "envelope/payload/file"
                inode = installed.stat().st_ino
            finally:
                resume.set()
            assert await asyncio.wait_for(loser, 10) == winner
        current = await service.ledger(ledger.id)
        assert current.files[0] == winner
        assert winner.state is FileState.COMPLETE
        assert winner.completed_parts == frozenset({1, 2})
        await _commit(service, await service.verify(current))
        record = await pool.fetchrow("SELECT * FROM dataset_revisions")
        final = root / record["revision_path"]
        assert (final / "payload/file").read_bytes() == data
        assert (final / "payload/file").stat().st_ino == inode
        assert not installed.exists()
        assert (await service.ledger(ledger.id)).files[0] == winner
    finally:
        await pool.close()
