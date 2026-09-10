"""HTTP ingestion resumes across application restarts using real PostgreSQL and POSIX storage."""

from __future__ import annotations

import asyncio
import io
from pathlib import Path

import asyncpg
import pytest
from fastapi.testclient import TestClient
from testcontainers.postgres import PostgresContainer

from huron.applications.api.app import create_app
from huron.applications.api.settings import ApiSettings, ClassificationValue
from tests.contract.test_hierarchy_store import _migrate
from tests.ingest_client import IngestClient, manifest_file

pytestmark = pytest.mark.integration


def test_verified_upload_and_commit_replay_survive_application_restarts(tmp_path: Path) -> None:
    """Real adapters retain completion, reject a foreign writer, and replay one revision."""
    with PostgresContainer("postgres:16") as postgres:
        _migrate(postgres.get_connection_url(driver="asyncpg"))
        settings = ApiSettings(
            env="development",
            auth_mode="dev-headers",
            data_root=str(tmp_path / "data"),
            database_url=postgres.get_connection_url(driver=None),
            classification_vocabulary=[
                ClassificationValue(code="open", order=0, discoverable=True)
            ],
            bootstrap_platform_owner="root",
        )
        _exercise_restarts(settings)
        asyncio.run(_assert_one_publication(settings.database_url))


def _exercise_restarts(settings: ApiSettings) -> None:
    sources = {"payload/nested/file.bin": b"verified evidence" * 65536, "payload/empty": b""}
    with TestClient(create_app(settings=settings)) as client:
        ingest = IngestClient(client)
        _, dataset = ingest.developer_dataset()
        ingest.reader("eve")
        created = ingest.create(
            dataset, [manifest_file(path, data) for path, data in sources.items()]
        )
        assert created.status_code == 201, created.text
        plan = created.json()
        foreign = IngestClient(client, subject="eve")
        forbidden = foreign.put_part(plan["files"][0]["file_id"], 1, b"unowned")
        assert forbidden.status_code == 403, forbidden.text
        ingest.upload(plan, lambda path: io.BytesIO(sources[path]))
        completed = ingest.get(plan["id"]).json()
        assert all(file["state"] == "COMPLETE" for file in completed["files"])

    metadata = {"title": "Verified restart", "creators": ["bob"]}
    with TestClient(create_app(settings=settings)) as client:
        ingest = IngestClient(client)
        resumed = ingest.get(plan["id"])
        assert resumed.status_code == 200, resumed.text
        assert resumed.json()["files"] == completed["files"]
        verified = ingest.verify(plan["id"])
        assert verified.status_code == 200, verified.text
        etag = verified.json()["etag"]
        committed = ingest.commit(plan["id"], etag, metadata, key="restart-commit")
        assert committed.status_code == 201, committed.text
        revision = committed.json()

    marker = next(Path(settings.data_root).rglob("COMMITTED"))
    final = marker.parent
    original = {
        str(path.relative_to(final)): path.read_bytes()
        for path in final.rglob("*")
        if path.is_file()
    }
    with TestClient(create_app(settings=settings)) as client:
        ingest = IngestClient(client)
        replay = ingest.commit(plan["id"], etag, metadata, key="restart-commit")
        assert replay.status_code == 201, replay.text
        assert replay.json() == revision
        changed = ingest.commit(
            plan["id"], etag, {**metadata, "title": "Changed"}, key="different-commit"
        )
        assert changed.status_code == 409, changed.text
        for path, data in sources.items():
            downloaded = ingest.download(revision["id"], path)
            assert downloaded.status_code == 200, downloaded.text
            assert downloaded.content == data
    assert {
        str(path.relative_to(final)): path.read_bytes()
        for path in final.rglob("*")
        if path.is_file()
    } == original
    assert set(original) == {"manifest.json", "metadata.json", "COMMITTED", *sources}


async def _assert_one_publication(dsn: str) -> None:
    connection = await asyncpg.connect(dsn)
    try:
        assert await connection.fetchval("SELECT count(*) FROM dataset_revisions") == 1
        assert await connection.fetchval("SELECT count(*) FROM ingest_commit_intents") == 1
        assert (
            await connection.fetchval(
                "SELECT count(*) FROM ingest_sessions WHERE state = 'COMMITTED'"
            )
            == 1
        )
        assert (
            await connection.fetchval(
                "SELECT count(*) FROM audit_events WHERE kind = 'revision.committed'"
            )
            == 1
        )
        assert await connection.fetchval("SELECT count(*) FROM outbox_events") == 1
    finally:
        await connection.close()
