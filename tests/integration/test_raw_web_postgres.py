"""Real PostgreSQL and POSIX evidence for delegated Raw uploads and catalog mappings."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import asyncpg
import pytest
from fastapi.testclient import TestClient
from testcontainers.postgres import PostgresContainer

from huron.applications.api.app import create_app
from huron.applications.api.settings import ApiSettings, ClassificationValue
from huron.core.metastore.raw_web import PostgresRawWebStore
from tests.contract.test_hierarchy_store import _migrate
from tests.raw_web_client import SECRET, RawWebClient

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from huron.core.catalog.external import ExternalDataset


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    """Migrate an isolated actual PostgreSQL 16 database for bridge verification."""
    with PostgresContainer("postgres:16") as postgres:
        _migrate(postgres.get_connection_url(driver="asyncpg"))
        yield postgres.get_connection_url(driver=None)


def settings(database_url: str, root: Path) -> ApiSettings:
    """Configure credential-only bridge access with real PostgreSQL persistence."""
    return ApiSettings(
        env="development",
        auth_mode="credentials",
        data_root=str(root),
        database_url=database_url,
        raw_bridge_secret=SECRET,
        classification_vocabulary=[ClassificationValue(code="open", order=0, discoverable=True)],
        completion_reserve_bytes=0,
    )


@pytest.mark.integration
def test_delegated_publication_and_registration_survive_process_restarts(
    database_url: str,
    tmp_path: Path,
) -> None:
    """Real persisted state resumes transfers and keeps one immutable revision across restarts."""
    configuration = settings(database_url, tmp_path)
    with TestClient(create_app(settings=configuration)) as client:
        raw = RawWebClient(client)
        raw.target = {**raw.target, "name": "restart-dataset"}
        session = raw.create(key="restart-upload")
        path = (
            f"/api/raw-web/uploads/{session['id']}/files/{session['files'][0]['file_id']}/parts/1"
        )
        assert raw.request("PUT", path, data=b"real uploaded bytes").status_code == 200
    with TestClient(create_app(settings=configuration)) as client:
        raw = RawWebClient(client)
        raw.target = session["target"]
        prefix = f"/api/raw-web/uploads/{session['id']}"
        resumed = raw.request("GET", prefix)
        assert resumed.json()["files"][0]["state"] == "COMPLETE"
        verified = raw.request("POST", prefix + "/verify")
        body = {
            "manifest_sha256": session["manifest_sha256"],
            "metadata": {"title": "Persisted observation", "creators": ["Scientist"]},
        }
        headers = {"idempotency-key": "restart-commit", "if-match": verified.headers["etag"]}
        committed = raw.request("POST", prefix + "/commit", body=body, headers=headers)
        assert committed.status_code == 201, committed.text
        receipt = committed.json()
        assert receipt["registration"]["state"] == "pending"
    original = {
        str(path.relative_to(tmp_path)): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    with TestClient(create_app(settings=configuration)) as client:
        raw = RawWebClient(client)
        raw.target = session["target"]
        replay = raw.request("POST", prefix + "/commit", body=body, headers=headers)
        assert replay.json() == receipt
        acknowledged = raw.request(
            "POST", prefix + "/registration", body={"revision_id": receipt["id"]}
        )
        assert acknowledged.status_code == 200, acknowledged.text
    with TestClient(create_app(settings=configuration)) as client:
        raw = RawWebClient(client)
        raw.target = session["target"]
        assert raw.request("GET", prefix).json()["registration"]["state"] == "registered"
        page = raw.request("GET", f"/api/raw-web/datasets/{session['dataset_id']}/revisions")
        assert page.json()["revisions"][0]["id"] == receipt["id"]
        downloaded = raw.request(
            "GET", f"/api/raw-web/revisions/{receipt['id']}/files/payload/science%20data.csv"
        )
        assert downloaded.content == b"real uploaded bytes"
    assert {
        str(path.relative_to(tmp_path)): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    } == original
    asyncio.run(assert_publication(database_url, session["dataset_id"], receipt["id"]))


async def assert_publication(dsn: str, dataset_id: str, revision_id: str) -> None:
    """Assert one durable publication plus immutable mapping and acknowledgement constraints."""
    connection = await asyncpg.connect(dsn)
    try:
        assert (
            await connection.fetchval(
                "SELECT count(*) FROM dataset_revisions WHERE dataset_id=$1", dataset_id
            )
            == 1
        )
        assert (
            await connection.fetchval(
                "SELECT count(*) FROM outbox_events WHERE subject_id=$1", revision_id
            )
            == 1
        )
        assert (
            await connection.fetchval(
                "SELECT count(*) FROM raw_catalog_publications WHERE revision_id=$1", revision_id
            )
            == 1
        )
        with pytest.raises(asyncpg.CheckViolationError):
            await connection.execute(
                "UPDATE raw_external_datasets SET name='other' WHERE dataset_id=$1", dataset_id
            )
        with pytest.raises(asyncpg.CheckViolationError):
            await connection.execute(
                "DELETE FROM raw_catalog_publications WHERE revision_id=$1", revision_id
            )
    finally:
        await connection.close()


@pytest.mark.contract
def test_expired_partial_provisioning_recovers_exact_identity(
    database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A crash before mapping insertion still resumes after normal retry receipts expire."""
    configuration = settings(database_url, tmp_path)
    original = PostgresRawWebStore.remember

    async def fail_mapping(self: PostgresRawWebStore, mapping: ExternalDataset) -> ExternalDataset:
        raise OSError("injected crash before target mapping")

    monkeypatch.setattr(PostgresRawWebStore, "remember", fail_mapping)
    with TestClient(create_app(settings=configuration), raise_server_exceptions=False) as client:
        raw = RawWebClient(client)
        raw.target = {
            **raw.target,
            "name": "interrupted-identity",
            "namespace": ["bounded-namespace-" + "x" * 230] * 20,
        }
        body = {
            "title": "Interrupted",
            "files": [
                {
                    "path": "payload/empty",
                    "size": 0,
                    "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                }
            ],
        }
        failed = raw.request(
            "POST", "/api/raw-web/uploads", body=body, headers={"idempotency-key": "partial-upload"}
        )
        assert failed.status_code == 500
        counts = asyncio.run(expire_creation_receipts(database_url))
        monkeypatch.setattr(PostgresRawWebStore, "remember", original)
        resumed = raw.request(
            "POST", "/api/raw-web/uploads", body=body, headers={"idempotency-key": "partial-upload"}
        )
        assert resumed.status_code == 201, resumed.text
        assert asyncio.run(hierarchy_counts(database_url)) == counts
        assert resumed.json()["target"] == raw.target


async def hierarchy_counts(dsn: str) -> tuple[int, int, int]:
    """Count the real hierarchy to detect duplicate identities during recovery."""
    connection = await asyncpg.connect(dsn)
    try:
        return tuple(
            [
                await connection.fetchval(f"SELECT count(*) FROM {table}")
                for table in ("organizations", "projects", "datasets")
            ]
        )
    finally:
        await connection.close()


async def expire_creation_receipts(dsn: str) -> tuple[int, int, int]:
    """Expire the normal infrastructure creation receipts while keeping created identities."""
    connection = await asyncpg.connect(dsn)
    try:
        await connection.execute(
            "UPDATE idempotency_records SET expires_at=now()-interval '1 day' "
            "WHERE principal='huron-raw-web-provisioner'"
        )
    finally:
        await connection.close()
    return await hierarchy_counts(dsn)
