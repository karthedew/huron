"""A fault at each on-disk step of a commit leaves one named state, and a retry recovers.

The publication a commit performs - documents, seal, marker, one rename,
one short transaction, a best-effort index - has one distinct outcome per
step a crash can land on: some leave the session terminal with the number
freed for a fresh attempt, others leave it recoverable by a plain retry
because storage has already moved past the point where the client's own
attempt still mattered. This module pins that outcome for the two steps
that straddle the rename: a crash before it, and a crash just after it.

A step indexed by an ``os.fsync`` call number cannot be targeted by its
path directly, because :func:`~tests.unit.support.crash_on` and
:func:`~tests.unit.support.fsync_log` both patch ``os.fsync`` and would
otherwise collide. Such a row first rehearses an equivalent commit - same
manifest shape, a sibling dataset - under ``fsync_log`` to learn which
numbered call the step of interest is, then applies ``crash_on`` with that
number against the real attempt in a fresh patch of its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from huron.pkg.catalog.documents import CommitRecord
from huron.pkg.catalog.paths import revision_dir, staging_dir
from huron.service.api.app import create_app
from huron.service.api.settings import ApiSettings, ClassificationValue
from tests.ingest_client import IngestClient, manifest_file
from tests.unit.support import crash_on, fsync_log, memory_stores

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from huron.service.api.runtime import ApiStores

pytestmark = pytest.mark.unit

_DATA = b"crash matrix payload"


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


def _final_path(
    client: TestClient, tmp_path: Path, dataset_id: str, *, number: int, revision_id: UUID
) -> Path:
    """Compute one revision's directory the same way the store lays it out.

    Args:
        client: The dev-header client, used to resolve the dataset's
            organization and project names.
        tmp_path: The test's temporary directory, the app's data root.
        dataset_id: The dataset the revision belongs to.
        number: The revision's 1-based position within the dataset.
        revision_id: The revision's identifier.

    Returns:
        The directory the revision publishes as.
    """
    dataset = client.get(f"/api/v1/datasets/{dataset_id}", headers=_headers("bob")).json()
    project = client.get(
        f"/api/v1/projects/{dataset['project_id']}", headers=_headers("bob")
    ).json()
    organization = client.get(
        f"/api/v1/organizations/{project['organization_id']}", headers=_headers("bob")
    ).json()
    return Path(
        revision_dir(
            PurePosixPath(str(tmp_path / "data")),
            _Ref(id=UUID(organization["id"]), slug=organization["slug"]),
            _Ref(id=UUID(project["id"]), slug=project["slug"]),
            _Ref(id=UUID(dataset["id"]), slug=dataset["slug"]),
            number,
            revision_id,
        )
    )


def _second_dataset(client: TestClient, project_id: str, slug: str) -> str:
    """Create an additional raw dataset in an already-bound project, for a rehearsal commit.

    Args:
        client: The dev-header client.
        project_id: The project to add the dataset to; ``bob`` must
            already hold ``developer`` on it.
        slug: The new dataset's slug.

    Returns:
        The new dataset's identifier.
    """
    response = client.post(
        f"/api/v1/projects/{project_id}/datasets",
        json={"slug": slug, "title": slug, "profile_name": "mcnp-run", "profile_version": "1.0"},
        headers=_headers("bob"),
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _crash_on_rename(
    monkeypatch: pytest.MonkeyPatch, client: TestClient, tmp_path: Path, project_id: str
) -> None:
    """Crash during the envelope's rename, before anything is published."""
    crash_on(monkeypatch, "rename", call=1)


def _crash_after_the_rename(
    monkeypatch: pytest.MonkeyPatch, client: TestClient, tmp_path: Path, project_id: str
) -> None:
    """Crash the parent directory's fsync that durably reveals the rename.

    A rehearsal commit of the same shape, in a sibling dataset, is driven
    to completion under a durability trace so the numbered ``os.fsync``
    call this step occupies can be found by the path it fsyncs; the same
    call number then targets the same step of the real attempt, because
    the two commits share one manifest shape and so one fsync sequence.
    """
    rehearsal = IngestClient(client, subject="bob")
    rehearsal_dataset_id = _second_dataset(client, project_id, "rehearsal")
    session = rehearsal.create(rehearsal_dataset_id, [manifest_file("payload/a.bin", _DATA)]).json()
    rehearsal.put_part(session["files"][0]["file_id"], 1, _DATA)
    verified = rehearsal.verify(session["id"]).json()
    final = _final_path(
        client,
        tmp_path,
        rehearsal_dataset_id,
        number=verified["revision_number"],
        revision_id=UUID(verified["revision_id"]),
    )
    with monkeypatch.context() as rehearsal_patch:
        log = fsync_log(rehearsal_patch)
        committed = rehearsal.commit(
            session["id"], verified["etag"], {"title": "Rehearsal", "creators": ["bob"]}
        )
        assert committed.status_code == 201, committed.text

        def call_of(path: Path) -> int:
            """Return the 1-based ``os.fsync`` call number the rehearsal fsynced ``path`` at."""
            return log.index(path) + 1

        call = call_of(final.parent)
    crash_on(monkeypatch, "fsync", call=call)


@dataclass(frozen=True, slots=True)
class _CrashRow:
    """One row of the commit crash matrix.

    Attributes:
        name: The row's identifier, used as the parametrization id.
        inject: Arranges the fault against the real attempt about to run.
        recovers: Whether the session is left COMMITTING for a retry to
            finish, rather than FAILED for good.
    """

    name: str
    inject: Callable[[pytest.MonkeyPatch, TestClient, Path, str], None]
    recovers: bool


_ROWS = (
    _CrashRow("rename", _crash_on_rename, recovers=False),
    _CrashRow("parent-fsync-after-rename", _crash_after_the_rename, recovers=True),
)


@pytest.mark.parametrize("row", _ROWS, ids=lambda row: row.name)
def test_a_crash_after_each_commit_step_leaves_the_named_state_and_the_retry_converges(
    client: TestClient,
    stores: ApiStores,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    row: _CrashRow,
) -> None:
    """A fault at each on-disk commit step leaves exactly one state, and a retry converges."""
    ingest = IngestClient(client)
    project_id, dataset_id = ingest.developer_dataset()
    session = ingest.create(dataset_id, [manifest_file("payload/a.bin", _DATA)]).json()
    ingest.put_part(session["files"][0]["file_id"], 1, _DATA)
    verified = ingest.verify(session["id"]).json()
    final = _final_path(
        client,
        tmp_path,
        dataset_id,
        number=verified["revision_number"],
        revision_id=UUID(verified["revision_id"]),
    )
    staging = staging_dir(PurePosixPath(str(tmp_path / "data")), UUID(session["id"]))
    metadata = {"title": "Run", "creators": ["bob"]}

    row.inject(monkeypatch, client, tmp_path, project_id)
    crashed = ingest.commit(session["id"], verified["etag"], metadata)

    assert crashed.status_code == 500
    session_id = UUID(session["id"])

    if not row.recovers:
        assert not final.exists()
        assert Path(staging).is_dir()
        after_crash = ingest.get(session["id"]).json()
        assert after_crash["state"] == "FAILED"
        assert "ingest.failed" in [event.kind for event in stores.hierarchy._audit]

        retry = ingest.create(dataset_id, [manifest_file("payload/b.bin", _DATA)])
        assert retry.status_code == 201, retry.text
        assert retry.json()["revision_number"] == 1
        return

    assert not Path(staging).exists()
    assert (final / "COMMITTED").is_file()
    stuck = stores.hierarchy._sessions[session_id]
    assert stuck.state.value == "COMMITTING"

    retried = ingest.commit(session["id"], stuck.etag, metadata)

    assert retried.status_code == 201, retried.text
    assert final.stat().st_mode & 0o777 == 0o555
    body = retried.json()
    marker = CommitRecord.decode((final / "COMMITTED").read_bytes())
    assert body["committed_at"] == marker.committed_at.isoformat().replace("+00:00", "Z")
    assert body["metadata_sha256"] == marker.metadata_sha256
    assert body["committed_by"] == marker.committed_by
    for_this_dataset = [
        record
        for record in stores.hierarchy._revisions.values()
        if record.dataset_id == UUID(dataset_id)
    ]
    assert len(for_this_dataset) == 1
