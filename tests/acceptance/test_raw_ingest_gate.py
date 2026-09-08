"""A 9 GiB file ingests through an interrupted, resumed multipart upload and downloads whole."""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

import httpx
import pytest
import uvicorn

from huron.applications.api.app import create_app
from huron.applications.api.settings import ApiSettings, ClassificationValue
from huron.pkg.catalog import PART_BYTES
from tests.ingest_client import IngestClient, declared_file, sparse_file, zeros_sha256
from tests.unit.support import memory_stores

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path
    from typing import BinaryIO

    from huron.applications.api.runtime import ApiStores

pytestmark = pytest.mark.acceptance

_FILE_SIZE = 9 * 1024**3
_STOP_AFTER_PART = 50
_DOWNLOAD_CHUNK_BYTES = 64 * 1024**2
_SERVER_START_TIMEOUT_S = 20.0
_SERVER_STOP_TIMEOUT_S = 10.0
_REQUEST_TIMEOUT_S = 300.0


@pytest.fixture
def stores() -> ApiStores:
    """A fresh in-memory store bundle backing the session's hierarchy."""
    return memory_stores()


@pytest.fixture
def _loopback_base_url(tmp_path: Path, stores: ApiStores) -> Iterator[str]:
    """Serve the wired app under ``uvicorn`` on a background thread, bound to a free port."""
    settings = ApiSettings(
        env="development",
        auth_mode="dev-headers",
        data_root=str(tmp_path / "data"),
        database_url="postgresql://unused",
        classification_vocabulary=[ClassificationValue(code="open", order=0, discoverable=True)],
        bootstrap_platform_owner="root",
    )
    app = create_app(settings=settings, stores=stores)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error"))
    failures: list[Exception] = []

    def _run() -> None:
        try:
            server.run()
        except Exception as exc:
            failures.append(exc)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    deadline = time.monotonic() + _SERVER_START_TIMEOUT_S
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.05)
    if failures:
        raise RuntimeError("the loopback server failed to start") from failures[0]
    assert server.started, "the loopback server did not start"
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=_SERVER_STOP_TIMEOUT_S)
        assert not thread.is_alive(), "the loopback server did not stop"


@pytest.fixture
def client(_loopback_base_url: str) -> Iterator[httpx.Client]:
    """An ``httpx.Client`` bound to the loopback server, streaming every request and response."""
    with httpx.Client(base_url=_loopback_base_url, timeout=_REQUEST_TIMEOUT_S) as client:
        yield client


def test_a_nine_gib_file_round_trips_byte_identically_after_an_interrupted_upload_resumes(
    client: httpx.Client, tmp_path: Path
) -> None:
    """A 9 GiB upload survives one client stopping mid-transfer and a second one finishing it."""
    first = IngestClient(client)
    _, dataset_id = first.developer_dataset()
    source_path = sparse_file(tmp_path / "nine-gib.bin", _FILE_SIZE)
    digest = zeros_sha256(_FILE_SIZE)

    created = first.create(dataset_id, [declared_file("payload/nine-gib.bin", _FILE_SIZE, digest)])
    assert created.status_code == 201, created.text
    plan = created.json()
    entry = plan["files"][0]
    assert plan["part_bytes"] == PART_BYTES
    assert entry["part_count"] == 144
    assert entry["action"] == "upload"

    def _reopen(_path: str) -> BinaryIO:
        return source_path.open("rb")

    issued_first = first.upload(plan, _reopen, last_part=_STOP_AFTER_PART)
    assert issued_first == _STOP_AFTER_PART
    assert first.put_count == _STOP_AFTER_PART

    second = IngestClient(client)
    view = second.get(plan["id"]).json()

    issued_second = second.upload(view, _reopen)
    assert issued_second == entry["part_count"] - _STOP_AFTER_PART
    assert first.put_count + second.put_count == entry["part_count"]

    resumed = second.get(plan["id"]).json()
    assert sorted(resumed["files"][0]["completed_parts"]) == list(range(1, entry["part_count"] + 1))

    completion = second.complete(entry["file_id"])
    assert completion.status_code == 200, completion.text
    assert completion.json()["state"] == "COMPLETE"

    verified = second.verify(plan["id"])
    assert verified.status_code == 200, verified.text
    verified_body = verified.json()

    committed = second.commit(
        verified_body["id"],
        verified_body["etag"],
        {"title": "Nine GiB", "creators": [second.subject]},
    )
    assert committed.status_code == 201, committed.text
    revision_id = committed.json()["id"]

    downloaded_digest, total, content_length = second.download_sha256(
        revision_id, "payload/nine-gib.bin", chunk_size=_DOWNLOAD_CHUNK_BYTES
    )
    assert content_length == _FILE_SIZE
    assert total == _FILE_SIZE
    assert downloaded_digest == digest
