"""Committing a revision's documents, and reading a committed revision back.

Drives the FastAPI app through a TestClient over an in-memory
``HierarchyStore`` with dev-header auth. The commit half asserts the three
documents a commit writes agree with each other and with the stored row,
that a schema-rejected submission is refused before any state moves, that
the composed metadata carries the project's classification and the
hierarchy's own references, and that the dataset's revision index grows by
one entry per commit. The read half asserts a committed revision, its
manifest and its payload files download correctly under a per-request
``data.read@raw`` check, honoring ``Range`` and refusing a path the
manifest does not list before any storage is touched.
"""

from __future__ import annotations

import hashlib
import stat
import unicodedata
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest

from huron.pkg.catalog.documents import (
    CommitRecord,
    MetadataDocument,
    RevisionIndex,
    decode_manifest,
)
from huron.pkg.rawstore import PosixRawStore
from tests.ingest_client import IngestClient, dev_headers, manifest_file

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

    from huron.service.api.runtime import ApiStores

pytestmark = pytest.mark.unit

_ADMIN = "root"


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
        headers={**dev_headers("bob"), "If-Match": f'"{verified["etag"]}"'},
    )
    assert forbidden_member.status_code == 422
    assert forbidden_member.json()["code"] == "REQUEST_INVALID"


def test_metadata_carries_the_project_s_classification_and_the_hierarchy_refs(
    client: TestClient, stores: ApiStores
) -> None:
    """The composed metadata document sources its classification and refs from the hierarchy."""
    ingest = IngestClient(client)
    project_id, dataset_id = ingest.developer_dataset()
    dataset = client.get(f"/api/v1/datasets/{dataset_id}", headers=dev_headers("bob")).json()
    project = client.get(f"/api/v1/projects/{project_id}", headers=dev_headers("bob")).json()
    organization = client.get(
        f"/api/v1/organizations/{project['organization_id']}", headers=dev_headers("bob")
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


def test_get_revision_returns_the_view_and_hides_an_invisible_one(client: TestClient) -> None:
    """A committed revision's view carries its nine members and never its storage location.

    A sibling project's revision is 404 to an outsider who holds no
    binding reaching it, and an unknown id is 404 too.
    """
    ingest = IngestClient(client)
    _, revision_id = ingest.committed([("payload/a.bin", b"hello")])

    response = client.get(f"/api/v1/revisions/{revision_id}", headers=dev_headers("bob"))
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {
        "id",
        "dataset_id",
        "number",
        "manifest_sha256",
        "metadata_sha256",
        "file_count",
        "total_bytes",
        "committed_by",
        "committed_at",
    }

    owner = IngestClient(client, subject="alice")
    _, sibling_revision_id = owner.committed(
        [("payload/a.bin", b"secret")], organization_slug="vault", project_slug="sealed"
    )
    hidden = client.get(f"/api/v1/revisions/{sibling_revision_id}", headers=dev_headers("bob"))
    assert hidden.status_code == 404
    assert hidden.json()["code"] == "NOT_FOUND"

    unknown = client.get(f"/api/v1/revisions/{uuid4()}", headers=dev_headers("bob"))
    assert unknown.status_code == 404


def test_manifest_download_streams_the_stored_bytes_with_the_identity_as_etag(
    client: TestClient, stores: ApiStores
) -> None:
    """The manifest route serves the stored bytes verbatim, keyed by their own content identity."""
    ingest = IngestClient(client)
    _, revision_id = ingest.committed([("payload/a.bin", b"hello world")])
    record = stores.hierarchy._revisions[UUID(revision_id)]
    stored = (Path(record.revision_path) / "manifest.json").read_bytes()

    response = client.get(f"/api/v1/revisions/{revision_id}/manifest", headers=dev_headers("bob"))

    assert response.status_code == 200, response.text
    assert response.content == stored
    assert hashlib.sha256(response.content).hexdigest() == record.manifest_sha256
    assert response.headers["etag"] == f'"{record.manifest_sha256}"'
    assert response.headers["content-type"] == "application/json"


def test_file_download_round_trips_nfc_zero_byte_and_eight_level_files_byte_identically(
    client: TestClient,
) -> None:
    """Uploaded files download back byte-identically, including a deep path and an empty one."""
    nfc_name = unicodedata.normalize("NFC", "café.txt")
    deep_path = "payload/" + "/".join(f"d{level}" for level in range(1, 9)) + "/leaf.bin"
    files = [
        (f"payload/{nfc_name}", "hello café".encode()),
        ("payload/empty.bin", b""),
        (deep_path, b"deep content"),
    ]
    ingest = IngestClient(client)
    _, revision_id = ingest.committed(files)

    for path, data in files:
        response = ingest.download(revision_id, path)
        assert response.status_code == 200, response.text
        assert response.content == data
        assert response.headers["content-length"] == str(len(data))
        assert response.headers["content-type"] == "application/octet-stream"
        assert response.headers["etag"] == f'"{hashlib.sha256(data).hexdigest()}"'

    named = ingest.download(revision_id, f"payload/{nfc_name}")
    assert "filename*=utf-8''caf%C3%A9.txt" in named.headers["content-disposition"]


def test_file_download_reads_a_sealed_payload(client: TestClient, stores: ApiStores) -> None:
    """A committed file downloads through its 0o444 permission bits under a 0o555 root."""
    ingest = IngestClient(client)
    _, revision_id = ingest.committed([("payload/a.bin", b"hello")])
    record = stores.hierarchy._revisions[UUID(revision_id)]
    location = Path(record.revision_path) / "payload" / "a.bin"

    assert stat.S_IMODE(location.stat().st_mode) == 0o444
    assert stat.S_IMODE(Path(record.revision_path).stat().st_mode) == 0o555

    response = ingest.download(revision_id, "payload/a.bin")

    assert response.status_code == 200
    assert response.content == b"hello"


def test_file_download_refuses_traversal_and_non_nfc_spellings_before_touching_storage(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A traversal, a non-NFC spelling and a path outside payload/ are refused before storage."""
    ingest = IngestClient(client)
    _, revision_id = ingest.committed([("payload/a.bin", b"hello")])

    calls: list[object] = []
    real_read_document = PosixRawStore.read_document

    def _tracking_read_document(self: PosixRawStore, path: object) -> bytes:
        calls.append(path)
        return real_read_document(self, path)

    monkeypatch.setattr(PosixRawStore, "read_document", _tracking_read_document)

    traversal = ingest.download(revision_id, "payload/%2E%2E/x")
    assert traversal.status_code == 400
    assert traversal.json()["code"] == "PATH_TRAVERSAL"

    non_nfc_path = "payload/" + unicodedata.normalize("NFD", "café.txt")
    non_nfc = ingest.download(revision_id, non_nfc_path)
    assert non_nfc.status_code == 400
    assert non_nfc.json()["code"] == "PATH_NOT_NFC"

    outside = ingest.download(revision_id, "x")
    assert outside.status_code == 400
    assert outside.json()["code"] == "PATH_OUTSIDE_PAYLOAD"

    assert calls == []


def test_file_download_404s_a_path_the_manifest_does_not_list_even_if_it_exists_on_disk(
    client: TestClient, stores: ApiStores
) -> None:
    """A stray file placed under payload/ is 404: the manifest is the authority, not disk."""
    ingest = IngestClient(client)
    _, revision_id = ingest.committed([("payload/a.bin", b"hello")])
    record = stores.hierarchy._revisions[UUID(revision_id)]
    payload_dir = Path(record.revision_path) / "payload"
    payload_dir.chmod(0o755)
    (payload_dir / "stray.bin").write_bytes(b"not listed")
    payload_dir.chmod(0o555)

    response = ingest.download(revision_id, "payload/stray.bin")

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


def test_download_authorization_requires_data_read_on_raw_and_hides_invisible_datasets(
    client: TestClient,
) -> None:
    """A reader downloads; a service account is refused with 403, an invisible dataset with 404.

    A principal bound on the dataset's own project can see it, so a
    service account of the same organization - restricted by kind to
    silver and gold - is refused with 403 rather than 404; a principal
    with no binding reaching the project at all cannot even discover it,
    so both an unrelated, unbound user and an outsider on a sibling
    project they hold no binding on are refused with 404 instead, on
    every route including the one (``get_revision``) that needs only
    visibility.
    """
    ingest = IngestClient(client)
    _, revision_id = ingest.committed([("payload/a.bin", b"hello")])
    ingest.reader("carol")

    account = client.post(
        f"/api/v1/organizations/{ingest.organization_id}/service-accounts",
        json={"name": "canonicalizer"},
        headers=dev_headers(_ADMIN),
    ).json()
    key = client.post(
        f"/api/v1/organizations/{ingest.organization_id}/service-accounts/"
        f"{account['principal_id']}/api-keys",
        json={"name": "ci"},
        headers=dev_headers(_ADMIN),
    ).json()
    sa_headers = {"Authorization": f"Bearer {key['secret']}"}

    reader_view = client.get(f"/api/v1/revisions/{revision_id}", headers=dev_headers("carol"))
    assert reader_view.status_code == 200
    for suffix in ("manifest", "files/payload/a.bin"):
        url = f"/api/v1/revisions/{revision_id}/{suffix}"
        allowed = client.get(url, headers=dev_headers("carol"))
        assert allowed.status_code == 200, allowed.text
        refused = client.get(url, headers=sa_headers)
        assert refused.status_code == 403
        assert refused.json()["code"] == "FORBIDDEN"
        unbound = client.get(url, headers=dev_headers("erin"))
        assert unbound.status_code == 404

    owner = IngestClient(client, subject="alice")
    _, sibling_revision_id = owner.committed(
        [("payload/a.bin", b"secret")], organization_slug="vault", project_slug="sealed"
    )
    invisible = client.get(f"/api/v1/revisions/{sibling_revision_id}", headers=dev_headers("bob"))
    assert invisible.status_code == 404
    for suffix in ("manifest", "files/payload/a.bin"):
        outsider = client.get(
            f"/api/v1/revisions/{sibling_revision_id}/{suffix}", headers=dev_headers("bob")
        )
        assert outsider.status_code == 404


def test_download_is_re_authorized_on_every_request(client: TestClient) -> None:
    """A 200 download turns into a refusal on the very next request once the binding is revoked.

    A reader's only binding carries both the project's visibility and its
    raw-read grant together, so revoking it removes both at once and the
    next request answers 404 rather than 403 - the same "absent or not
    discoverable" answer an unbound caller gets. Either way the point
    holds: nothing is cached between requests, so a revoked binding takes
    effect on the very next one.
    """
    ingest = IngestClient(client)
    _, revision_id = ingest.committed([("payload/a.bin", b"hello")])
    ingest.reader("carol")
    reader = IngestClient(client, subject="carol")

    first = reader.download(revision_id, "payload/a.bin")
    assert first.status_code == 200, first.text

    bindings = client.get(
        f"/api/v1/projects/{ingest.project_id}/bindings", headers=dev_headers(_ADMIN)
    ).json()
    binding_id = next(item["id"] for item in bindings["items"] if item["principal"] == "user:carol")
    revoked = client.delete(
        f"/api/v1/projects/{ingest.project_id}/bindings/{binding_id}", headers=dev_headers(_ADMIN)
    )
    assert revoked.status_code == 204

    second = reader.download(revision_id, "payload/a.bin")
    assert second.status_code == 404
    assert second.json()["code"] == "NOT_FOUND"


def test_range_requests_are_served_and_an_unsatisfiable_one_is_416(client: TestClient) -> None:
    """A satisfiable Range downloads as 206; one naming bytes past the end is 416."""
    ingest = IngestClient(client)
    _, revision_id = ingest.committed([("payload/a.bin", b"hello")])

    partial = ingest.download(revision_id, "payload/a.bin", headers={"Range": "bytes=1-3"})
    assert partial.status_code == 206, partial.text
    assert partial.content == b"ell"
    assert partial.headers["content-range"] == "bytes 1-3/5"

    unsatisfiable = ingest.download(revision_id, "payload/a.bin", headers={"Range": "bytes=99999-"})
    assert unsatisfiable.status_code == 416
    assert unsatisfiable.content == b""
    assert unsatisfiable.headers["content-range"] == "bytes */5"


def test_a_listed_file_missing_or_short_on_disk_is_a_server_error(
    client: TestClient, stores: ApiStores
) -> None:
    """A listed file missing, short, or a manifest-identity mismatch is a 500, not a silent 200."""
    ingest = IngestClient(client)
    _, revision_id = ingest.committed([("payload/a.bin", b"hello world")])
    record = stores.hierarchy._revisions[UUID(revision_id)]
    payload_dir = Path(record.revision_path) / "payload"
    location = payload_dir / "a.bin"

    payload_dir.chmod(0o755)
    location.chmod(0o644)
    location.unlink()
    missing = ingest.download(revision_id, "payload/a.bin")
    assert missing.status_code == 500
    assert missing.json()["code"] == "INTERNAL_ERROR"

    location.write_bytes(b"short")
    location.chmod(0o444)
    payload_dir.chmod(0o555)
    truncated = ingest.download(revision_id, "payload/a.bin")
    assert truncated.status_code == 500
    assert truncated.json()["code"] == "INTERNAL_ERROR"

    location.chmod(0o644)
    location.write_bytes(b"hello world")
    location.chmod(0o444)
    payload_dir.chmod(0o555)
    stores.hierarchy._revisions[UUID(revision_id)] = replace(record, manifest_sha256="0" * 64)
    mismatched = ingest.download(revision_id, "payload/a.bin")
    assert mismatched.status_code == 500
    assert mismatched.json()["code"] == "INTERNAL_ERROR"
