"""The ingest-session surface: opening, reading, renewing and giving one up.

Drives the FastAPI app through a TestClient over an in-memory
``HierarchyStore`` with dev-header auth. Covers opening a session on an
existing dataset or by minting one at intake, reading it, renewing its
lease, aborting it, and the authorization each of those enforces.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from huron.pkg.catalog import (
    PART_BYTES,
    IngestState,
    ManifestEntry,
    RevisionRecord,
    validate_manifest,
)
from huron.pkg.catalog.documents import manifest_bytes
from huron.pkg.catalog.manifest import DEFAULT_MAX_FILE_BYTES
from huron.pkg.catalog.paths import revision_dir
from huron.pkg.rawstore import PosixRawStore
from huron.service.api.app import create_app
from huron.service.api.ingest import IngestService
from huron.service.api.settings import ApiSettings, ClassificationValue
from huron.service.api.stores import SystemClock
from tests.ingest_client import IngestClient, declared_file, manifest_file
from tests.unit.support import crash_on, memory_stores

if TYPE_CHECKING:
    from collections.abc import Iterator

    from huron.service.api.runtime import ApiStores

pytestmark = pytest.mark.unit

_ZERO_SHA = "a" * 64


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
        headers=_headers("bob"),
    )

    assert response.status_code == status, response.text
    assert response.json()["code"] == code


def test_create_refuses_a_dataset_whose_entry_layer_is_not_raw(client: TestClient) -> None:
    """A dataset that declares a bronze or silver entry layer refuses a raw ingest session."""
    organization = client.post(
        "/api/v1/organizations", json={"slug": "astro", "title": "Astro"}, headers=_headers("root")
    ).json()
    project = client.post(
        f"/api/v1/organizations/{organization['id']}/projects",
        json={"slug": "sims", "title": "Sims", "data_classification": "open"},
        headers=_headers("root"),
    ).json()
    assert (
        client.post(
            f"/api/v1/projects/{project['id']}/bindings",
            json={"principal": "user:bob", "role": "developer"},
            headers=_headers("root"),
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
        headers=_headers("bob"),
    ).json()

    response = client.post(
        f"/api/v1/datasets/{dataset['id']}/ingest-sessions",
        json={"files": [{"path": "payload/a.bin", "size": 1, "sha256": _ZERO_SHA}]},
        headers=_headers("bob"),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "LAYER_WORKFLOW_VIOLATION"


# -- create at intake ---------------------------------------------------------


def test_create_in_project_mints_the_dataset_then_opens_the_session(client: TestClient) -> None:
    """Minting a dataset at intake opens raw, and one key covers both idempotent writes."""
    organization = client.post(
        "/api/v1/organizations", json={"slug": "astro", "title": "Astro"}, headers=_headers("root")
    ).json()
    project = client.post(
        f"/api/v1/organizations/{organization['id']}/projects",
        json={"slug": "sims", "title": "Sims", "data_classification": "open"},
        headers=_headers("root"),
    ).json()
    assert (
        client.post(
            f"/api/v1/projects/{project['id']}/bindings",
            json={"principal": "user:bob", "role": "developer"},
            headers=_headers("root"),
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
        headers=_headers("bob", key=key),
    )
    assert first.status_code == 201, first.text
    dataset = client.get(
        f"/api/v1/datasets/{first.json()['dataset_id']}", headers=_headers("bob")
    ).json()
    assert dataset["entry_layer"] == "raw"
    assert dataset["slug"] == "feed-01"

    replay = client.post(
        f"/api/v1/projects/{project['id']}/ingest-sessions",
        json=body,
        headers=_headers("bob", key=key),
    )
    assert replay.status_code == 201
    assert replay.json()["id"] == first.json()["id"]

    changed = {**body, "files": [{"path": "payload/b.bin", "size": 1, "sha256": "b" * 64}]}
    reused = client.post(
        f"/api/v1/projects/{project['id']}/ingest-sessions",
        json=changed,
        headers=_headers("bob", key=key),
    )
    assert reused.status_code == 409
    assert reused.json()["code"] == "IDEMPOTENCY_KEY_REUSED"
    datasets = client.get(f"/api/v1/projects/{project['id']}/datasets", headers=_headers("bob"))
    assert len(datasets.json()["items"]) == 1


def test_intake_authorization_matrix(client: TestClient) -> None:
    """A developer opens sessions on both routes; a project admin and a service account cannot."""
    organization = client.post(
        "/api/v1/organizations", json={"slug": "astro", "title": "Astro"}, headers=_headers("root")
    ).json()
    project = client.post(
        f"/api/v1/organizations/{organization['id']}/projects",
        json={"slug": "sims", "title": "Sims", "data_classification": "open"},
        headers=_headers("root"),
    ).json()
    for subject, role in (("bob", "developer"), ("alice", "project_admin")):
        assert (
            client.post(
                f"/api/v1/projects/{project['id']}/bindings",
                json={"principal": f"user:{subject}", "role": role},
                headers=_headers("root"),
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
        headers=_headers("bob"),
    ).json()
    account = client.post(
        f"/api/v1/organizations/{organization['id']}/service-accounts",
        json={"name": "canonicalizer"},
        headers=_headers("root"),
    ).json()
    key = client.post(
        f"/api/v1/organizations/{organization['id']}/service-accounts/"
        f"{account['principal_id']}/api-keys",
        json={"name": "ci"},
        headers=_headers("root"),
    ).json()
    sa_headers = {"Authorization": f"Bearer {key['secret']}", "Idempotency-Key": str(uuid4())}
    files = [{"path": "payload/a.bin", "size": 1, "sha256": _ZERO_SHA}]

    dev_route1 = client.post(
        f"/api/v1/datasets/{dataset['id']}/ingest-sessions",
        json={"files": files},
        headers=_headers("bob"),
    )
    assert dev_route1.status_code == 201, dev_route1.text

    pa_route1 = client.post(
        f"/api/v1/datasets/{dataset['id']}/ingest-sessions",
        json={"files": files},
        headers=_headers("alice"),
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
            headers=_headers("bob"),
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
        f"/api/v1/projects/{project['id']}/ingest-sessions", json=body, headers=_headers("alice")
    )
    assert pa_route2.status_code == 403
    assert pa_route2.json()["code"] == "FORBIDDEN"

    sa_route2 = client.post(
        f"/api/v1/projects/{project['id']}/ingest-sessions", json=body, headers=sa_headers
    )
    assert sa_route2.status_code == 403
    assert sa_route2.json()["code"] == "LAYER_WRITE_FORBIDDEN"

    dev_route2 = client.post(
        f"/api/v1/projects/{project['id']}/ingest-sessions", json=body, headers=_headers("bob")
    )
    assert dev_route2.status_code == 201, dev_route2.text

    assert (
        client.post(
            f"/api/v1/projects/{uuid4()}/ingest-sessions", json=body, headers=_headers("bob")
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
            headers=_headers("root"),
        ).status_code
        == 201
    )
    outsider = client.get(f"/api/v1/ingest-sessions/{session_id}", headers=_headers("eve"))
    assert outsider.status_code == 403

    assert (
        client.post(
            f"/api/v1/projects/{project_id}/bindings",
            json={"principal": "user:alice", "role": "project_admin"},
            headers=_headers("root"),
        ).status_code
        == 201
    )
    as_admin = client.get(f"/api/v1/ingest-sessions/{session_id}", headers=_headers("alice"))
    assert as_admin.status_code == 200

    unknown = client.get(f"/api/v1/ingest-sessions/{uuid4()}", headers=_headers("bob"))
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
            headers=_headers("root"),
        ).status_code
        == 201
    )
    bindings = client.get(
        f"/api/v1/projects/{project_id}/bindings", headers=_headers("root")
    ).json()
    developer_binding_id = next(
        item["id"]
        for item in bindings["items"]
        if item["principal"] == "user:bob" and item["role_code"] == "developer"
    )
    assert (
        client.delete(
            f"/api/v1/projects/{project_id}/bindings/{developer_binding_id}",
            headers=_headers("root"),
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
            headers=_headers("root"),
        ).status_code
        == 201
    )
    forced = client.post(
        f"/api/v1/ingest-sessions/{second.json()['id']}/abort", headers=_headers("alice")
    )
    assert forced.status_code == 200
    assert forced.json()["state"] == "ABORTED"
    assert "ingest.force_aborted" in [event.kind for event in stores.hierarchy._audit]

    assert (
        client.post(
            f"/api/v1/projects/{project_id}/bindings",
            json={"principal": "user:carl", "role": "developer"},
            headers=_headers("root"),
        ).status_code
        == 201
    )
    third = ingest.create(dataset_id, [manifest_file("payload/a.bin", b"hello")]).json()
    not_owner = client.post(
        f"/api/v1/ingest-sessions/{third['id']}/abort", headers=_headers("carl")
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
    """GET, heartbeat and abort all 404 for a caller with no binding anywhere near the dataset.

    A binding is what makes a scope discoverable at all - the project's
    classification only refines what an already-covering binding reveals
    - so a principal with no binding anywhere sees nothing, whatever the
    classification says.
    """
    ingest = IngestClient(client)
    _, dataset_id = ingest.developer_dataset()
    session_id = ingest.create(dataset_id, [manifest_file("payload/a.bin", b"hello")]).json()["id"]

    outsider = _headers("eve")
    get_response = client.get(f"/api/v1/ingest-sessions/{session_id}", headers=outsider)
    assert get_response.status_code == 404
    heartbeat_response = client.post(
        f"/api/v1/ingest-sessions/{session_id}/heartbeat", headers=outsider
    )
    assert heartbeat_response.status_code == 404
    abort_response = client.post(f"/api/v1/ingest-sessions/{session_id}/abort", headers=outsider)
    assert abort_response.status_code == 404


# -- planning against a parent revision ---------------------------------------


def test_create_plans_hardlinks_against_the_latest_committed_revision(
    client: TestClient, stores: ApiStores, tmp_path: Path
) -> None:
    """A file identical to the parent's is hard-linked; a changed one must still be uploaded."""
    ingest = IngestClient(client)
    _, dataset_id = ingest.developer_dataset()

    dataset_view = client.get(f"/api/v1/datasets/{dataset_id}", headers=_headers("bob")).json()
    project_view = client.get(
        f"/api/v1/projects/{dataset_view['project_id']}", headers=_headers("bob")
    ).json()
    organization = client.get(
        f"/api/v1/organizations/{project_view['organization_id']}", headers=_headers("bob")
    ).json()

    unchanged = manifest_file("payload/a.bin", b"hello")
    changed = manifest_file("payload/b.bin", b"world")
    parent_manifest = validate_manifest(
        [ManifestEntry(path=unchanged.path, size=unchanged.size, sha256=unchanged.sha256)]
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
    (Path(path)).mkdir(parents=True)
    (Path(path) / "manifest.json").write_bytes(manifest_bytes(parent_manifest))
    record = RevisionRecord(
        id=revision_id,
        dataset_id=UUID(dataset_id),
        number=1,
        manifest_sha256=parent_manifest.sha256,
        metadata_sha256=_ZERO_SHA,
        revision_path=str(path),
        committed_by="bob",
        committed_at=datetime.now(UTC),
        file_count=1,
        total_bytes=parent_manifest.total_bytes,
    )
    stores.hierarchy._revisions[record.id] = record

    response = ingest.create(dataset_id, [unchanged, changed])

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["parent_revision_id"] == str(revision_id)
    files_by_path = {item["path"]: item for item in body["files"]}
    assert files_by_path["payload/a.bin"]["action"] == "hardlink"
    assert files_by_path["payload/a.bin"]["part_count"] == 0
    assert files_by_path["payload/b.bin"]["action"] == "upload"


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
