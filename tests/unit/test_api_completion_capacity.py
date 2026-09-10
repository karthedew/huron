"""Application completion capacity settings reach the real filesystem adapter."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from huron.applications.api.app import create_app
from huron.applications.api.settings import ApiSettings, ClassificationValue
from tests.ingest_client import IngestClient, manifest_file
from tests.unit.support import memory_stores

pytestmark = pytest.mark.unit


def test_configured_capacity_refusal_preserves_upload_for_retry(tmp_path: Path) -> None:
    """An oversized reserve refuses completion, and a restarted configured app can retry."""
    filesystem = os.statvfs(tmp_path)
    settings = ApiSettings(
        env="development",
        auth_mode="dev-headers",
        data_root=str(tmp_path / "data"),
        database_url="postgresql://unused",
        classification_vocabulary=[ClassificationValue(code="open", order=0, discoverable=True)],
        bootstrap_platform_owner="root",
        completion_max_concurrent=2,
        completion_reserve_bytes=filesystem.f_blocks * filesystem.f_frsize + 1,
    )
    stores = memory_stores()
    with TestClient(
        create_app(settings=settings, stores=stores), raise_server_exceptions=False
    ) as client:
        ingest = IngestClient(client)
        _, dataset_id = ingest.developer_dataset()
        created = ingest.create(dataset_id, [manifest_file("payload/file", b"complete")])
        assert created.status_code == 201, created.text
        plan = created.json()
        file_id = plan["files"][0]["file_id"]
        failed = ingest.put_part(file_id, 1, b"complete")
        assert failed.status_code == 500, failed.text
        current = ingest.get(plan["id"]).json()
        assert current["files"][0]["state"] == "PENDING"
    session = Path(settings.data_root) / ".staging" / UUID(plan["id"]).hex
    assert (session / "upload" / file_id).read_bytes() == b"complete"
    assert list((session / "completion").iterdir()) == []
    assert list((session / "envelope/payload").iterdir()) == []
    retry_settings = settings.model_copy(update={"completion_reserve_bytes": 0})
    with TestClient(create_app(settings=retry_settings, stores=stores)) as client:
        ingest = IngestClient(client)
        retried = ingest.put_part(file_id, 1, b"complete")
        assert retried.status_code == 200, retried.text
        assert ingest.get(plan["id"]).json()["files"][0]["state"] == "COMPLETE"
    assert (session / "envelope/payload/file").read_bytes() == b"complete"
