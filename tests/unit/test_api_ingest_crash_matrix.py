"""A fault at each on-disk step of a commit leaves one named state, and a retry recovers.

The publication a commit performs - documents, seal, marker, one rename,
one short transaction, a best-effort index - has one distinct outcome per
step a crash can land on: some leave the session terminal with the number
freed for a fresh attempt, one leaves it recoverable by a plain retry
because storage has already moved past the point where the client's own
attempt still mattered, and one leaves the commit already returned to the
client with only a best-effort side effect missing. This module pins that
outcome for every named step, plus the case where the process itself is
killed - no handler runs at all - between the fence into COMMITTING and
the first document write.

A step indexed by an ``os.fsync`` call number cannot be targeted by its
path directly, because :func:`~tests.unit.support.crash_on` and
:func:`~tests.unit.support.fsync_log` both patch ``os.fsync`` and would
otherwise collide. Such a row first rehearses an equivalent commit - same
manifest shape, a sibling dataset - under ``fsync_log`` to learn which
numbered call the step of interest is, then applies ``crash_on`` with that
number against the real attempt in a fresh patch of its own.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from functools import partial
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from huron.pkg.catalog.documents import CommitRecord
from huron.pkg.catalog.ingest import IngestState
from huron.pkg.catalog.paths import revision_dir, staging_dir
from huron.pkg.rawstore import PosixRawStore
from huron.service.api.app import create_app
from huron.service.api.settings import ApiSettings, ClassificationValue
from tests.ingest_client import IngestClient, manifest_file
from tests.unit.support import crash_on, fsync_log, memory_stores

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Iterator

    from httpx import Response

    from huron.pkg.catalog.models import RevisionRecord
    from huron.service.api.runtime import ApiStores
    from huron.service.api.stores.ports import HierarchyWriter

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


def _revisions_for(stores: ApiStores, dataset_id: str) -> list[RevisionRecord]:
    """Return every revision the in-memory store currently holds for one dataset.

    Args:
        stores: The store bundle backing the app under test.
        dataset_id: The dataset to filter revisions by.

    Returns:
        The matching revisions, in whatever order the store's dict yields.
    """
    return [
        record
        for record in stores.hierarchy._revisions.values()
        if record.dataset_id == UUID(dataset_id)
    ]


def _crash_on_manifest_replace(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    stores: ApiStores,
    tmp_path: Path,
    project_id: str,
) -> None:
    """Crash the manifest document's own replace, before it lands."""
    crash_on(monkeypatch, "replace", call=1)


def _crash_on_metadata_replace(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    stores: ApiStores,
    tmp_path: Path,
    project_id: str,
) -> None:
    """Crash the metadata document's own replace, after the manifest's has landed."""
    crash_on(monkeypatch, "replace", call=2)


def _crash_during_seal(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    stores: ApiStores,
    tmp_path: Path,
    project_id: str,
) -> None:
    """Crash the first permission change sealing makes, before any mode moves."""
    crash_on(monkeypatch, "chmod", call=1)


def _crash_on_marker_replace(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    stores: ApiStores,
    tmp_path: Path,
    project_id: str,
) -> None:
    """Crash the COMMITTED marker's own replace, after sealing has finished."""
    crash_on(monkeypatch, "replace", call=3)


def _crash_during_the_tree_fsync(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    stores: ApiStores,
    tmp_path: Path,
    project_id: str,
) -> None:
    """Crash while flushing the payload to disk, before any rename is attempted.

    A rehearsal commit of the same shape, in a sibling dataset, is driven
    to completion under a durability trace so the numbered ``os.fsync``
    call that first touches the payload once the marker is already
    durable can be found by the paths it fsyncs; the same call number
    then targets the real attempt, because the two commits share one
    manifest shape and so one fsync sequence.
    """
    rehearsal = IngestClient(client, subject="bob")
    rehearsal_dataset_id = _second_dataset(client, project_id, "rehearsal-fsync")
    session = rehearsal.create(rehearsal_dataset_id, [manifest_file("payload/a.bin", _DATA)]).json()
    rehearsal.put_part(session["files"][0]["file_id"], 1, _DATA)
    verified = rehearsal.verify(session["id"]).json()
    staging = Path(staging_dir(PurePosixPath(str(tmp_path / "data")), UUID(session["id"])))
    with monkeypatch.context() as rehearsal_patch:
        log = fsync_log(rehearsal_patch)
        committed = rehearsal.commit(
            session["id"], verified["etag"], {"title": "Rehearsal", "creators": ["bob"]}
        )
        assert committed.status_code == 201, committed.text

        marker_index = log.index(staging / "COMMITTED")
        payload_root = staging / "payload"
        payload_index = next(
            index
            for index, path in enumerate(log)
            if index > marker_index and payload_root in path.parents
        )
        call = payload_index + 1
    crash_on(monkeypatch, "fsync", call=call)


def _crash_on_rename(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    stores: ApiStores,
    tmp_path: Path,
    project_id: str,
) -> None:
    """Crash during the envelope's rename, before anything is published."""
    crash_on(monkeypatch, "rename", call=1)


def _crash_after_the_rename(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    stores: ApiStores,
    tmp_path: Path,
    project_id: str,
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


def _crash_in_the_commit_transaction(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    stores: ApiStores,
    tmp_path: Path,
    project_id: str,
) -> None:
    """Raise once from the in-memory writer's outbox insert, rolling back the whole transaction."""
    hierarchy = stores.hierarchy
    real_transaction = type(hierarchy).transaction
    raised = False

    class _OutboxFailingWriter:
        """A transaction writer that delegates everything except one poisoned outbox insert."""

        def __init__(self, inner: HierarchyWriter) -> None:
            """Wrap ``inner``, keeping every write except the first outbox insert.

            Args:
                inner: The real writer this one delegates every write to,
                    except the one poisoned ``insert_outbox_event`` call.
            """
            self._inner = inner

        def __getattr__(self, name: str) -> object:
            """Delegate any write this wrapper does not override to the real writer.

            Args:
                name: The attribute being looked up.

            Returns:
                The corresponding attribute of the wrapped writer.
            """
            return getattr(self._inner, name)

        async def insert_outbox_event(self, event: object) -> None:
            """Raise once, then delegate to the real writer on every later call.

            Args:
                event: The outbox row the caller tried to insert.

            Raises:
                RuntimeError: The first time this is called.
            """
            nonlocal raised
            if not raised:
                raised = True
                raise RuntimeError("outbox insert injected failure")
            await self._inner.insert_outbox_event(event)

    @asynccontextmanager
    async def _transaction() -> AsyncIterator[HierarchyWriter]:
        """Open the real transaction, yielding a writer that poisons one outbox insert.

        Yields:
            A writer that behaves like the real one except for its first
            ``insert_outbox_event`` call.
        """
        async with real_transaction(hierarchy) as writer:
            yield _OutboxFailingWriter(writer)

    monkeypatch.setattr(hierarchy, "transaction", _transaction)


def _crash_writing_the_index(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    stores: ApiStores,
    tmp_path: Path,
    project_id: str,
) -> None:
    """Fail the best-effort index write only, leaving every earlier step untouched."""
    real_replace = PosixRawStore.atomic_replace

    def _broken_replace(self: PosixRawStore, path: Path, payload: bytes, **kwargs: object) -> None:
        """Raise for the index file only, delegating every other replace unchanged.

        Args:
            self: The store the call was made on.
            path: The file being replaced.
            payload: The complete new content.
            **kwargs: Any further keyword arguments, forwarded unchanged.

        Raises:
            OSError: If ``path`` names ``INDEX.json``.
        """
        if Path(path).name == "INDEX.json":
            raise OSError("index write injected failure")
        real_replace(self, path, payload, **kwargs)

    monkeypatch.setattr(PosixRawStore, "atomic_replace", _broken_replace)


@dataclass(frozen=True, slots=True)
class _CrashContext:
    """Everything one crash row's assertion needs once the crashed commit has returned.

    Attributes:
        client: The dev-header client the whole test drives.
        ingest: The client wrapping ``client`` as the subject that opened
            the session.
        stores: The in-memory store bundle backing the app.
        dataset_id: The dataset the session belongs to.
        session_id: The session under test.
        staging: The envelope's staging directory.
        final: The revision directory the envelope publishes as.
        metadata: The metadata submission the crashed commit carried.
        crashed: The crashed commit's HTTP response.
        reserved_revision_id: The revision id the session's lease
            reserved, whether or not it is ever published.
        original_manifest_bytes: The manifest document's bytes as
            ``create`` first wrote them.
        original_manifest_ino: The manifest document's inode number as
            ``create`` first wrote it, before the crashed commit ran.
    """

    client: TestClient
    ingest: IngestClient
    stores: ApiStores
    dataset_id: str
    session_id: UUID
    staging: Path
    final: Path
    metadata: dict[str, object]
    crashed: Response
    reserved_revision_id: str
    original_manifest_bytes: bytes
    original_manifest_ino: int


def _assert_fails_and_a_retry_retakes_the_number(
    ctx: _CrashContext, *, disk: Callable[[_CrashContext], None]
) -> None:
    """A crash before the rename fails the session outright and frees its number for a retry.

    Args:
        ctx: The crashed attempt's context.
        disk: The row's own check of what remains in the unpublished
            staging envelope.
    """
    assert ctx.crashed.status_code == 500
    assert not ctx.final.exists()
    assert ctx.staging.is_dir()
    disk(ctx)

    after_crash = ctx.ingest.get(str(ctx.session_id)).json()
    assert after_crash["state"] == "FAILED"
    assert "ingest.failed" in [event.kind for event in ctx.stores.hierarchy._audit]

    missing = ctx.client.get(
        f"/api/v1/revisions/{ctx.reserved_revision_id}", headers=_headers(ctx.ingest.subject)
    )
    assert missing.status_code == 404
    assert not _revisions_for(ctx.stores, ctx.dataset_id)

    retry = ctx.ingest.create(ctx.dataset_id, [manifest_file("payload/b.bin", _DATA)])
    assert retry.status_code == 201, retry.text
    assert retry.json()["revision_number"] == 1


def _manifest_untouched(ctx: _CrashContext) -> None:
    """The manifest document's own replace never landed; its create-time bytes survive."""
    assert (ctx.staging / "manifest.json").stat().st_ino == ctx.original_manifest_ino
    assert (ctx.staging / "manifest.json").read_bytes() == ctx.original_manifest_bytes
    assert not (ctx.staging / "metadata.json").exists()


def _manifest_rewritten_no_metadata(ctx: _CrashContext) -> None:
    """The manifest document's replace landed; the metadata document's did not."""
    assert (ctx.staging / "manifest.json").stat().st_ino != ctx.original_manifest_ino
    assert (ctx.staging / "manifest.json").read_bytes() == ctx.original_manifest_bytes
    assert not (ctx.staging / "metadata.json").exists()


def _documents_present_payload_unsealed(ctx: _CrashContext) -> None:
    """Both documents are written; sealing has not changed a single mode yet."""
    assert (ctx.staging / "manifest.json").is_file()
    assert (ctx.staging / "metadata.json").is_file()
    payload = ctx.staging / "payload" / "a.bin"
    assert payload.stat().st_mode & 0o777 == 0o600


def _sealed_with_no_marker(ctx: _CrashContext) -> None:
    """Sealing finished; the COMMITTED marker's own replace never landed."""
    payload = ctx.staging / "payload" / "a.bin"
    assert payload.stat().st_mode & 0o777 == 0o444
    assert (ctx.staging / "payload").stat().st_mode & 0o777 == 0o555
    assert ctx.staging.stat().st_mode & 0o777 == 0o700
    assert not (ctx.staging / "COMMITTED").exists()


def _marker_present_no_rename(ctx: _CrashContext) -> None:
    """The marker is durable, but the fault lands before any rename is attempted."""
    assert (ctx.staging / "COMMITTED").is_file()
    assert not ctx.final.exists()


def _nothing_beyond_the_shared_check(ctx: _CrashContext) -> None:
    """The rename never starts; the shared staging/final check already proves this row."""


def _assert_publication_recovers_on_retry(ctx: _CrashContext) -> None:
    """A crash just after the rename leaves publication durable; a retry finishes the catalog."""
    assert ctx.crashed.status_code == 500
    assert not ctx.staging.exists()
    assert (ctx.final / "COMMITTED").is_file()
    stuck = ctx.stores.hierarchy._sessions[ctx.session_id]
    assert stuck.state.value == "COMMITTING"

    retried = ctx.ingest.commit(str(ctx.session_id), stuck.etag, ctx.metadata)

    assert retried.status_code == 201, retried.text
    assert ctx.final.stat().st_mode & 0o777 == 0o555
    body = retried.json()
    marker = CommitRecord.decode((ctx.final / "COMMITTED").read_bytes())
    assert body["committed_at"] == marker.committed_at.isoformat().replace("+00:00", "Z")
    assert body["metadata_sha256"] == marker.metadata_sha256
    assert body["committed_by"] == marker.committed_by
    assert len(_revisions_for(ctx.stores, ctx.dataset_id)) == 1


def _assert_transaction_rolled_back_and_a_retry_finishes(ctx: _CrashContext) -> None:
    """A crash inside the recording transaction rolls it back whole; a retry finishes it."""
    assert ctx.crashed.status_code == 500
    assert not ctx.staging.exists()
    assert ctx.final.is_dir()
    assert ctx.final.stat().st_mode & 0o777 == 0o555
    stuck = ctx.stores.hierarchy._sessions[ctx.session_id]
    assert stuck.state.value == "COMMITTING"
    assert not _revisions_for(ctx.stores, ctx.dataset_id)
    assert not any(event.kind == "revision.committed" for event in ctx.stores.hierarchy._audit)

    retried = ctx.ingest.commit(str(ctx.session_id), stuck.etag, ctx.metadata)

    assert retried.status_code == 201, retried.text
    assert len(_revisions_for(ctx.stores, ctx.dataset_id)) == 1
    assert len(ctx.stores.hierarchy._outbox) == 1


def _assert_the_index_failure_leaves_the_commit_intact(ctx: _CrashContext) -> None:
    """A best-effort index write that fails never turns an already-published commit into one."""
    assert ctx.crashed.status_code == 201, ctx.crashed.text
    assert (ctx.final / "COMMITTED").is_file()
    assert ctx.final.stat().st_mode & 0o777 == 0o555
    assert not (ctx.final.parent / "INDEX.json").exists()
    after = ctx.ingest.get(str(ctx.session_id)).json()
    assert after["state"] == "COMMITTED"
    assert len(_revisions_for(ctx.stores, ctx.dataset_id)) == 1


@dataclass(frozen=True, slots=True)
class _CrashRow:
    """One row of the commit crash matrix.

    Attributes:
        name: The row's identifier, used as the parametrization id.
        inject: Arranges the fault against the real attempt about to run.
        assert_afterwards: Checks the on-disk state, the session row and
            the retry expectation the row promises.
    """

    name: str
    inject: Callable[[pytest.MonkeyPatch, TestClient, ApiStores, Path, str], None]
    assert_afterwards: Callable[[_CrashContext], None]


_ROWS = (
    _CrashRow(
        "manifest-replace",
        _crash_on_manifest_replace,
        partial(_assert_fails_and_a_retry_retakes_the_number, disk=_manifest_untouched),
    ),
    _CrashRow(
        "metadata-replace",
        _crash_on_metadata_replace,
        partial(_assert_fails_and_a_retry_retakes_the_number, disk=_manifest_rewritten_no_metadata),
    ),
    _CrashRow(
        "seal",
        _crash_during_seal,
        partial(
            _assert_fails_and_a_retry_retakes_the_number, disk=_documents_present_payload_unsealed
        ),
    ),
    _CrashRow(
        "marker-replace",
        _crash_on_marker_replace,
        partial(_assert_fails_and_a_retry_retakes_the_number, disk=_sealed_with_no_marker),
    ),
    _CrashRow(
        "tree-fsync",
        _crash_during_the_tree_fsync,
        partial(_assert_fails_and_a_retry_retakes_the_number, disk=_marker_present_no_rename),
    ),
    _CrashRow(
        "rename",
        _crash_on_rename,
        partial(
            _assert_fails_and_a_retry_retakes_the_number, disk=_nothing_beyond_the_shared_check
        ),
    ),
    _CrashRow(
        "parent-fsync-after-rename", _crash_after_the_rename, _assert_publication_recovers_on_retry
    ),
    _CrashRow(
        "commit-transaction",
        _crash_in_the_commit_transaction,
        _assert_transaction_rolled_back_and_a_retry_finishes,
    ),
    _CrashRow(
        "index-write", _crash_writing_the_index, _assert_the_index_failure_leaves_the_commit_intact
    ),
)


@pytest.mark.parametrize("row", _ROWS, ids=lambda row: row.name)
def test_a_crash_after_each_commit_step_leaves_the_named_state_and_the_retry_converges(
    client: TestClient,
    stores: ApiStores,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    row: _CrashRow,
) -> None:
    """A fault at each on-disk commit step leaves exactly one state, and recovery converges."""
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
    staging = Path(staging_dir(PurePosixPath(str(tmp_path / "data")), UUID(session["id"])))
    metadata = {"title": "Run", "creators": ["bob"]}
    original_manifest = staging / "manifest.json"
    original_manifest_bytes = original_manifest.read_bytes()
    original_manifest_ino = original_manifest.stat().st_ino

    row.inject(monkeypatch, client, stores, tmp_path, project_id)
    crashed = ingest.commit(session["id"], verified["etag"], metadata)

    ctx = _CrashContext(
        client=client,
        ingest=ingest,
        stores=stores,
        dataset_id=dataset_id,
        session_id=UUID(session["id"]),
        staging=staging,
        final=final,
        metadata=metadata,
        crashed=crashed,
        reserved_revision_id=verified["revision_id"],
        original_manifest_bytes=original_manifest_bytes,
        original_manifest_ino=original_manifest_ino,
    )
    row.assert_afterwards(ctx)


def test_a_session_left_committing_before_the_rename_completes_on_the_next_commit(
    client: TestClient, stores: ApiStores, tmp_path: Path
) -> None:
    """A session killed right after fencing into COMMITTING still finishes on the next commit.

    No handler runs on a process kill, so the fence's own transaction can
    complete - moving the session to COMMITTING and advancing its etag -
    while nothing beyond that has happened: no document has been written
    and no rename attempted. The next ``/commit`` re-enters COMMITTING
    (the state machine's one self-loop) and runs every publishing step
    fresh, exactly as a first attempt would.
    """
    ingest = IngestClient(client)
    _, dataset_id = ingest.developer_dataset()
    session = ingest.create(dataset_id, [manifest_file("payload/a.bin", _DATA)]).json()
    ingest.put_part(session["files"][0]["file_id"], 1, _DATA)
    verified = ingest.verify(session["id"]).json()
    session_id = UUID(session["id"])

    verifying = stores.hierarchy._sessions[session_id]
    killed = replace(verifying, state=IngestState.COMMITTING, etag=verifying.etag + 1)
    stores.hierarchy._sessions[session_id] = killed

    metadata = {"title": "Run", "creators": ["bob"]}
    resumed = ingest.commit(session["id"], killed.etag, metadata)

    assert resumed.status_code == 201, resumed.text
    assert resumed.json()["number"] == 1
    final = _final_path(
        client,
        tmp_path,
        dataset_id,
        number=verified["revision_number"],
        revision_id=UUID(verified["revision_id"]),
    )
    assert (final / "manifest.json").is_file()
    assert (final / "metadata.json").is_file()
    assert (final / "COMMITTED").is_file()
    assert len(_revisions_for(stores, dataset_id)) == 1
