"""The ingest-session surface: opening, reading, renewing and giving one up.

Drives the FastAPI app through a TestClient over an in-memory
``HierarchyStore`` with dev-header auth. Covers opening a session on an
existing dataset or by minting one at intake, reading it, renewing its
lease, aborting it, and the authorization each of those enforces.
"""

from __future__ import annotations

import io
import json
import stat
import unicodedata
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest

import huron.pkg.catalog.ingest as ingest_module
from huron.core._ingest import IngestService
from huron.pkg.catalog import (
    PART_BYTES,
    FileState,
    IngestState,
    ManifestEntry,
    RevisionRecord,
    validate_manifest,
)
from huron.pkg.catalog.documents import (
    CommitRecord,
    MetadataDocument,
    decode_manifest,
    manifest_bytes,
)
from huron.pkg.catalog.errors import IllegalIngestTransition
from huron.pkg.catalog.manifest import DEFAULT_MAX_FILE_BYTES
from huron.pkg.catalog.paths import revision_dir, staging_dir
from huron.pkg.metastore import IdempotencyClaim, Replay, SystemClock
from huron.pkg.rawstore import PosixRawStore
from tests.ingest_client import IngestClient, declared_file, dev_headers, manifest_file
from tests.unit.support import crash_on

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from typing import BinaryIO

    from fastapi.testclient import TestClient

    from huron.applications.api.routes.v1.schema.ingest_sessions import ManifestFile
    from huron.applications.api.runtime import ApiStores

pytestmark = pytest.mark.unit

_ZERO_SHA = "a" * 64


@dataclass(frozen=True, slots=True)
class _Ref:
    """A minimal ``Slugged`` value: just enough for ``paths.revision_dir``."""

    id: UUID
    slug: str


def _files(count: int, *, size: int = 5, sha256: str = _ZERO_SHA) -> list[dict[str, object]]:
    """Build ``count`` distinct declared files of a given size and digest."""
    return [declared_file(f"payload/{i}", size, sha256).model_dump() for i in range(count)]


# -- create on an existing dataset -------------------------------------------


def test_create_returns_the_plan_and_locks_the_dataset(client: TestClient) -> None:
    """A create response carries the upload plan, and a second create locks out."""
    ingest = IngestClient(client)
    _, dataset_id = ingest.developer_dataset()

    response = ingest.create(dataset_id, [manifest_file("payload/a.bin", b"hello")])

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["state"] == "UPLOADING"
    assert body["etag"] == 2
    assert body["part_bytes"] == PART_BYTES
    assert body["dataset_id"] == dataset_id
    assert len(body["files"]) == 1
    file_view = body["files"][0]
    assert file_view["action"] == "upload"
    assert file_view["part_count"] == 1
    assert file_view["state"] == "PENDING"
    assert file_view["completed_parts"] == []
    assert response.headers["ETag"] == '"2"'

    locked = ingest.create(dataset_id, [manifest_file("payload/b.bin", b"world")])
    assert locked.status_code == 409
    assert locked.json()["code"] == "DATASET_LOCKED"
    assert locked.json()["context"]["session_id"] == body["id"]


def test_create_replays_under_the_same_key_and_refuses_a_changed_manifest(
    client: TestClient,
) -> None:
    """The same key and body replays the same session; a changed body under it is refused."""
    ingest = IngestClient(client)
    _, dataset_id = ingest.developer_dataset()
    key = str(uuid4())
    files = [manifest_file("payload/a.bin", b"hello")]

    first = ingest.create(dataset_id, files, key=key)
    assert first.status_code == 201, first.text

    replay = ingest.create(dataset_id, files, key=key)
    assert replay.status_code == 201
    assert replay.json()["id"] == first.json()["id"]

    changed = ingest.create(dataset_id, [manifest_file("payload/b.bin", b"world")], key=key)
    assert changed.status_code == 409
    assert changed.json()["code"] == "IDEMPOTENCY_KEY_REUSED"


@pytest.mark.parametrize(
    ("files", "status", "code"),
    [
        ([], 400, "EMPTY_REVISION"),
        ([{"path": "x", "size": 1, "sha256": _ZERO_SHA}], 400, "PATH_OUTSIDE_PAYLOAD"),
        (
            [
                {
                    "path": "payload/" + unicodedata.normalize("NFD", "café"),
                    "size": 1,
                    "sha256": _ZERO_SHA,
                }
            ],
            400,
            "PATH_NOT_NFC",
        ),
        ([{"path": "payload/" + "a" * 1025, "size": 1, "sha256": _ZERO_SHA}], 400, "PATH_TOO_LONG"),
        ([{"path": "payload/a/../b", "size": 1, "sha256": _ZERO_SHA}], 400, "PATH_TRAVERSAL"),
        ([{"path": "payload/a\x01", "size": 1, "sha256": _ZERO_SHA}], 400, "PATH_CONTROL_CHARS"),
        ([{"path": "payload/a\\b", "size": 1, "sha256": _ZERO_SHA}], 400, "PATH_SEPARATOR"),
        (
            [
                {"path": "payload/A", "size": 1, "sha256": _ZERO_SHA},
                {"path": "payload/a", "size": 1, "sha256": _ZERO_SHA},
            ],
            409,
            "PATH_COLLISION",
        ),
        (
            [{"path": "payload/big", "size": DEFAULT_MAX_FILE_BYTES + 1, "sha256": _ZERO_SHA}],
            413,
            "FILE_TOO_LARGE",
        ),
        (_files(10_001), 413, "TOO_MANY_FILES"),
        (_files(200, size=6 * 1024**3), 413, "REVISION_TOO_LARGE"),
    ],
)
def test_create_refuses_every_manifest_rule_with_its_documented_code(
    client: TestClient, files: list[dict[str, object]], status: int, code: str
) -> None:
    """Every manifest rule refuses with its documented status and code."""
    ingest = IngestClient(client)
    _, dataset_id = ingest.developer_dataset()

    response = client.post(
        f"/api/v1/datasets/{dataset_id}/ingest-sessions",
        json={"files": files},
        headers=dev_headers("bob"),
    )

    assert response.status_code == status, response.text
    assert response.json()["code"] == code


def test_create_refuses_a_dataset_whose_entry_layer_is_not_raw(client: TestClient) -> None:
    """A dataset that declares a bronze or silver entry layer refuses a raw ingest session."""
    organization = client.post(
        "/api/v1/organizations",
        json={"slug": "astro", "title": "Astro"},
        headers=dev_headers("root"),
    ).json()
    project = client.post(
        f"/api/v1/organizations/{organization['id']}/projects",
        json={"slug": "sims", "title": "Sims", "data_classification": "open"},
        headers=dev_headers("root"),
    ).json()
    assert (
        client.post(
            f"/api/v1/projects/{project['id']}/bindings",
            json={"principal": "user:bob", "role": "developer"},
            headers=dev_headers("root"),
        ).status_code
        == 201
    )
    dataset = client.post(
        f"/api/v1/projects/{project['id']}/datasets",
        json={
            "slug": "feed-01",
            "title": "Feed 1",
            "profile_name": "neutron-monitor",
            "profile_version": "1.0",
            "entry_layer": "bronze",
        },
        headers=dev_headers("bob"),
    ).json()

    response = client.post(
        f"/api/v1/datasets/{dataset['id']}/ingest-sessions",
        json={"files": [{"path": "payload/a.bin", "size": 1, "sha256": _ZERO_SHA}]},
        headers=dev_headers("bob"),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "LAYER_WORKFLOW_VIOLATION"


# -- create at intake ---------------------------------------------------------


def test_create_in_project_mints_the_dataset_then_opens_the_session(client: TestClient) -> None:
    """Minting a dataset at intake opens raw, and one key covers both idempotent writes."""
    organization = client.post(
        "/api/v1/organizations",
        json={"slug": "astro", "title": "Astro"},
        headers=dev_headers("root"),
    ).json()
    project = client.post(
        f"/api/v1/organizations/{organization['id']}/projects",
        json={"slug": "sims", "title": "Sims", "data_classification": "open"},
        headers=dev_headers("root"),
    ).json()
    assert (
        client.post(
            f"/api/v1/projects/{project['id']}/bindings",
            json={"principal": "user:bob", "role": "developer"},
            headers=dev_headers("root"),
        ).status_code
        == 201
    )
    body = {
        "dataset": {
            "slug": "feed-01",
            "title": "Feed 1",
            "profile_name": "neutron-monitor",
            "profile_version": "1.0",
        },
        "files": [{"path": "payload/a.bin", "size": 1, "sha256": _ZERO_SHA}],
    }
    key = str(uuid4())

    first = client.post(
        f"/api/v1/projects/{project['id']}/ingest-sessions",
        json=body,
        headers=dev_headers("bob", key=key),
    )
    assert first.status_code == 201, first.text
    dataset = client.get(
        f"/api/v1/datasets/{first.json()['dataset_id']}", headers=dev_headers("bob")
    ).json()
    assert dataset["entry_layer"] == "raw"
    assert dataset["slug"] == "feed-01"

    replay = client.post(
        f"/api/v1/projects/{project['id']}/ingest-sessions",
        json=body,
        headers=dev_headers("bob", key=key),
    )
    assert replay.status_code == 201
    assert replay.json()["id"] == first.json()["id"]

    changed = {**body, "files": [{"path": "payload/b.bin", "size": 1, "sha256": "b" * 64}]}
    reused = client.post(
        f"/api/v1/projects/{project['id']}/ingest-sessions",
        json=changed,
        headers=dev_headers("bob", key=key),
    )
    assert reused.status_code == 409
    assert reused.json()["code"] == "IDEMPOTENCY_KEY_REUSED"
    datasets = client.get(f"/api/v1/projects/{project['id']}/datasets", headers=dev_headers("bob"))
    assert len(datasets.json()["items"]) == 1


def test_intake_authorization_matrix(client: TestClient) -> None:
    """A developer opens sessions on both routes; a project admin and a service account cannot."""
    organization = client.post(
        "/api/v1/organizations",
        json={"slug": "astro", "title": "Astro"},
        headers=dev_headers("root"),
    ).json()
    project = client.post(
        f"/api/v1/organizations/{organization['id']}/projects",
        json={"slug": "sims", "title": "Sims", "data_classification": "open"},
        headers=dev_headers("root"),
    ).json()
    for subject, role in (("bob", "developer"), ("alice", "project_admin")):
        assert (
            client.post(
                f"/api/v1/projects/{project['id']}/bindings",
                json={"principal": f"user:{subject}", "role": role},
                headers=dev_headers("root"),
            ).status_code
            == 201
        )
    dataset = client.post(
        f"/api/v1/projects/{project['id']}/datasets",
        json={
            "slug": "run-0001",
            "title": "Run 1",
            "profile_name": "mcnp-run",
            "profile_version": "1.0",
        },
        headers=dev_headers("bob"),
    ).json()
    account = client.post(
        f"/api/v1/organizations/{organization['id']}/service-accounts",
        json={"name": "canonicalizer"},
        headers=dev_headers("root"),
    ).json()
    key = client.post(
        f"/api/v1/organizations/{organization['id']}/service-accounts/"
        f"{account['principal_id']}/api-keys",
        json={"name": "ci"},
        headers=dev_headers("root"),
    ).json()
    sa_headers = {"Authorization": f"Bearer {key['secret']}", "Idempotency-Key": str(uuid4())}
    files = [{"path": "payload/a.bin", "size": 1, "sha256": _ZERO_SHA}]

    dev_route1 = client.post(
        f"/api/v1/datasets/{dataset['id']}/ingest-sessions",
        json={"files": files},
        headers=dev_headers("bob"),
    )
    assert dev_route1.status_code == 201, dev_route1.text

    pa_route1 = client.post(
        f"/api/v1/datasets/{dataset['id']}/ingest-sessions",
        json={"files": files},
        headers=dev_headers("alice"),
    )
    assert pa_route1.status_code == 403
    assert pa_route1.json()["code"] == "FORBIDDEN"

    sa_route1 = client.post(
        f"/api/v1/datasets/{dataset['id']}/ingest-sessions",
        json={"files": files},
        headers=sa_headers,
    )
    assert sa_route1.status_code == 403
    assert sa_route1.json()["code"] == "LAYER_WRITE_FORBIDDEN"

    assert (
        client.post(
            f"/api/v1/datasets/{uuid4()}/ingest-sessions",
            json={"files": files},
            headers=dev_headers("bob"),
        ).status_code
        == 404
    )

    body = {
        "dataset": {
            "slug": "feed-01",
            "title": "Feed 1",
            "profile_name": "x",
            "profile_version": "1.0",
        },
        "files": files,
    }

    pa_route2 = client.post(
        f"/api/v1/projects/{project['id']}/ingest-sessions", json=body, headers=dev_headers("alice")
    )
    assert pa_route2.status_code == 403
    assert pa_route2.json()["code"] == "FORBIDDEN"

    sa_route2 = client.post(
        f"/api/v1/projects/{project['id']}/ingest-sessions", json=body, headers=sa_headers
    )
    assert sa_route2.status_code == 403
    assert sa_route2.json()["code"] == "LAYER_WRITE_FORBIDDEN"

    dev_route2 = client.post(
        f"/api/v1/projects/{project['id']}/ingest-sessions", json=body, headers=dev_headers("bob")
    )
    assert dev_route2.status_code == 201, dev_route2.text

    assert (
        client.post(
            f"/api/v1/projects/{uuid4()}/ingest-sessions", json=body, headers=dev_headers("bob")
        ).status_code
        == 404
    )


# -- reading, renewing and giving up ------------------------------------------


def test_get_shows_progress_and_the_etag(client: TestClient) -> None:
    """A GET matches the create response, refuses a non-owner, and allows a project admin."""
    ingest = IngestClient(client)
    project_id, dataset_id = ingest.developer_dataset()
    created = ingest.create(dataset_id, [manifest_file("payload/a.bin", b"hello")])
    session_id = created.json()["id"]

    got = ingest.get(session_id)
    assert got.status_code == 200
    assert got.json() == created.json()
    assert got.headers["ETag"] == created.headers["ETag"]

    assert (
        client.post(
            f"/api/v1/projects/{project_id}/bindings",
            json={"principal": "user:eve", "role": "reader"},
            headers=dev_headers("root"),
        ).status_code
        == 201
    )
    outsider = client.get(f"/api/v1/ingest-sessions/{session_id}", headers=dev_headers("eve"))
    assert outsider.status_code == 403

    assert (
        client.post(
            f"/api/v1/projects/{project_id}/bindings",
            json={"principal": "user:alice", "role": "project_admin"},
            headers=dev_headers("root"),
        ).status_code
        == 201
    )
    as_admin = client.get(f"/api/v1/ingest-sessions/{session_id}", headers=dev_headers("alice"))
    assert as_admin.status_code == 200

    unknown = client.get(f"/api/v1/ingest-sessions/{uuid4()}", headers=dev_headers("bob"))
    assert unknown.status_code == 404


def test_heartbeat_moves_the_lease_and_not_the_etag(client: TestClient, stores: ApiStores) -> None:
    """A heartbeat extends the lease without touching the etag; a lapsed or terminal one refuses."""
    ingest = IngestClient(client)
    _, dataset_id = ingest.developer_dataset()
    created = ingest.create(dataset_id, [manifest_file("payload/a.bin", b"hello")]).json()

    beat = ingest.heartbeat(created["id"])
    assert beat.status_code == 200
    body = beat.json()
    assert body["etag"] == created["etag"]
    assert body["expires_at"] > created["expires_at"]

    session_id = UUID(created["id"])
    stored = stores.hierarchy._sessions[session_id]
    stores.hierarchy._sessions[session_id] = replace(
        stored, lease=replace(stored.lease, expires_at=datetime.now(UTC) - timedelta(hours=1))
    )
    lapsed = ingest.heartbeat(created["id"])
    assert lapsed.status_code == 409
    assert lapsed.json()["code"] == "INGEST_SESSION_EXPIRED"

    ingest.abort(created["id"])  # abort ignores the lease, releasing the dataset's lock
    second = ingest.create(dataset_id, [manifest_file("payload/b.bin", b"world")]).json()
    ingest.abort(second["id"])
    aborted_heartbeat = ingest.heartbeat(second["id"])
    assert aborted_heartbeat.status_code == 409
    assert aborted_heartbeat.json()["code"] == "INGEST_SESSION_EXPIRED"


def test_heartbeat_is_forbidden_once_the_owners_raw_write_binding_is_revoked(
    client: TestClient,
) -> None:
    """Heartbeat refuses once the owner's raw-write binding is gone; get and abort still work."""
    ingest = IngestClient(client)
    project_id, dataset_id = ingest.developer_dataset()
    session_id = ingest.create(dataset_id, [manifest_file("payload/a.bin", b"hello")]).json()["id"]

    # A reader binding keeps bob's visibility into the project once the
    # developer binding beneath it - his only write authority - is gone.
    assert (
        client.post(
            f"/api/v1/projects/{project_id}/bindings",
            json={"principal": "user:bob", "role": "reader"},
            headers=dev_headers("root"),
        ).status_code
        == 201
    )
    bindings = client.get(
        f"/api/v1/projects/{project_id}/bindings", headers=dev_headers("root")
    ).json()
    developer_binding_id = next(
        item["id"]
        for item in bindings["items"]
        if item["principal"] == "user:bob" and item["role_code"] == "developer"
    )
    assert (
        client.delete(
            f"/api/v1/projects/{project_id}/bindings/{developer_binding_id}",
            headers=dev_headers("root"),
        ).status_code
        == 204
    )

    revoked = ingest.heartbeat(session_id)
    assert revoked.status_code == 403
    assert revoked.json()["code"] == "FORBIDDEN"

    assert ingest.get(session_id).status_code == 200
    assert ingest.abort(session_id).status_code == 200


def test_abort_releases_the_lock_for_the_owner_and_a_project_admin(
    client: TestClient, stores: ApiStores
) -> None:
    """The owner and a project admin may abort; a non-owner developer may not."""
    ingest = IngestClient(client)
    project_id, dataset_id = ingest.developer_dataset()

    first = ingest.create(dataset_id, [manifest_file("payload/a.bin", b"hello")]).json()
    owner_abort = ingest.abort(first["id"])
    assert owner_abort.status_code == 200
    assert owner_abort.json()["state"] == "ABORTED"
    assert "ingest.aborted" in [event.kind for event in stores.hierarchy._audit]

    second = ingest.create(dataset_id, [manifest_file("payload/a.bin", b"hello")])
    assert second.status_code == 201
    assert second.json()["revision_number"] == 1

    assert (
        client.post(
            f"/api/v1/projects/{project_id}/bindings",
            json={"principal": "user:alice", "role": "project_admin"},
            headers=dev_headers("root"),
        ).status_code
        == 201
    )
    forced = client.post(
        f"/api/v1/ingest-sessions/{second.json()['id']}/abort", headers=dev_headers("alice")
    )
    assert forced.status_code == 200
    assert forced.json()["state"] == "ABORTED"
    assert "ingest.force_aborted" in [event.kind for event in stores.hierarchy._audit]

    assert (
        client.post(
            f"/api/v1/projects/{project_id}/bindings",
            json={"principal": "user:carl", "role": "developer"},
            headers=dev_headers("root"),
        ).status_code
        == 201
    )
    third = ingest.create(dataset_id, [manifest_file("payload/a.bin", b"hello")]).json()
    not_owner = client.post(
        f"/api/v1/ingest-sessions/{third['id']}/abort", headers=dev_headers("carl")
    )
    assert not_owner.status_code == 403

    already_aborted = ingest.abort(third["id"])
    assert already_aborted.status_code == 200
    re_abort = ingest.abort(third["id"])
    assert re_abort.status_code == 409
    assert re_abort.json()["code"] == "ILLEGAL_INGEST_TRANSITION"

    fourth = ingest.create(dataset_id, [manifest_file("payload/a.bin", b"hello")]).json()
    session_id = UUID(fourth["id"])
    stored = stores.hierarchy._sessions[session_id]
    stores.hierarchy._sessions[session_id] = replace(
        stored, state=IngestState.COMMITTING, etag=stored.etag + 1
    )
    committing_abort = ingest.abort(fourth["id"])
    assert committing_abort.status_code == 409
    assert committing_abort.json()["code"] == "ILLEGAL_INGEST_TRANSITION"


def test_every_session_route_hides_an_invisible_dataset(client: TestClient) -> None:
    """GET, upload, complete, verify, commit, heartbeat and abort all 404 for an outsider.

    A binding is what makes a scope discoverable at all - the project's
    classification only refines what an already-covering binding reveals
    - so a principal with no binding anywhere sees nothing, whatever the
    classification says.
    """
    ingest = IngestClient(client)
    _, dataset_id = ingest.developer_dataset()
    created = ingest.create(dataset_id, [manifest_file("payload/a.bin", b"hello")]).json()
    session_id = created["id"]
    file_id = created["files"][0]["file_id"]

    outsider = dev_headers("eve")
    get_response = client.get(f"/api/v1/ingest-sessions/{session_id}", headers=outsider)
    assert get_response.status_code == 404
    heartbeat_response = client.post(
        f"/api/v1/ingest-sessions/{session_id}/heartbeat", headers=outsider
    )
    assert heartbeat_response.status_code == 404
    part_response = client.put(
        f"/api/v1/transfer/uploads/{file_id}/parts/1",
        content=b"hello",
        headers={**outsider, "Content-Length": "5"},
    )
    assert part_response.status_code == 404
    complete_response = client.post(
        f"/api/v1/transfer/uploads/{file_id}/complete", headers=outsider
    )
    assert complete_response.status_code == 404
    verify_response = client.post(f"/api/v1/ingest-sessions/{session_id}/verify", headers=outsider)
    assert verify_response.status_code == 404
    commit_response = client.post(
        f"/api/v1/ingest-sessions/{session_id}/commit",
        json={
            "manifest_sha256": created["manifest_sha256"],
            "metadata": {"title": "x", "creators": ["eve"]},
        },
        headers={**outsider, "If-Match": '"2"'},
    )
    assert commit_response.status_code == 404
    abort_response = client.post(f"/api/v1/ingest-sessions/{session_id}/abort", headers=outsider)
    assert abort_response.status_code == 404


# -- planning against a parent revision ---------------------------------------


def test_a_staging_failure_at_create_fails_the_session_and_frees_the_number(
    client: TestClient, stores: ApiStores, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A crash while staging the envelope fails the session and lets a retry re-take the number."""
    ingest = IngestClient(client)
    _, dataset_id = ingest.developer_dataset()

    # Call 1 is ``.staging`` itself, created with ``exist_ok=True`` and
    # already present; ``pathlib`` swallows an injected failure there once
    # it sees the directory exists. Call 2 is the envelope's own
    # exclusive ``mkdir``, which has no such fallback.
    crash_on(monkeypatch, "mkdir", call=2)
    failed = ingest.create(dataset_id, [manifest_file("payload/a.bin", b"hello")])
    assert failed.status_code == 500

    assert "ingest.failed" in [event.kind for event in stores.hierarchy._audit]
    sessions = list(stores.hierarchy._sessions.values())
    assert len(sessions) == 1
    assert sessions[0].state is IngestState.FAILED

    retry = ingest.create(dataset_id, [manifest_file("payload/a.bin", b"hello")])
    assert retry.status_code == 201, retry.text
    assert retry.json()["revision_number"] == 1


# -- the upload transport ------------------------------------------------------


def _untouched_body(data: bytes, touched: list[bool]) -> Iterator[bytes]:
    """Yield ``data`` once, recording that the generator was actually iterated.

    Args:
        data: The bytes to yield if the generator is ever pulled from.
        touched: Appended to on the generator's first iteration, so a test
            can assert a refused request never read this at all.

    Yields:
        ``data``, once.
    """
    touched.append(True)
    yield data


def _seed_committed_revision(
    client: TestClient,
    stores: ApiStores,
    tmp_path: Path,
    dataset_id: str,
    files: Sequence[ManifestFile],
) -> UUID:
    """Publish a fake committed revision directly against the store, for planning tests.

    Args:
        client: The dev-header client, used to resolve the dataset's
            organization and project names.
        stores: The store bundle the app was wired with.
        tmp_path: The test's temporary directory, the app's data root.
        dataset_id: The dataset the revision belongs to.
        files: The manifest files the revision holds.

    Returns:
        The seeded revision's identifier.
    """
    dataset_view = client.get(f"/api/v1/datasets/{dataset_id}", headers=dev_headers("bob")).json()
    project_view = client.get(
        f"/api/v1/projects/{dataset_view['project_id']}", headers=dev_headers("bob")
    ).json()
    organization = client.get(
        f"/api/v1/organizations/{project_view['organization_id']}", headers=dev_headers("bob")
    ).json()
    manifest = validate_manifest(
        [ManifestEntry(path=item.path, size=item.size, sha256=item.sha256) for item in files]
    )
    revision_id = uuid4()
    path = revision_dir(
        PurePosixPath(str(tmp_path / "data")),
        _Ref(id=UUID(organization["id"]), slug=organization["slug"]),
        _Ref(id=UUID(project_view["id"]), slug=project_view["slug"]),
        _Ref(id=UUID(dataset_view["id"]), slug=dataset_view["slug"]),
        1,
        revision_id,
    )
    Path(path).mkdir(parents=True)
    (Path(path) / "manifest.json").write_bytes(manifest_bytes(manifest))
    record = RevisionRecord(
        id=revision_id,
        dataset_id=UUID(dataset_id),
        number=1,
        manifest_sha256=manifest.sha256,
        metadata_sha256=_ZERO_SHA,
        revision_path=str(path),
        committed_by="bob",
        committed_at=datetime.now(UTC),
        file_count=len(manifest.files),
        total_bytes=manifest.total_bytes,
    )
    stores.hierarchy._revisions[record.id] = record
    return revision_id


async def _drive_a_disconnect(
    app: object, *, subject: str, file_id: str, part: int, content_length: int, first_chunk: bytes
) -> tuple[int, dict[str, object]]:
    """Drive one part upload through the raw ASGI app, disconnecting mid-body.

    ``TestClient`` never sends ``http.disconnect`` partway through a
    request body, so proving the route's behavior under a genuine
    mid-stream disconnect means driving the ASGI application directly.

    Args:
        app: The ASGI application to drive.
        subject: The dev-header subject to authenticate as.
        file_id: The file the part belongs to.
        part: The 1-based part number being sent.
        content_length: The ``Content-Length`` header to declare.
        first_chunk: The one chunk of body sent before disconnecting.

    Returns:
        The response's status code and its decoded JSON body.
    """
    messages = iter(
        [
            {"type": "http.request", "body": first_chunk, "more_body": True},
            {"type": "http.disconnect"},
        ]
    )
    captured: dict[str, object] = {"status": None, "body": b""}

    async def receive() -> dict[str, object]:
        return next(messages)

    async def send(message: dict[str, object]) -> None:
        if message["type"] == "http.response.start":
            captured["status"] = message["status"]
        elif message["type"] == "http.response.body":
            captured["body"] = captured["body"] + message.get("body", b"")

    path = f"/api/v1/transfer/uploads/{file_id}/parts/{part}"
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "PUT",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"x-huron-subject", subject.encode()),
            (b"content-length", str(content_length).encode()),
        ],
        "server": ("testserver", 80),
        "client": ("testclient", 123),
    }
    await app(scope, receive, send)
    return captured["status"], json.loads(captured["body"])


def test_a_single_part_upload_completes_the_file(client: TestClient) -> None:
    """A single-part upload with matching bytes completes the file and renews the lease."""
    ingest = IngestClient(client)
    _, dataset_id = ingest.developer_dataset()
    data = b"hello"
    session = ingest.create(dataset_id, [manifest_file("payload/a.bin", data)]).json()
    file_id = session["files"][0]["file_id"]

    response = ingest.put_part(file_id, 1, data)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "COMPLETE"
    assert body["completed_parts"] == [1]
    after = ingest.get(session["id"]).json()
    assert after["expires_at"] > session["expires_at"]


def test_a_multipart_upload_resumes_without_resending_completed_parts(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Parts may land out of order; a completed file refuses a re-sent part."""
    monkeypatch.setattr(ingest_module, "PART_BYTES", 4)
    ingest = IngestClient(client)
    _, dataset_id = ingest.developer_dataset()
    data = b"0123456789"
    session = ingest.create(dataset_id, [manifest_file("payload/a.bin", data)]).json()
    file_id = session["files"][0]["file_id"]
    assert session["files"][0]["part_count"] == 3

    third = ingest.put_part(file_id, 3, data[8:10])
    assert third.status_code == 200, third.text
    assert third.json()["completed_parts"] == [3]

    first = ingest.put_part(file_id, 1, data[0:4])
    assert first.status_code == 200, first.text
    assert sorted(first.json()["completed_parts"]) == [1, 3]
    assert ingest.get(session["id"]).json()["files"][0]["state"] == "PENDING"

    second = ingest.put_part(file_id, 2, data[4:8])
    assert second.status_code == 200, second.text
    assert sorted(second.json()["completed_parts"]) == [1, 2, 3]

    completed = ingest.complete(file_id)
    assert completed.status_code == 200, completed.text
    assert completed.json()["state"] == "COMPLETE"

    resent = ingest.put_part(file_id, 2, data[4:8])
    assert resent.status_code == 409
    assert resent.json()["code"] == "ILLEGAL_INGEST_TRANSITION"


def test_an_upload_refuses_a_content_length_that_disagrees_with_the_plan_before_reading(
    client: TestClient,
) -> None:
    """A Content-Length off by one is a manifest mismatch; a missing header is 422."""
    ingest = IngestClient(client)
    _, dataset_id = ingest.developer_dataset()
    data = b"hello"
    session = ingest.create(dataset_id, [manifest_file("payload/a.bin", data)]).json()
    file_id = session["files"][0]["file_id"]

    wrong_length = ingest.put_part(file_id, 1, data, content_length=len(data) - 1)
    assert wrong_length.status_code == 400
    body = wrong_length.json()
    assert body["code"] == "MANIFEST_MISMATCH"
    assert body["context"]["expected_length"] == len(data)
    assert body["context"]["content_length"] == len(data) - 1

    missing = ingest.put_part(file_id, 1, iter([data]))
    assert missing.status_code == 422

    unchanged = ingest.get(session["id"]).json()
    assert unchanged["files"][0]["completed_parts"] == []


def test_a_short_body_is_a_manifest_mismatch_and_leaves_the_part_pending(
    client: TestClient,
) -> None:
    """A body that ends before its declared Content-Length is a manifest mismatch."""
    ingest = IngestClient(client)
    _, dataset_id = ingest.developer_dataset()
    data = b"hello"
    session = ingest.create(dataset_id, [manifest_file("payload/a.bin", data)]).json()
    file_id = session["files"][0]["file_id"]

    def _short_body() -> Iterator[bytes]:
        yield data[:2]

    short = ingest.put_part(file_id, 1, _short_body(), content_length=len(data))
    assert short.status_code == 400
    body = short.json()
    assert body["code"] == "MANIFEST_MISMATCH"
    assert body["context"]["observed_length"] == 2

    unchanged = ingest.get(session["id"]).json()
    assert unchanged["files"][0]["completed_parts"] == []

    retry = ingest.put_part(file_id, 1, data)
    assert retry.status_code == 200, retry.text
    assert retry.json()["state"] == "COMPLETE"


def test_a_mismatched_single_part_file_is_discarded_and_back_to_pending(
    client: TestClient, tmp_path: Path
) -> None:
    """Wrong bytes for a single-part file discard the payload and leave the ledger untouched."""
    ingest = IngestClient(client)
    _, dataset_id = ingest.developer_dataset()
    data = b"hello"
    session = ingest.create(dataset_id, [manifest_file("payload/a.bin", data)]).json()
    file_id = session["files"][0]["file_id"]

    wrong = ingest.put_part(file_id, 1, b"wrong")
    assert wrong.status_code == 400
    body = wrong.json()
    assert body["code"] == "MANIFEST_MISMATCH"
    assert "observed_sha256" in body["context"]

    staging = staging_dir(PurePosixPath(str(tmp_path / "data")), UUID(session["id"]))
    assert not (Path(staging) / "payload" / "a.bin").exists()
    assert ingest.get(session["id"]).json()["files"][0]["completed_parts"] == []

    retry = ingest.put_part(file_id, 1, data)
    assert retry.status_code == 200, retry.text
    assert retry.json()["state"] == "COMPLETE"


def test_a_mismatched_multipart_file_is_discarded_at_complete(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A multipart file assembled from wrong bytes is discarded and reset to no parts."""
    monkeypatch.setattr(ingest_module, "PART_BYTES", 4)
    ingest = IngestClient(client)
    _, dataset_id = ingest.developer_dataset()
    data = b"0123456789"
    session = ingest.create(dataset_id, [manifest_file("payload/a.bin", data)]).json()
    file_id = session["files"][0]["file_id"]

    wrong = b"9876543210"
    for part, chunk in ((1, wrong[0:4]), (2, wrong[4:8]), (3, wrong[8:10])):
        assert ingest.put_part(file_id, part, chunk).status_code == 200

    mismatch = ingest.complete(file_id)
    assert mismatch.status_code == 400
    assert mismatch.json()["code"] == "MANIFEST_MISMATCH"

    after = ingest.get(session["id"]).json()["files"][0]
    assert after["completed_parts"] == []
    assert after["state"] == "PENDING"
    staging = staging_dir(PurePosixPath(str(tmp_path / "data")), UUID(session["id"]))
    assert not (Path(staging) / "payload" / "a.bin").exists()

    for part, chunk in ((1, data[0:4]), (2, data[4:8]), (3, data[8:10])):
        assert ingest.put_part(file_id, part, chunk).status_code == 200
    completed = ingest.complete(file_id)
    assert completed.status_code == 200, completed.text
    assert completed.json()["state"] == "COMPLETE"


def test_complete_refuses_a_file_that_has_not_received_every_part(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Completing a multipart file before every part has arrived is refused."""
    monkeypatch.setattr(ingest_module, "PART_BYTES", 4)
    ingest = IngestClient(client)
    _, dataset_id = ingest.developer_dataset()
    data = b"0123456789"
    session = ingest.create(dataset_id, [manifest_file("payload/a.bin", data)]).json()
    file_id = session["files"][0]["file_id"]

    assert ingest.put_part(file_id, 1, data[0:4]).status_code == 200

    response = ingest.complete(file_id)
    assert response.status_code == 409
    assert response.json()["code"] == "ILLEGAL_INGEST_TRANSITION"


def test_a_repeated_complete_is_refused_without_rehashing_the_file(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A second complete on an already-COMPLETE file is refused before its bytes are touched."""
    monkeypatch.setattr(ingest_module, "PART_BYTES", 4)
    ingest = IngestClient(client)
    _, dataset_id = ingest.developer_dataset()
    data = b"0123456789"
    session = ingest.create(dataset_id, [manifest_file("payload/a.bin", data)]).json()
    file_id = session["files"][0]["file_id"]
    for part, chunk in ((1, data[0:4]), (2, data[4:8]), (3, data[8:10])):
        assert ingest.put_part(file_id, part, chunk).status_code == 200
    first = ingest.complete(file_id)
    assert first.status_code == 200, first.text

    staging = staging_dir(PurePosixPath(str(tmp_path / "data")), UUID(session["id"]))
    (Path(staging) / "payload" / "a.bin").unlink()

    second = ingest.complete(file_id)

    assert second.status_code == 409, second.text
    assert second.json()["code"] == "ILLEGAL_INGEST_TRANSITION"


def test_upload_refusals_happen_before_the_body_is_read(
    client: TestClient, stores: ApiStores, tmp_path: Path
) -> None:
    """Every refusal before the stream opens leaves the request body completely unread."""
    ingest = IngestClient(client)
    project_id, dataset_id = ingest.developer_dataset()
    data = b"hello"

    session = ingest.create(dataset_id, [manifest_file("payload/a.bin", data)]).json()
    file_id = session["files"][0]["file_id"]
    for part in (0, session["files"][0]["part_count"] + 1):
        touched: list[bool] = []
        response = ingest.put_part(
            file_id, part, _untouched_body(data, touched), content_length=len(data)
        )
        assert response.status_code == 404, response.text
        assert touched == []
    ingest.abort(session["id"])

    verifying_session = ingest.create(dataset_id, [manifest_file("payload/b.bin", data)]).json()
    verifying_file_id = verifying_session["files"][0]["file_id"]
    verifying_id = UUID(verifying_session["id"])
    stored = stores.hierarchy._sessions[verifying_id]
    stores.hierarchy._sessions[verifying_id] = replace(
        stored, state=IngestState.VERIFYING, etag=stored.etag + 1
    )
    touched = []
    verifying_response = ingest.put_part(
        verifying_file_id, 1, _untouched_body(data, touched), content_length=len(data)
    )
    assert verifying_response.status_code == 409
    assert verifying_response.json()["code"] == "ILLEGAL_INGEST_TRANSITION"
    assert touched == []

    stores.hierarchy._sessions[verifying_id] = replace(
        stored,
        state=IngestState.UPLOADING,
        lease=replace(stored.lease, expires_at=datetime.now(UTC) - timedelta(hours=1)),
    )
    touched = []
    lapsed_response = ingest.put_part(
        verifying_file_id, 1, _untouched_body(data, touched), content_length=len(data)
    )
    assert lapsed_response.status_code == 409
    assert lapsed_response.json()["code"] == "INGEST_SESSION_EXPIRED"
    assert touched == []

    assert (
        client.post(
            f"/api/v1/projects/{project_id}/bindings",
            json={"principal": "user:carl", "role": "developer"},
            headers=dev_headers("root"),
        ).status_code
        == 201
    )
    outsider = IngestClient(client, subject="carl")
    touched = []
    outsider_response = outsider.put_part(
        verifying_file_id, 1, _untouched_body(data, touched), content_length=len(data)
    )
    assert outsider_response.status_code == 403
    assert touched == []

    ingest.abort(verifying_session["id"])
    revoked_session = ingest.create(dataset_id, [manifest_file("payload/c.bin", data)]).json()
    revoked_file_id = revoked_session["files"][0]["file_id"]
    # A reader binding keeps bob's visibility into the project once the
    # developer binding beneath it - his only write authority - is gone.
    assert (
        client.post(
            f"/api/v1/projects/{project_id}/bindings",
            json={"principal": "user:bob", "role": "reader"},
            headers=dev_headers("root"),
        ).status_code
        == 201
    )
    bindings = client.get(
        f"/api/v1/projects/{project_id}/bindings", headers=dev_headers("root")
    ).json()
    developer_binding_id = next(
        item["id"]
        for item in bindings["items"]
        if item["principal"] == "user:bob" and item["role_code"] == "developer"
    )
    assert (
        client.delete(
            f"/api/v1/projects/{project_id}/bindings/{developer_binding_id}",
            headers=dev_headers("root"),
        ).status_code
        == 204
    )
    touched = []
    revoked_response = ingest.put_part(
        revoked_file_id, 1, _untouched_body(data, touched), content_length=len(data)
    )
    assert revoked_response.status_code == 403
    assert touched == []


async def test_a_client_disconnect_mid_part_answers_400_and_keeps_the_ledger(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A raw ASGI disconnect mid-part answers 400 and leaves the ledger untouched."""
    monkeypatch.setattr(ingest_module, "PART_BYTES", 4)
    ingest = IngestClient(client)
    _, dataset_id = ingest.developer_dataset()
    data = b"01234567"
    session = ingest.create(dataset_id, [manifest_file("payload/a.bin", data)]).json()
    file_id = session["files"][0]["file_id"]

    status, body = await _drive_a_disconnect(
        client.app,
        subject="bob",
        file_id=file_id,
        part=1,
        content_length=4,
        first_chunk=data[:2],
    )

    assert status == 400
    assert body["code"] == "BAD_REQUEST"
    unchanged = ingest.get(session["id"]).json()
    assert unchanged["files"][0]["completed_parts"] == []


def test_a_new_client_resumes_from_the_session_view_and_re_sends_only_pending_files(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fresh client reads the session view and resends only what is still pending."""
    monkeypatch.setattr(ingest_module, "PART_BYTES", 4)
    first = IngestClient(client)
    _, dataset_id = first.developer_dataset()
    file_a = b"hi"
    file_b = b"0123456789"
    session = first.create(
        dataset_id,
        [manifest_file("payload/a.bin", file_a), manifest_file("payload/b.bin", file_b)],
    ).json()
    files_by_path = {item["path"]: item for item in session["files"]}

    a_response = first.put_part(files_by_path["payload/a.bin"]["file_id"], 1, file_a)
    assert a_response.status_code == 200, a_response.text
    assert a_response.json()["state"] == "COMPLETE"

    b_response = first.put_part(files_by_path["payload/b.bin"]["file_id"], 1, file_b[0:4])
    assert b_response.status_code == 200, b_response.text

    second = IngestClient(client)
    view = second.get(session["id"]).json()
    view_by_path = {item["path"]: item for item in view["files"]}
    assert view_by_path["payload/a.bin"]["state"] == "COMPLETE"
    assert view_by_path["payload/a.bin"]["completed_parts"] == [1]
    assert view_by_path["payload/b.bin"]["state"] == "PENDING"
    assert view_by_path["payload/b.bin"]["completed_parts"] == [1]

    sources = {"payload/a.bin": file_a, "payload/b.bin": file_b}

    def _source(path: str) -> BinaryIO:
        return io.BytesIO(sources[path])

    issued = second.upload(view, _source)
    assert issued == 2
    assert second.put_count == 2

    completion = second.complete(files_by_path["payload/b.bin"]["file_id"])
    assert completion.status_code == 200, completion.text
    assert completion.json()["state"] == "COMPLETE"

    resend = second.put_part(files_by_path["payload/a.bin"]["file_id"], 1, file_a)
    assert resend.status_code == 409
    assert resend.json()["code"] == "ILLEGAL_INGEST_TRANSITION"


# -- the facade beneath the routes --------------------------------------------


async def test_entry_reads_the_files_state_and_its_session_ledger(
    client: TestClient, stores: ApiStores, tmp_path: Path
) -> None:
    """The facade's ``entry`` reads one planned file paired with its session's ledger."""
    ingest = IngestClient(client)
    _, dataset_id = ingest.developer_dataset()
    session = ingest.create(dataset_id, [manifest_file("payload/a.bin", b"hello")]).json()
    file_id = UUID(session["files"][0]["file_id"])
    service = IngestService(
        PosixRawStore(str(tmp_path / "data")), stores.hierarchy, clock=SystemClock()
    )

    found_ledger, file = await service.entry(file_id)

    assert found_ledger.id == UUID(session["id"])
    assert file.file_id == file_id


async def test_two_parts_of_one_file_landing_at_once_both_persist_via_the_retry(
    client: TestClient, stores: ApiStores, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two parts driven from the same stale read still both land, one retrying past the other."""
    monkeypatch.setattr(ingest_module, "PART_BYTES", 4)
    ingest = IngestClient(client)
    _, dataset_id = ingest.developer_dataset()
    data = b"0123456789"
    session = ingest.create(dataset_id, [manifest_file("payload/a.bin", data)]).json()
    file_id = UUID(session["files"][0]["file_id"])
    service = IngestService(
        PosixRawStore(str(tmp_path / "data")), stores.hierarchy, clock=SystemClock()
    )
    stale_ledger, stale_file = await service.entry(file_id)

    first = await service.receive_part(
        stale_ledger, stale_file, 1, iter([data[0:4]]), content_length=4
    )
    assert first.completed_parts == frozenset({1})

    second = await service.receive_part(
        stale_ledger, stale_file, 2, iter([data[4:8]]), content_length=4
    )
    assert second.completed_parts == frozenset({1, 2})

    view = ingest.get(session["id"]).json()
    assert sorted(view["files"][0]["completed_parts"]) == [1, 2]


async def test_a_second_concurrent_complete_retries_past_the_first_then_refuses(
    client: TestClient, stores: ApiStores, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second complete driven from a stale read retries the race, then finds the file done."""
    monkeypatch.setattr(ingest_module, "PART_BYTES", 4)
    ingest = IngestClient(client)
    _, dataset_id = ingest.developer_dataset()
    data = b"0123456789"
    session = ingest.create(dataset_id, [manifest_file("payload/a.bin", data)]).json()
    file_id = UUID(session["files"][0]["file_id"])
    for part, chunk in ((1, data[0:4]), (2, data[4:8]), (3, data[8:10])):
        assert ingest.put_part(str(file_id), part, chunk).status_code == 200
    service = IngestService(
        PosixRawStore(str(tmp_path / "data")), stores.hierarchy, clock=SystemClock()
    )
    stale_ledger, stale_file = await service.entry(file_id)

    first = await service.complete_file(stale_ledger, stale_file)
    assert first.state == FileState.COMPLETE

    with pytest.raises(IllegalIngestTransition):
        await service.complete_file(stale_ledger, stale_file)


# -- verify and commit ---------------------------------------------------------


def test_verify_refuses_while_a_file_is_pending(client: TestClient) -> None:
    """Verify refuses, naming the incomplete paths, while a planned file is still pending."""
    ingest = IngestClient(client)
    _, dataset_id = ingest.developer_dataset()
    session = ingest.create(dataset_id, [manifest_file("payload/a.bin", b"hello")]).json()

    response = ingest.verify(session["id"])

    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "MANIFEST_MISMATCH"
    assert body["context"]["incomplete"] == ["payload/a.bin"]
    unchanged = ingest.get(session["id"]).json()
    assert unchanged["state"] == "UPLOADING"


def test_commit_publishes_the_revision_and_its_events(
    client: TestClient, stores: ApiStores, tmp_path: Path
) -> None:
    """A commit publishes the envelope's three documents, seals the root, and records its events."""
    ingest = IngestClient(client)
    _, dataset_id = ingest.developer_dataset()
    data = b"hello world"
    session = ingest.create(dataset_id, [manifest_file("payload/a.bin", data)]).json()
    ingest.put_part(session["files"][0]["file_id"], 1, data)
    verified = ingest.verify(session["id"]).json()

    response = ingest.commit(
        session["id"], verified["etag"], {"title": "Run 1", "creators": ["bob"]}
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["number"] == 1
    assert body["file_count"] == 1
    assert body["total_bytes"] == len(data)
    assert body["committed_by"] == "bob"

    record = stores.hierarchy._revisions[UUID(body["id"])]
    revision_path = Path(record.revision_path)
    assert revision_path.name.startswith("000001--")
    assert stat.S_IMODE(revision_path.stat().st_mode) == 0o555
    assert sorted(item.name for item in revision_path.iterdir()) == [
        "COMMITTED",
        "manifest.json",
        "metadata.json",
        "payload",
    ]

    manifest = decode_manifest((revision_path / "manifest.json").read_bytes())
    assert manifest.sha256 == body["manifest_sha256"]
    metadata_doc = MetadataDocument.decode((revision_path / "metadata.json").read_bytes())
    assert metadata_doc.sha256 == body["metadata_sha256"]
    assert metadata_doc.committed_by == "bob"
    marker = CommitRecord.decode((revision_path / "COMMITTED").read_bytes())
    assert marker.revision_record(revision_path=str(revision_path)) == record

    staging = staging_dir(PurePosixPath(str(tmp_path / "data")), UUID(session["id"]))
    assert not Path(staging).exists()

    assert stores.hierarchy._sessions[UUID(session["id"])].state is IngestState.COMMITTED
    committed_events = [e for e in stores.hierarchy._audit if e.kind == "revision.committed"]
    assert len(committed_events) == 1
    assert committed_events[0].subject_id == UUID(body["id"])
    outbox_kinds = [e.kind for e in stores.hierarchy._outbox]
    assert outbox_kinds.count("revision.committed") == 1

    release = client.post(
        f"/api/v1/datasets/{dataset_id}/releases",
        json={"tag": "v1", "revision_number": 1},
        headers=dev_headers("bob"),
    )
    assert release.status_code == 201, release.text


def test_commit_requires_the_current_etag_and_the_declared_digest(
    client: TestClient, stores: ApiStores
) -> None:
    """Commit refuses the wrong session state, a stale or malformed etag, and the wrong digest."""
    ingest = IngestClient(client)
    _, dataset_id = ingest.developer_dataset()
    data = b"hello"
    metadata = {"title": "Run", "creators": ["bob"]}
    session = ingest.create(dataset_id, [manifest_file("payload/a.bin", data)]).json()
    file_id = session["files"][0]["file_id"]

    from_uploading = ingest.commit(session["id"], session["etag"], metadata)
    assert from_uploading.status_code == 409
    assert from_uploading.json()["code"] == "ILLEGAL_INGEST_TRANSITION"

    ingest.put_part(file_id, 1, data)
    verified = ingest.verify(session["id"]).json()

    stale = ingest.commit(session["id"], verified["etag"] - 1, metadata)
    assert stale.status_code == 412
    assert stale.json()["code"] == "PRECONDITION_FAILED"

    malformed = client.post(
        f"/api/v1/ingest-sessions/{session['id']}/commit",
        json={"manifest_sha256": session["manifest_sha256"], "metadata": metadata},
        headers={**dev_headers("bob"), "If-Match": "not-an-integer"},
    )
    assert malformed.status_code == 422
    assert malformed.json()["code"] == "REQUEST_INVALID"

    wrong_digest = client.post(
        f"/api/v1/ingest-sessions/{session['id']}/commit",
        json={"manifest_sha256": "a" * 64, "metadata": metadata},
        headers={**dev_headers("bob"), "If-Match": f'"{verified["etag"]}"'},
    )
    assert wrong_digest.status_code == 400
    assert wrong_digest.json()["code"] == "MANIFEST_MISMATCH"

    session_id = UUID(session["id"])
    stored = stores.hierarchy._sessions[session_id]
    stores.hierarchy._sessions[session_id] = replace(
        stored, lease=replace(stored.lease, expires_at=datetime.now(UTC) - timedelta(hours=1))
    )
    lapsed = ingest.commit(session["id"], verified["etag"], metadata)
    assert lapsed.status_code == 409
    assert lapsed.json()["code"] == "INGEST_SESSION_EXPIRED"


def test_a_commit_whose_staged_manifest_disagrees_with_the_session_is_a_server_error(
    client: TestClient, tmp_path: Path
) -> None:
    """A staged manifest that no longer matches the session's declared identity is a server error.

    This is storage and the catalog disagreeing with each other, never a
    client mistake, so the reconciler owns it rather than the caller.
    """
    ingest = IngestClient(client)
    _, dataset_id = ingest.developer_dataset()
    data = b"hello"
    session = ingest.create(dataset_id, [manifest_file("payload/a.bin", data)]).json()
    ingest.put_part(session["files"][0]["file_id"], 1, data)
    verified = ingest.verify(session["id"]).json()

    staging = staging_dir(PurePosixPath(str(tmp_path / "data")), UUID(session["id"]))
    manifest_path = Path(staging) / "manifest.json"
    other = validate_manifest([ManifestEntry(path="payload/other.bin", size=3, sha256="b" * 64)])
    manifest_path.chmod(0o644)
    manifest_path.write_bytes(manifest_bytes(other))

    response = ingest.commit(session["id"], verified["etag"], {"title": "Run", "creators": ["bob"]})

    assert response.status_code == 500


async def test_a_commit_race_that_loses_its_claim_returns_the_winner_s_revision(
    client: TestClient, stores: ApiStores, tmp_path: Path
) -> None:
    """A commit whose idempotency claim was already remembered returns the recorded revision.

    Proves the facade's own defence against two concurrent attempts at the
    same commit racing past the envelope's publication and into the
    transaction together: whichever loses the claim returns what the
    winner recorded instead of raising or double-publishing.
    """
    ingest = IngestClient(client)
    _, dataset_id = ingest.developer_dataset()
    data = b"hello"
    session = ingest.create(dataset_id, [manifest_file("payload/a.bin", data)]).json()
    ingest.put_part(session["files"][0]["file_id"], 1, data)
    verified = ingest.verify(session["id"]).json()

    service = IngestService(
        PosixRawStore(str(tmp_path / "data")), stores.hierarchy, clock=SystemClock()
    )
    ledger = await service.ledger(UUID(session["id"]))
    metadata = {"title": "Run", "creators": ["bob"]}
    claim = IdempotencyClaim(
        principal="user:bob",
        key=str(uuid4()),
        request_sha256="already-claimed-by-the-winner",
    )
    winner = RevisionRecord(
        id=uuid4(),
        dataset_id=UUID(dataset_id),
        number=verified["revision_number"],
        manifest_sha256=verified["manifest_sha256"],
        metadata_sha256=_ZERO_SHA,
        revision_path="/wherever/the/winner/published",
        committed_by="bob",
        committed_at=datetime.now(UTC),
        file_count=1,
        total_bytes=len(data),
    )
    async with stores.hierarchy.transaction() as writer:
        assert await writer.claim(claim) is None
        await writer.insert_revision(winner)
        await writer.remember(claim, Replay(kind="revision", resource_id=winner.id))

    record = await service.commit(
        ledger,
        expected_etag=verified["etag"],
        manifest_sha256=verified["manifest_sha256"],
        metadata=metadata,
        committed_by="bob",
        claim=claim,
    )

    assert record == winner
    assert stores.hierarchy._sessions[UUID(session["id"])].state is IngestState.COMMITTING


def test_a_replayed_commit_returns_the_same_revision(client: TestClient) -> None:
    """A replayed commit under the same key, even with a stale etag, returns the same revision.

    Reusing the key for a distinct, not-yet-committed session's commit is
    refused instead of silently publishing a second revision under it.
    """
    ingest = IngestClient(client)
    _, dataset_id = ingest.developer_dataset()
    key = str(uuid4())
    data = b"hello"
    metadata = {"title": "Run", "creators": ["bob"]}
    session = ingest.create(dataset_id, [manifest_file("payload/a.bin", data)]).json()
    ingest.put_part(session["files"][0]["file_id"], 1, data)
    verified = ingest.verify(session["id"]).json()

    first = ingest.commit(session["id"], verified["etag"], metadata, key=key)
    assert first.status_code == 201, first.text

    replay = ingest.commit(session["id"], verified["etag"] - 1, metadata, key=key)
    assert replay.status_code == 201
    assert replay.json()["id"] == first.json()["id"]

    second_session = ingest.create(dataset_id, [manifest_file("payload/b.bin", b"other")]).json()
    ingest.put_part(second_session["files"][0]["file_id"], 1, b"other")
    second_verified = ingest.verify(second_session["id"]).json()

    reused = ingest.commit(
        second_session["id"],
        second_verified["etag"],
        {"title": "Other", "creators": ["bob"]},
        key=key,
    )

    assert reused.status_code == 409
    assert reused.json()["code"] == "IDEMPOTENCY_KEY_REUSED"
    still_committing = ingest.get(second_session["id"]).json()
    assert still_committing["state"] == "COMMITTING"
