"""Publication faults preserve frozen evidence and converge on one revision."""

from __future__ import annotations

import errno
import os
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

import pytest

from huron.core._ingest import IngestService
from huron.pkg.catalog import ingest as ingest_module
from huron.pkg.catalog.ingest import FileState, IngestState
from huron.pkg.rawstore import PosixRawStore
from tests.ingest_client import IngestClient, dev_headers, manifest_file
from tests.unit.support import FakeClock, crash_on

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

    from huron.applications.api.runtime import ApiStores

pytestmark = pytest.mark.unit

_DATA = b"crash matrix payload"
_METADATA: dict[str, object] = {"title": "Run", "creators": ["bob"]}


def _verified(ingest: IngestClient, dataset_id: str) -> dict[str, object]:
    session = ingest.create(dataset_id, [manifest_file("payload/a.bin", _DATA)]).json()
    assert ingest.put_part(session["files"][0]["file_id"], 1, _DATA).status_code == 200
    verified = ingest.verify(session["id"])
    assert verified.status_code == 200
    return verified.json()


def _dataset(client: TestClient, project: str, slug: str) -> str:
    response = client.post(
        f"/api/v1/projects/{project}/datasets",
        json={"slug": slug, "title": slug, "profile_name": "mcnp-run", "profile_version": "1.0"},
        headers=dev_headers("bob"),
    )
    assert response.status_code == 201
    return response.json()["id"]


@pytest.mark.parametrize("operation", ["fsync", "fchmod", "write"])
def test_every_document_durability_failure_preserves_one_frozen_commit(
    client: TestClient, stores: ApiStores, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    """Each syscall failure leaves either a retriable intent or the one committed revision."""
    ingest = IngestClient(client)
    project, dataset = ingest.developer_dataset()
    rehearsal = _verified(ingest, dataset)
    with monkeypatch.context() as patch:
        calls = crash_on(patch, operation, call=10_000)
        result = ingest.commit(str(rehearsal["id"]), int(str(rehearsal["etag"])), _METADATA)
        assert result.status_code == 201, result.text
        checkpoints = len(calls)
    assert checkpoints > 0
    for checkpoint in range(1, checkpoints + 1):
        dataset = _dataset(client, project, f"fault-{operation}-{checkpoint}")
        verified = _verified(ingest, dataset)
        session_id = UUID(str(verified["id"]))
        with monkeypatch.context() as patch:
            calls = crash_on(patch, operation, call=checkpoint)
            response = ingest.commit(str(session_id), int(str(verified["etag"])), _METADATA)
            assert len(calls) >= checkpoint
            assert response.status_code in {201, 500}, response.text
        frozen = stores.hierarchy._intents[session_id]
        session = stores.hierarchy._sessions[session_id]
        assert session.state in {IngestState.COMMITTING, IngestState.COMMITTED}
        retried = ingest.commit(str(session_id), session.etag, _METADATA)
        assert retried.status_code == 201, retried.text
        record = stores.hierarchy._revisions[UUID(retried.json()["id"])]
        final = Path(record.revision_path)
        assert {name: (final / name).read_bytes() for name in frozen.documents} == frozen.documents
        assert (final / "payload/a.bin").read_bytes() == _DATA
        assert (final / "payload/a.bin").stat().st_nlink == 1
        assert sorted(path.name for path in final.iterdir()) == [
            "COMMITTED",
            "manifest.json",
            "metadata.json",
            "payload",
        ]
        assert (
            len(
                [
                    item
                    for item in stores.hierarchy._revisions.values()
                    if item.dataset_id == UUID(dataset)
                ]
            )
            == 1
        )


def test_metadata_retry_conflicts_before_and_after_publication(
    client: TestClient, stores: ApiStores, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A persisted intent refuses a different metadata command without altering its bytes."""
    ingest = IngestClient(client)
    _, dataset = ingest.developer_dataset()
    verified = _verified(ingest, dataset)
    session_id = UUID(str(verified["id"]))
    with monkeypatch.context() as patch:
        crash_on(patch, "fsync")
        assert (
            ingest.commit(str(session_id), int(str(verified["etag"])), _METADATA).status_code == 500
        )
    original = stores.hierarchy._intents[session_id]
    for published in (False, True):
        if published:
            current = stores.hierarchy._sessions[session_id]
            assert ingest.commit(str(session_id), current.etag, _METADATA).status_code == 201
        current = stores.hierarchy._sessions[session_id]
        conflict = ingest.commit(str(session_id), current.etag, {**_METADATA, "title": "Changed"})
        assert conflict.status_code == 409, conflict.text
        assert stores.hierarchy._intents[session_id] == original


@pytest.mark.parametrize("name", ["COMMITTED", "manifest.json", "metadata.json", "payload/a.bin"])
def test_a_retry_refuses_modified_final_evidence(
    client: TestClient, stores: ApiStores, name: str
) -> None:
    """A named marker alone never makes an altered final envelope a successful replay."""
    ingest = IngestClient(client)
    _, dataset = ingest.developer_dataset()
    verified = _verified(ingest, dataset)
    session_id = str(verified["id"])
    result = ingest.commit(session_id, int(str(verified["etag"])), _METADATA)
    assert result.status_code == 201
    record = stores.hierarchy._revisions[UUID(result.json()["id"])]
    target = Path(record.revision_path) / name
    target.chmod(0o600)
    target.write_bytes(b"corrupt")
    target.chmod(0o444)
    response = ingest.commit(
        session_id, stores.hierarchy._sessions[UUID(session_id)].etag, _METADATA
    )
    assert response.status_code == 500, response.text


async def test_a_late_part_receipt_preserves_a_completed_file(
    client: TestClient, stores: ApiStores, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A part driver holding a stale ledger returns the winner without regressing COMPLETE."""
    monkeypatch.setattr(ingest_module, "PART_BYTES", 4)
    ingest = IngestClient(client)
    _, dataset = ingest.developer_dataset()
    data = b"abcdefgh"
    session = ingest.create(dataset, [manifest_file("payload/a.bin", data)]).json()
    file_id = UUID(session["files"][0]["file_id"])
    persisted = await stores.hierarchy.ingest_session(UUID(session["id"]))
    service = IngestService(
        PosixRawStore(str(tmp_path / "data")),
        stores.hierarchy,
        clock=FakeClock(persisted.lease.expires_at - timedelta(seconds=1)),
    )
    stale_ledger, stale_file = await service.entry(file_id)
    for part in (1, 2):
        assert (
            ingest.put_part(str(file_id), part, data[(part - 1) * 4 : part * 4]).status_code == 200
        )
    assert ingest.complete(str(file_id)).status_code == 200
    winner = (await stores.hierarchy.ingest_file(file_id)).file
    result = await service.receive_part(
        stale_ledger, stale_file, 1, iter([b"xxxx"]), content_length=4
    )
    assert result == winner
    assert result.state is FileState.COMPLETE
    assert (await stores.hierarchy.ingest_file(file_id)).file == winner
    verified = ingest.verify(session["id"]).json()
    committed = ingest.commit(session["id"], verified["etag"], _METADATA)
    assert committed.status_code == 201, committed.text
    assert ingest.download(committed.json()["id"], "payload/a.bin").content == data


@pytest.mark.parametrize("error, checkpoint", [(errno.ENOENT, 1), (errno.EEXIST, 4)])
def test_publication_rechecks_final_evidence_after_a_filesystem_race(
    client: TestClient,
    stores: ApiStores,
    monkeypatch: pytest.MonkeyPatch,
    error: int,
    checkpoint: int,
) -> None:
    """A missing or conflicting publication path never substitutes for verified final evidence."""
    ingest = IngestClient(client)
    _, dataset = ingest.developer_dataset()
    verified = _verified(ingest, dataset)
    session_id = UUID(str(verified["id"]))
    with monkeypatch.context() as patch:
        # Open the session root, completion and envelope directories, then
        # exclusively create the first document candidate.
        calls = crash_on(patch, "open", call=checkpoint, errno_=error)
        result = ingest.commit(str(session_id), int(str(verified["etag"])), _METADATA)
        assert len(calls) >= checkpoint
    assert result.status_code == 500, result.text
    assert stores.hierarchy._sessions[session_id].state is IngestState.COMMITTING
    assert not stores.hierarchy._revisions
    frozen = stores.hierarchy._intents[session_id]
    retried = ingest.commit(str(session_id), stores.hierarchy._sessions[session_id].etag, _METADATA)
    assert retried.status_code == 201, retried.text
    final = Path(stores.hierarchy._revisions[UUID(retried.json()["id"])].revision_path)
    assert {name: (final / name).read_bytes() for name in frozen.documents} == frozen.documents
    assert ingest.download(retried.json()["id"], "payload/a.bin").content == _DATA
    assert len(stores.hierarchy._revisions) == 1


def test_recovery_fences_a_commit_driver_after_the_final_rename(
    client: TestClient, stores: ApiStores, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A driver that loses ownership after publication cannot record a revision or its events."""
    ingest = IngestClient(client)
    _, dataset = ingest.developer_dataset()
    verified = _verified(ingest, dataset)
    session_id = UUID(str(verified["id"]))
    original = os.fchmod
    published: list[Path] = []

    async def recover() -> None:
        current = await stores.hierarchy.ingest_session(session_id)
        async with stores.hierarchy.transaction() as writer:
            await writer.update_ingest_session(current.recover(), expected_etag=current.etag)

    def fence_after_rename(descriptor: int, mode: int) -> None:
        original(descriptor, mode)
        identity = os.fstat(descriptor)
        targets = list((tmp_path / "data").rglob("000001--*"))
        if targets and targets[0].stat().st_ino == identity.st_ino and not published:
            published.append(targets[0])
            assert client.portal is not None
            client.portal.call(recover)

    with monkeypatch.context() as patch:
        patch.setattr(os, "fchmod", fence_after_rename)
        result = ingest.commit(str(session_id), int(str(verified["etag"])), _METADATA)
    assert result.status_code == 412, result.text
    assert result.json()["code"] == "PRECONDITION_FAILED"
    assert len(published) == 1
    frozen = stores.hierarchy._intents[session_id]
    assert {
        name: (published[0] / name).read_bytes() for name in frozen.documents
    } == frozen.documents
    assert (published[0] / "payload/a.bin").read_bytes() == _DATA
    assert stores.hierarchy._sessions[session_id].state is IngestState.RECOVERING
    assert not stores.hierarchy._revisions
    assert not any(event.kind == "revision.committed" for event in stores.hierarchy._audit)
    assert not any(event.kind == "revision.committed" for event in stores.hierarchy._outbox)
