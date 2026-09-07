"""Commit's documents: the metadata a submission composes into, and the dataset's revision index.

Drives the FastAPI app through a TestClient over an in-memory
``HierarchyStore`` with dev-header auth, asserting the three documents a
commit writes agree with each other and with the stored row, that a
schema-rejected submission is refused before any state moves, that the
composed metadata carries the project's classification and the hierarchy's
own references, and that the dataset's revision index grows by one entry
per commit.
"""

from __future__ import annotations

import stat
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from huron.pkg.catalog.documents import (
    CommitRecord,
    MetadataDocument,
    RevisionIndex,
    decode_manifest,
)
from huron.pkg.rawstore import PosixRawStore
from huron.service.api.app import create_app
from huron.service.api.settings import ApiSettings, ClassificationValue
from tests.ingest_client import IngestClient, manifest_file
from tests.unit.support import memory_stores

if TYPE_CHECKING:
    from collections.abc import Iterator

    from huron.service.api.runtime import ApiStores

pytestmark = pytest.mark.unit


def _headers(subject: str, *, key: str | None = None) -> dict[str, str]:
    """Dev-header credentials for ``subject``, paired with an idempotency key."""
    return {"X-Huron-Subject": subject, "Idempotency-Key": key if key is not None else str(uuid4())}


@pytest.fixture
def stores() -> ApiStores:
    """A fresh in-memory store bundle, held so a test can seed its hierarchy store directly."""
    return memory_stores()


@pytest.fixture
def client(tmp_path: Path, stores: ApiStores) -> Iterator[TestClient]:
    """A dev-header TestClient over a freshly wired in-memory repository, ``root`` bootstrapped."""
    settings = ApiSettings(
        env="development",
        auth_mode="dev-headers",
        data_root=str(tmp_path / "data"),
        database_url="postgresql://unused",
        classification_vocabulary=[ClassificationValue(code="open", order=0, discoverable=True)],
        bootstrap_platform_owner="root",
    )
    with TestClient(
        create_app(settings=settings, stores=stores), raise_server_exceptions=False
    ) as client:
        yield client


def _committed(
    ingest: IngestClient, dataset_id: str, path: str, data: bytes, title: str
) -> dict[str, object]:
    """Create, upload, verify and commit one single-file revision, returning its view."""
    session = ingest.create(dataset_id, [manifest_file(path, data)]).json()
    ingest.put_part(session["files"][0]["file_id"], 1, data)
    verified = ingest.verify(session["id"]).json()
    response = ingest.commit(session["id"], verified["etag"], {"title": title, "creators": ["bob"]})
    assert response.status_code == 201, response.text
    return response.json()


def test_commit_writes_the_three_documents_and_they_agree(
    client: TestClient, stores: ApiStores
) -> None:
    """The manifest, metadata and marker a commit writes agree with each other and the stored row.

    Every document is read back through its own decoder rather than by
    string inspection, so a change to the canonical byte form would still
    leave this test meaningful.
    """
    ingest = IngestClient(client)
    _, dataset_id = ingest.developer_dataset()

    view = _committed(ingest, dataset_id, "payload/a.bin", b"hello world", "Run 1")

    record = stores.hierarchy._revisions[UUID(view["id"])]
    revision_path = Path(record.revision_path)

    manifest = decode_manifest((revision_path / "manifest.json").read_bytes())
    assert manifest.sha256 == view["manifest_sha256"]

    metadata_doc = MetadataDocument.decode((revision_path / "metadata.json").read_bytes())
    assert metadata_doc.sha256 == view["metadata_sha256"]
    assert metadata_doc.committed_by == "bob"
    document = metadata_doc.as_dict()
    assert set(document) >= {
        "schema",
        "organization",
        "project",
        "dataset",
        "revision_number",
        "title",
        "creators",
        "committed_by",
        "committed_at",
        "data_classification",
        "manifest_sha256",
    }

    marker = CommitRecord.decode((revision_path / "COMMITTED").read_bytes())
    assert marker.revision_record(revision_path=str(revision_path)) == record

    for name in ("manifest.json", "metadata.json", "COMMITTED"):
        assert stat.S_IMODE((revision_path / name).stat().st_mode) == 0o444


def test_commit_refuses_a_metadata_submission_the_schema_rejects_before_any_edge(
    client: TestClient,
) -> None:
    """A submission the registered schema rejects is refused before the session moves at all."""
    ingest = IngestClient(client)
    _, dataset_id = ingest.developer_dataset()
    data = b"hello"
    session = ingest.create(dataset_id, [manifest_file("payload/a.bin", data)]).json()
    ingest.put_part(session["files"][0]["file_id"], 1, data)
    verified = ingest.verify(session["id"]).json()

    empty_creators = ingest.commit(
        session["id"], verified["etag"], {"title": "Run", "creators": []}
    )

    assert empty_creators.status_code == 409
    body = empty_creators.json()
    assert body["code"] == "CONTRACT_MISMATCH"
    assert body["context"]["path"] == "$.creators"
    unchanged = ingest.get(session["id"]).json()
    assert unchanged["state"] == "VERIFYING"
    assert unchanged["etag"] == verified["etag"]

    forbidden_member = client.post(
        f"/api/v1/ingest-sessions/{session['id']}/commit",
        json={
            "manifest_sha256": session["manifest_sha256"],
            "metadata": {"title": "Run", "creators": ["bob"], "committed_by": "eve"},
        },
        headers={**_headers("bob"), "If-Match": f'"{verified["etag"]}"'},
    )
    assert forbidden_member.status_code == 422
    assert forbidden_member.json()["code"] == "REQUEST_INVALID"


def test_metadata_carries_the_project_s_classification_and_the_hierarchy_refs(
    client: TestClient, stores: ApiStores
) -> None:
    """The composed metadata document sources its classification and refs from the hierarchy."""
    ingest = IngestClient(client)
    project_id, dataset_id = ingest.developer_dataset()
    dataset = client.get(f"/api/v1/datasets/{dataset_id}", headers=_headers("bob")).json()
    project = client.get(f"/api/v1/projects/{project_id}", headers=_headers("bob")).json()
    organization = client.get(
        f"/api/v1/organizations/{project['organization_id']}", headers=_headers("bob")
    ).json()

    view = _committed(ingest, dataset_id, "payload/a.bin", b"hello", "Run")

    record = stores.hierarchy._revisions[UUID(view["id"])]
    doc = MetadataDocument.decode((Path(record.revision_path) / "metadata.json").read_bytes())
    document = doc.as_dict()
    assert document["data_classification"] == project["data_classification"]
    assert document["organization"] == {"id": organization["id"], "slug": organization["slug"]}
    assert document["project"] == {"id": project["id"], "slug": project["slug"]}
    assert document["dataset"] == {"id": dataset["id"], "slug": dataset["slug"]}


def test_a_commit_writes_the_index_and_a_second_commit_extends_it(
    client: TestClient, stores: ApiStores
) -> None:
    """A commit writes the dataset's revision index, and a second commit extends it."""
    ingest = IngestClient(client)
    _, dataset_id = ingest.developer_dataset()

    first_view = _committed(ingest, dataset_id, "payload/a.bin", b"first", "R1")
    first_record = stores.hierarchy._revisions[UUID(first_view["id"])]
    index_path = Path(first_record.revision_path).parent / "INDEX.json"

    index_after_one = RevisionIndex.decode(index_path.read_bytes())
    assert [entry.number for entry in index_after_one.entries] == [1]
    assert index_after_one.entries[0].directory == Path(first_record.revision_path).name
    assert index_after_one.entries[0].manifest_sha256 == first_record.manifest_sha256

    second_view = _committed(ingest, dataset_id, "payload/b.bin", b"second", "R2")
    second_record = stores.hierarchy._revisions[UUID(second_view["id"])]

    index_after_two = RevisionIndex.decode(index_path.read_bytes())
    assert [entry.number for entry in index_after_two.entries] == [1, 2]
    assert index_after_two.entries[1].directory == Path(second_record.revision_path).name
    assert index_after_two.entries[1].manifest_sha256 == second_record.manifest_sha256


def test_a_failed_index_update_does_not_fail_the_commit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A commit still returns its revision even when the best-effort index write fails."""
    ingest = IngestClient(client)
    _, dataset_id = ingest.developer_dataset()

    real_replace = PosixRawStore.atomic_replace

    def _broken_replace(self: PosixRawStore, path: Path, payload: bytes, **kwargs: object) -> None:
        if Path(path).name == "INDEX.json":
            raise OSError("index write injected failure")
        real_replace(self, path, payload, **kwargs)

    monkeypatch.setattr(PosixRawStore, "atomic_replace", _broken_replace)

    view = _committed(ingest, dataset_id, "payload/a.bin", b"hello", "Run")

    assert view["number"] == 1
