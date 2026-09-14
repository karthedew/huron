"""The Books script drives the real upload routes with bounded streams and retry identities."""

from __future__ import annotations

from uuid import UUID, uuid4

import httpx
import pytest

import huron.pkg.catalog.ingest as ingest_module
from huron.pkg.catalog.errors import EmptyRevision
from scripts.main import upload_books
from tests.ingest_client import IngestClient

pytestmark = pytest.mark.unit


@pytest.fixture
def books_project(client, monkeypatch):
    """Authorize the script's HTTP client and use small parts to exercise real multipart I/O."""
    ingest = IngestClient(client)
    project_id, _ = ingest.developer_dataset()
    client.headers["X-Huron-Subject"] = ingest.subject
    monkeypatch.setattr(ingest_module, "PART_BYTES", 8)
    return UUID(project_id), ingest


def test_books_upload_commits_exact_nested_files_and_replays(client, tmp_path, books_project):
    """Nested, empty and multipart files are readable; retry returns the same revision."""
    project_id, ingest = books_project
    source = tmp_path / "Books"
    (source / "Science").mkdir(parents=True)
    expected = {
        "empty.txt": b"",
        "note.txt": b"hello",
        "Science/Book with spaces.pdf": bytes(range(37)),
    }
    for path, payload in expected.items():
        (source / path).write_bytes(payload)
    upload_id = uuid4()

    receipt = upload_books(client, source, project_id, "Karl", upload_id).json()
    replay = upload_books(client, source, project_id, "Karl", upload_id).json()

    assert receipt == replay
    assert receipt["file_count"] == len(expected)
    assert receipt["total_bytes"] == sum(map(len, expected.values()))
    assert receipt["committed_by"] == ingest.subject
    for path, payload in expected.items():
        response = ingest.download(receipt["id"], f"payload/{path}")
        assert response.status_code == 200
        assert response.content == payload
    different = upload_books(client, source, project_id, "Karl", uuid4()).json()
    assert different["dataset_id"] != receipt["dataset_id"]


@pytest.mark.parametrize("lost_response", ["part", "commit"])
def test_books_upload_resumes_after_lost_acknowledgement(
    client, tmp_path, books_project, monkeypatch, lost_response
):
    """Lost part or commit responses resume without re-uploading acknowledged parts."""
    project_id, ingest = books_project
    source = tmp_path / "Books"
    source.mkdir()
    payload = b"A book longer than a part"
    (source / "book.pdf").write_bytes(payload)
    upload_id = uuid4()
    original_send = client.send
    interrupted = False
    uploaded_paths = []

    def send(request, **kwargs):
        nonlocal interrupted
        response = original_send(request, **kwargs)
        is_part = request.method == "PUT"
        if is_part:
            uploaded_paths.append(request.url.path)
        target = is_part if lost_response == "part" else request.url.path.endswith("/commit")
        if target and not interrupted:
            interrupted = True
            response.raise_for_status()
            raise httpx.ReadError("Lost acknowledgement", request=request)
        return response

    monkeypatch.setattr(client, "send", send)
    with pytest.raises(httpx.ReadError, match="Lost acknowledgement"):
        upload_books(client, source, project_id, "Karl", upload_id)

    receipt = upload_books(client, source, project_id, "Karl", upload_id).json()

    assert len(uploaded_paths) == len(set(uploaded_paths)) == 4
    assert ingest.download(receipt["id"], "payload/book.pdf").content == payload


@pytest.mark.parametrize("invalid_source", ["missing", "empty", "symlink"])
def test_invalid_books_source_does_not_create_a_dataset(
    client, tmp_path, monkeypatch, invalid_source
):
    """Missing, empty and linked source trees fail before any remote mutation."""
    source = tmp_path / "Books"
    if invalid_source != "missing":
        source.mkdir()
    if invalid_source == "symlink":
        (tmp_path / "outside.pdf").write_bytes(b"outside")
        (source / "linked.pdf").symlink_to(tmp_path / "outside.pdf")

    def refuse_request(*args, **kwargs):
        pytest.fail("Invalid local source must not create a remote dataset")

    monkeypatch.setattr(client, "post", refuse_request)
    with pytest.raises((ValueError, EmptyRevision)):
        upload_books(client, source, uuid4(), "Karl", uuid4())
