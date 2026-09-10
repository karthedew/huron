"""``IngestSession``'s named operations enforce the transition table and the lease.

Every operation below moves the session along an edge :data:`TRANSITIONS`
allows, refusing a lapsed lease with ``IngestSessionExpired`` and a state
the table has no edge for with ``IllegalIngestTransition`` - a terminal
session always refuses with the latter, even past its lease, because that
names the real reason. ``renew`` is the one operation that touches only the
lease, never a state edge.

The rest of this module pins the per-file ledger (:class:`IngestFile`), the
upload plan (:func:`compute_upload_plan`), and the two factories a commit
publishes through (:func:`revision_record`, :func:`revision_committed`):
what a file's part-by-part progress proves, what a whole-file observation is
checked against, which files a revision can hard-link from its parent
instead of uploading, and what a COMMITTING session hands off once its
commit lands.
"""

from __future__ import annotations

import hashlib
from datetime import timedelta
from uuid import uuid4

import pytest

from huron.pkg.catalog.errors import IllegalIngestTransition, IngestSessionExpired, ManifestMismatch
from huron.pkg.catalog.ingest import (
    LEASE_TTL,
    PART_BYTES,
    TRANSITIONS,
    FileState,
    IngestState,
    compute_upload_plan,
    revision_committed,
    revision_record,
)
from huron.pkg.catalog.manifest import Manifest, ManifestEntry
from huron.pkg.catalog.models import RevisionRecord

from .support import (
    INGEST_NOW,
    INGEST_OPERATION_TARGETS,
    ingest_file,
    ingest_session,
    run_ingest_operation,
)

pytestmark = pytest.mark.unit

_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


def _entry(
    path: str = "payload/a.bin",
    *,
    size: int = 10,
    sha256: str = "a" * 64,
    media_type: str = "application/octet-stream",
) -> ManifestEntry:
    """Build a manifest entry, defaulting to one small unremarkable file."""
    return ManifestEntry(path=path, size=size, sha256=sha256, media_type=media_type)


@pytest.mark.parametrize("state", list(IngestState))
@pytest.mark.parametrize("operation", sorted(INGEST_OPERATION_TARGETS))
def test_every_operation_from_every_state_matches_the_transition_table(
    operation: str, state: IngestState
) -> None:
    """Each named operation succeeds exactly where the transition table has an edge."""
    session = ingest_session(state, expires_in=timedelta(hours=1))
    target = INGEST_OPERATION_TARGETS[operation]

    if target in TRANSITIONS[state]:
        moved = run_ingest_operation(session, operation, now=INGEST_NOW)
        assert moved.state is target
        assert moved.etag == session.etag + 1
    else:
        with pytest.raises(IllegalIngestTransition):
            run_ingest_operation(session, operation, now=INGEST_NOW)


def test_a_committing_session_refuses_abort_and_expire() -> None:
    """A COMMITTING session can be aborted by neither the owner nor the expiry sweep."""
    session = ingest_session(IngestState.COMMITTING, expires_in=timedelta(seconds=-1))

    with pytest.raises(IllegalIngestTransition):
        session.abort()
    with pytest.raises(IllegalIngestTransition):
        session.expire(now=INGEST_NOW)


def test_abort_and_fail_ignore_a_lapsed_lease() -> None:
    """A session past its lease can still be aborted or failed; neither consults the lease."""
    lapsed = ingest_session(IngestState.UPLOADING, expires_in=timedelta(seconds=-1))

    assert lapsed.abort().state is IngestState.ABORTED
    assert lapsed.fail().state is IngestState.FAILED


def test_commit_ignores_a_lapsed_lease() -> None:
    """A COMMITTING session past its lease still commits: storage has already led."""
    lapsed = ingest_session(IngestState.COMMITTING, expires_in=timedelta(seconds=-1))

    committed = lapsed.commit()

    assert committed.state is IngestState.COMMITTED
    assert committed.etag == lapsed.etag + 1


def test_begin_commit_re_entry_from_committing_ignores_a_lapsed_lease() -> None:
    """A lapsed COMMITTING session still re-enters COMMITTING: the etag fences it, not the lease."""
    lapsed = ingest_session(IngestState.COMMITTING, expires_in=timedelta(seconds=-1))

    reentered = lapsed.begin_commit(manifest_sha256=lapsed.manifest_sha256, now=INGEST_NOW)

    assert reentered.state is IngestState.COMMITTING
    assert reentered.etag == lapsed.etag + 1


@pytest.mark.parametrize(
    ("state", "operation"),
    [
        (IngestState.PREPARING, "open"),
        (IngestState.PREPARING, "begin_commit"),
        (IngestState.UPLOADING, "verify"),
        (IngestState.UPLOADING, "begin_commit"),
        (IngestState.VERIFYING, "begin_commit"),
    ],
)
def test_forward_edges_refuse_a_lapsed_lease(state: IngestState, operation: str) -> None:
    """A forward edge refuses once the session driving it has let its lease lapse."""
    session = ingest_session(state, expires_in=timedelta(seconds=-1))

    with pytest.raises(IngestSessionExpired):
        run_ingest_operation(session, operation, now=INGEST_NOW)


@pytest.mark.parametrize("operation", sorted(INGEST_OPERATION_TARGETS))
def test_terminal_sessions_refuse_with_the_transition_error_even_when_lapsed(
    operation: str,
) -> None:
    """A lapsed, terminal session is refused for the real reason, never as merely expired."""
    session = ingest_session(IngestState.COMMITTED, expires_in=timedelta(seconds=-1))

    with pytest.raises(IllegalIngestTransition):
        run_ingest_operation(session, operation, now=INGEST_NOW)


def test_renew_moves_the_expiry_and_leaves_the_etag() -> None:
    """A live session's renewal pushes its lease out without bumping the etag or state."""
    session = ingest_session(IngestState.UPLOADING, expires_in=timedelta(hours=1))

    renewed = session.renew(now=INGEST_NOW, ttl=timedelta(hours=3))

    assert renewed.lease.expires_at == INGEST_NOW + timedelta(hours=3)
    assert renewed.etag == session.etag
    assert renewed.state is session.state


def test_renew_without_a_ttl_uses_the_default_lease_duration() -> None:
    """Renewing without a ttl extends the lease by the module's default duration."""
    session = ingest_session(IngestState.UPLOADING, expires_in=timedelta(hours=1))

    renewed = session.renew(now=INGEST_NOW)

    assert renewed.lease.expires_at == INGEST_NOW + LEASE_TTL


def test_renew_refuses_at_the_expiry_instant_and_after_and_when_terminal() -> None:
    """Renewal refuses at the lease's expiry instant, past it, and for a terminal session."""
    at_expiry = ingest_session(IngestState.UPLOADING, expires_in=timedelta(0))
    past_expiry = ingest_session(IngestState.UPLOADING, expires_in=timedelta(seconds=-1))
    terminal = ingest_session(IngestState.COMMITTED, expires_in=timedelta(hours=1))

    with pytest.raises(IngestSessionExpired):
        at_expiry.renew(now=INGEST_NOW)
    with pytest.raises(IngestSessionExpired):
        past_expiry.renew(now=INGEST_NOW)
    with pytest.raises(IngestSessionExpired):
        terminal.renew(now=INGEST_NOW)


def test_require_refuses_another_state_and_a_lapsed_lease() -> None:
    """``require`` accepts a live session in the named state and refuses every other case."""
    live = ingest_session(IngestState.UPLOADING, expires_in=timedelta(hours=1))
    assert live.require(IngestState.UPLOADING, now=INGEST_NOW) is None

    wrong_state = ingest_session(IngestState.VERIFYING, expires_in=timedelta(hours=1))
    with pytest.raises(IllegalIngestTransition):
        wrong_state.require(IngestState.UPLOADING, now=INGEST_NOW)

    lapsed = ingest_session(IngestState.UPLOADING, expires_in=timedelta(seconds=-1))
    with pytest.raises(IngestSessionExpired):
        lapsed.require(IngestState.UPLOADING, now=INGEST_NOW)


def test_expire_aborts_a_lapsed_session_and_refuses_a_live_one() -> None:
    """The sweep's ``expire`` aborts a lapsed session and refuses to touch a live one."""
    lapsed = ingest_session(IngestState.UPLOADING, expires_in=timedelta(seconds=-1))
    live = ingest_session(IngestState.UPLOADING, expires_in=timedelta(hours=1))

    expired = lapsed.expire(now=INGEST_NOW)

    assert expired.state is IngestState.ABORTED
    assert expired.etag == lapsed.etag + 1
    with pytest.raises(ValueError, match="has not lapsed"):
        live.expire(now=INGEST_NOW)


def test_verify_refuses_while_any_file_is_pending() -> None:
    """Verifying refuses while any planned file is still pending, naming every one."""
    session = ingest_session(IngestState.UPLOADING, expires_in=timedelta(hours=1))
    files = (
        ingest_file(path="payload/a.bin", state=FileState.COMPLETE),
        ingest_file(path="payload/b.bin", state=FileState.PENDING),
        ingest_file(path="payload/c.bin", state=FileState.PENDING),
    )

    with pytest.raises(ManifestMismatch) as excinfo:
        session.verify(files, now=INGEST_NOW)

    assert excinfo.value.context == {"incomplete": ["payload/b.bin", "payload/c.bin"]}


def test_verify_refuses_an_empty_ledger() -> None:
    """Verifying a session with no planned files at all is refused outright."""
    session = ingest_session(IngestState.UPLOADING, expires_in=timedelta(hours=1))

    with pytest.raises(ValueError, match="no planned files"):
        session.verify((), now=INGEST_NOW)


def test_begin_commit_refuses_a_different_manifest_digest() -> None:
    """Committing under a manifest digest other than the one declared is refused."""
    session = ingest_session(IngestState.VERIFYING, expires_in=timedelta(hours=1))

    with pytest.raises(ManifestMismatch):
        session.begin_commit(manifest_sha256="b" * 64, now=INGEST_NOW)

    assert session.state is IngestState.VERIFYING


def test_part_received_records_the_part_and_is_idempotent() -> None:
    """A part not yet held is added to the ledger; requesting it again changes nothing."""
    file = ingest_file(part_count=1)

    once = file.part_received(1)
    twice = once.part_received(1)

    assert once.completed_parts == frozenset({1})
    assert twice.completed_parts == frozenset({1})
    assert twice.received is True


def test_part_received_refuses_a_part_outside_the_plan_a_hardlink_file_and_a_complete_file() -> (
    None
):
    """A part outside the plan is a caller bug; a hardlink or already-complete file refuses one."""
    file = ingest_file(part_count=2)
    with pytest.raises(ValueError, match=r"\b0\b"):
        file.part_received(0)
    with pytest.raises(ValueError, match=r"\b3\b"):
        file.part_received(3)

    complete = ingest_file(part_count=1, state=FileState.COMPLETE, completed_parts=frozenset({1}))
    with pytest.raises(IllegalIngestTransition):
        complete.part_received(1)


def test_completed_refuses_before_every_part_has_arrived() -> None:
    """A file with parts still outstanding cannot be proven complete."""
    file = ingest_file(part_count=2).part_received(1)

    with pytest.raises(IllegalIngestTransition):
        file.completed(observed_size=file.size, observed_sha256=file.expected_sha256)


def test_completed_marks_a_matching_observation_complete() -> None:
    """A matching whole-file observation completes the file and keeps its recorded parts."""
    file = ingest_file(size=10, expected_sha256="a" * 64, part_count=1).part_received(1)

    completed = file.completed(observed_size=10, observed_sha256="a" * 64)

    assert completed.state is FileState.COMPLETE
    assert completed.completed_parts == frozenset({1})


@pytest.mark.parametrize(
    ("observed_size", "observed_sha256"),
    [
        pytest.param(11, "a" * 64, id="size_only"),
        pytest.param(10, "b" * 64, id="digest_only"),
        pytest.param(11, "b" * 64, id="both"),
    ],
)
def test_completed_refuses_a_size_or_digest_mismatch_with_the_observation_in_context(
    observed_size: int, observed_sha256: str
) -> None:
    """A mismatch in the size alone, the digest alone, or both is refused with both in context."""
    file = ingest_file(size=10, expected_sha256="a" * 64, part_count=1).part_received(1)

    with pytest.raises(ManifestMismatch) as excinfo:
        file.completed(observed_size=observed_size, observed_sha256=observed_sha256)

    assert excinfo.value.context == {
        "path": file.path,
        "expected_size": 10,
        "observed_size": observed_size,
        "expected_sha256": "a" * 64,
        "observed_sha256": observed_sha256,
    }


def test_a_zero_byte_file_is_one_part_that_completes_on_the_empty_digest() -> None:
    """A zero-byte manifest entry plans as one part that completes on the empty-string digest."""
    manifest = Manifest((_entry("payload/empty.bin", size=0, sha256=_EMPTY_SHA256),))

    plan = compute_upload_plan(manifest)

    assert plan[0].part_count == 1

    file = ingest_file(
        path="payload/empty.bin", size=0, expected_sha256=_EMPTY_SHA256, part_count=1
    )
    completed = file.part_received(1).completed(observed_size=0, observed_sha256=_EMPTY_SHA256)

    assert completed.state is FileState.COMPLETE


def test_upload_plan_part_counts_follow_the_part_size() -> None:
    """Part counts follow ``ceil(size / part_bytes)``, floored at one, and zero for a hardlink."""
    nine_gib = 9 * 1024**3
    manifest = Manifest(
        (
            _entry("payload/a.bin", size=nine_gib),
            _entry("payload/b.bin", size=PART_BYTES),
            _entry("payload/c.bin", size=PART_BYTES + 1),
            _entry("payload/d.bin", size=0, sha256=_EMPTY_SHA256),
        )
    )

    plan = {entry.file.path: entry.part_count for entry in compute_upload_plan(manifest)}

    assert plan == {
        "payload/a.bin": 144,
        "payload/b.bin": 1,
        "payload/c.bin": 2,
        "payload/d.bin": 1,
    }
    with pytest.raises(ValueError, match="positive"):
        compute_upload_plan(manifest, part_bytes=0)


@pytest.mark.parametrize("recovering", [False, True])
def test_revision_record_takes_every_column_from_the_session_and_manifest(recovering: bool) -> None:
    """A revision record's every field traces to the session, the manifest or a given value."""
    manifest = Manifest((_entry("payload/a.bin", size=10, sha256="a" * 64),))
    session = ingest_session(
        IngestState.COMMITTING, expires_in=timedelta(hours=1), manifest_sha256=manifest.sha256
    )
    if recovering:
        session = session.recover()

    record = revision_record(
        session,
        manifest,
        metadata_sha256="c" * 64,
        revision_path="orgs/o--org/projects/p--proj/datasets/d--data/raw/1--rev",
        committed_by="user:alice",
        committed_at=INGEST_NOW,
    )

    assert record.id == session.lease.revision_id
    assert record.dataset_id == session.lease.dataset_id
    assert record.number == session.lease.revision_number
    assert record.manifest_sha256 == manifest.sha256
    assert record.metadata_sha256 == "c" * 64
    assert record.revision_path == "orgs/o--org/projects/p--proj/datasets/d--data/raw/1--rev"
    assert record.committed_by == "user:alice"
    assert record.committed_at == INGEST_NOW
    assert record.file_count == len(manifest.files)
    assert record.total_bytes == manifest.total_bytes


def test_revision_record_refuses_a_foreign_manifest_or_a_session_not_committing() -> None:
    """A revision record refuses a foreign manifest or a session not COMMITTING."""
    manifest = Manifest((_entry("payload/a.bin", size=10, sha256="a" * 64),))
    foreign_manifest = Manifest((_entry("payload/b.bin", size=20, sha256="b" * 64),))
    committing = ingest_session(
        IngestState.COMMITTING, expires_in=timedelta(hours=1), manifest_sha256=manifest.sha256
    )
    verifying = ingest_session(
        IngestState.VERIFYING, expires_in=timedelta(hours=1), manifest_sha256=manifest.sha256
    )

    with pytest.raises(ValueError, match="does not match"):
        revision_record(
            committing,
            foreign_manifest,
            metadata_sha256="c" * 64,
            revision_path="r",
            committed_by="user:alice",
            committed_at=INGEST_NOW,
        )
    with pytest.raises(ValueError, match="committing or recovering"):
        revision_record(
            verifying,
            manifest,
            metadata_sha256="c" * 64,
            revision_path="r",
            committed_by="user:alice",
            committed_at=INGEST_NOW,
        )


def test_revision_committed_event_carries_the_revision_identity() -> None:
    """The outbox event names its kind, subject and every identity field of the revision."""
    record = RevisionRecord(
        id=uuid4(),
        dataset_id=uuid4(),
        number=3,
        manifest_sha256="a" * 64,
        metadata_sha256="b" * 64,
        revision_path="orgs/o--org/projects/p--proj/datasets/d--data/raw/3--rev",
        committed_by="user:alice",
        committed_at=INGEST_NOW,
        file_count=1,
        total_bytes=10,
    )
    event_id = uuid4()

    event = revision_committed(record, event_id=event_id, created_at=INGEST_NOW)

    assert event.id == event_id
    assert event.kind == "revision.committed"
    assert event.subject_id == record.id
    assert event.created_at == INGEST_NOW
    assert event.payload == {
        "revision_id": str(record.id),
        "dataset_id": str(record.dataset_id),
        "revision_number": record.number,
        "manifest_sha256": record.manifest_sha256,
        "revision_path": record.revision_path,
    }
