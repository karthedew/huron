"""Commit request operations: acceptance, entries, the final transaction and the operator exit,
on both stores."""

from dataclasses import replace
from datetime import timedelta

import pytest

from huron.core.lake.audit import Action
from huron.core.lake.collections.models import Update
from huron.core.lake.files.errors import BaseVersionConflict, CommitInvalid, FileNotRecorded
from huron.core.lake.files.models import Commit, FileRecord
from huron.core.lake.publications.errors import (
    CollectionBusy,
    CommitRequestNotFound,
    RequestIdConflict,
)
from huron.core.lake.publications.models import (
    CommitAdd,
    CommitOutcome,
    CommitRequest,
    CommitState,
    EntryAction,
    Refusal,
    Resolution,
)
from huron.core.lake.uploads.errors import IneligibleReason, UploadIneligible, UploadNotFound
from huron.core.lake.uploads.models import AttemptState
from huron.core.security.rbac import Actor, Role
from huron.pkg.errors import Conflict, Forbidden, HuronError, NotFound
from huron.pkg.identifiers import new_id
from tests.support.clock import START
from tests.support.lake import (
    CATALOG_ADMIN,
    CONTRIBUTOR,
    OTHER_CONTRIBUTOR,
    PLATFORM_ADMIN,
    STRANGER,
    VALID_METADATA,
    settled_collection,
)
from tests.support.publication import TTL, Publishing, sha256

OLD = b"the committed bytes"
NEW = b"the new bytes of it"
DIRECTORY = "helio/heliophysics/solar-wind/run7"
BLOCK = Refusal("STORAGE_FAILED", "a foreign file is at the target", {"path": "x"})


async def refused[E: HuronError](
    publishing: Publishing, actor: Actor, request: CommitRequest, error: type[E]
) -> E:
    """Submit ``request``, expect ``error``, and check that the request is saved ``rejected``
    with that refusal and that the collection stays free."""
    with pytest.raises(error) as raised:
        await publishing.publications.submit(actor, request)
    saved = await publishing.publications.status(actor, request.request_id)
    assert (saved.state, saved.refusal) == (CommitState.REJECTED, Refusal.of(raised.value))
    assert (saved.version, saved.commit_id) == (None, None)
    assert (await publishing.collection()).pending_request_id is None
    return raised.value


async def committed(publishing: Publishing) -> CommitOutcome:
    """Version 3 of the collection: ``keep.txt`` and ``a.txt`` with :data:`OLD`."""
    return await publishing.commit(CONTRIBUTOR, 2, {"keep.txt": b"kept", "a.txt": OLD})


# Acceptance.


async def test_an_accepted_request_holds_its_collection_and_its_uploads(
    publishing: Publishing,
) -> None:
    attempt = await publishing.ready(CONTRIBUTOR, "dir/new.txt", NEW)
    request = publishing.request(2, [(attempt, NEW)])
    outcome = await publishing.publications.submit(CONTRIBUTOR, request)
    assert (outcome.subject, outcome.request_id, outcome.collection_id) == (
        CONTRIBUTOR.subject,
        request.request_id,
        publishing.collection_id,
    )
    assert (outcome.body_digest, outcome.base_version, outcome.host, outcome.message) == (
        request.digest(),
        2,
        "host-1",
        "a test commit",
    )
    assert (outcome.state, outcome.created_at, outcome.updated_at) == (
        CommitState.ACCEPTED,
        START,
        START,
    )
    assert [(e.action, e.rel_path, e.upload_id) for e in await publishing.entries(outcome)] == [
        (EntryAction.MAKE_DIRECTORY, "dir", None),
        (EntryAction.ADD_FILE, "dir/new.txt", attempt.current_upload_id),
    ]
    collection = await publishing.collection()
    assert (collection.pending_request_id, collection.version) == (outcome.id, 2)
    held = await publishing.attempt(attempt)
    assert (held.state, held.commit_request_id) == (AttemptState.READY, outcome.id)
    assert await publishing.files() == {}


async def test_a_request_to_a_collection_with_a_pending_request_is_busy(
    publishing: Publishing,
) -> None:
    first = await publishing.ready(CONTRIBUTOR, "a.txt", OLD)
    pending = await publishing.publications.submit(
        CONTRIBUTOR, publishing.request(2, [(first, OLD)])
    )
    second = await publishing.ready(OTHER_CONTRIBUTOR, "b.txt", NEW)
    request = publishing.request(2, [(second, NEW)])
    with pytest.raises(CollectionBusy) as raised:
        await publishing.publications.submit(OTHER_CONTRIBUTOR, request)
    assert raised.value.context == {"collection_id": str(publishing.collection_id)}
    saved = await publishing.publications.status(OTHER_CONTRIBUTOR, request.request_id)
    assert (saved.state, saved.refusal) == (CommitState.REJECTED, Refusal.of(raised.value))
    assert (await publishing.collection()).pending_request_id == pending.id
    assert (await publishing.attempt(second)).commit_request_id is None


async def test_a_request_on_a_stale_base_version_is_rejected(publishing: Publishing) -> None:
    attempt = await publishing.ready(CONTRIBUTOR, "a.txt", OLD)
    error = await refused(
        publishing, CONTRIBUTOR, publishing.request(1, [(attempt, OLD)]), BaseVersionConflict
    )
    assert error.context == {"current_version": 2, "base_version": 1}
    assert (await publishing.attempt(attempt)).commit_request_id is None


async def test_a_request_after_a_revoked_privilege_is_rejected(publishing: Publishing) -> None:
    attempt = await publishing.ready(CONTRIBUTOR, "a.txt", OLD)
    grants = publishing.lake.grants
    await grants.set_catalog_role(
        CATALOG_ADMIN, "heliophysics", Role.READER, ["helio-readers", "helio-contributors"]
    )
    await grants.set_catalog_role(CATALOG_ADMIN, "heliophysics", Role.CONTRIBUTOR, [])
    error = await refused(
        publishing, CONTRIBUTOR, publishing.request(2, [(attempt, OLD)]), Forbidden
    )
    assert error.context["privilege"] == "COLLECTION_WRITE_FILES"
    assert (await publishing.attempt(attempt)).commit_request_id is None


async def test_a_request_to_a_draft_collection_is_rejected(publishing: Publishing) -> None:
    draft = await publishing.lake.collections.create(
        CONTRIBUTOR, "heliophysics", "solar-wind", "draft", dict(VALID_METADATA)
    )
    request = replace(publishing.request(1), collection_id=draft.collection.id)
    with pytest.raises(Conflict) as raised:
        await publishing.publications.submit(CONTRIBUTOR, request)
    assert raised.value.message == "you can commit files only to an active or incomplete collection"
    saved = await publishing.publications.status(CONTRIBUTOR, request.request_id)
    assert saved.state is CommitState.REJECTED


async def test_a_request_to_a_collection_that_the_actor_cannot_see_saves_nothing(
    publishing: Publishing,
) -> None:
    request = publishing.request(2)
    with pytest.raises(NotFound):
        await publishing.publications.submit(STRANGER, request)
    with pytest.raises(CommitRequestNotFound):
        await publishing.publications.status(STRANGER, request.request_id)


async def test_a_request_that_removes_a_file_that_is_not_recorded_is_rejected(
    publishing: Publishing,
) -> None:
    error = await refused(
        publishing, CONTRIBUTOR, publishing.request(2, removes=["ghost.txt"]), FileNotRecorded
    )
    assert error.context == {"rel_paths": ["ghost.txt"]}


async def test_a_request_with_a_bad_tree_is_rejected(publishing: Publishing) -> None:
    await committed(publishing)
    attempt = await publishing.ready(CONTRIBUTOR, "a.txt/inside", NEW)
    error = await refused(
        publishing, CONTRIBUTOR, publishing.request(3, [(attempt, NEW)]), CommitInvalid
    )
    assert error.context == {"rel_path": "a.txt/inside", "other": "a.txt"}
    assert (await publishing.attempt(attempt)).commit_request_id is None


async def test_a_request_that_names_an_unknown_or_foreign_upload_is_rejected(
    publishing: Publishing,
) -> None:
    unknown = CommitAdd("a.txt", len(NEW), sha256(NEW), new_id())
    request = replace(publishing.request(2), adds=(unknown,))
    error = await refused(publishing, CONTRIBUTOR, request, UploadNotFound)
    assert error.context == {"upload": str(unknown.upload_id)}
    foreign = await publishing.ready(OTHER_CONTRIBUTOR, "b.txt", NEW)
    await refused(publishing, CONTRIBUTOR, publishing.request(2, [(foreign, NEW)]), UploadNotFound)


async def test_a_request_that_names_an_upload_that_is_not_ready_is_rejected(
    publishing: Publishing,
) -> None:
    receiving = await publishing.receiving(CONTRIBUTOR, "a.txt", NEW)
    error = await refused(
        publishing, CONTRIBUTOR, publishing.request(2, [(receiving, NEW)]), UploadIneligible
    )
    assert error.context == {
        "upload_id": str(receiving.current_upload_id),
        "state": "receiving",
        "reason": "state",
    }
    assert error.message == (
        f"upload {receiving.current_upload_id} is receiving. A commit can publish only a ready"
        " upload. Read the upload attempt, then send the commit again with a new request ID"
    )


async def test_a_request_that_names_an_id_that_is_not_current_is_rejected(
    publishing: Publishing,
) -> None:
    first = await publishing.receiving(CONTRIBUTOR, "a.txt", NEW)
    current = await publishing.attempts.begin(
        CONTRIBUTOR, first.attempt_id, publishing.collection_id, "a.txt", len(NEW)
    )
    await publishing.seal(current, NEW)
    error = await refused(
        publishing, CONTRIBUTOR, publishing.request(2, [(first, NEW)]), UploadIneligible
    )
    assert (error.reason, error.state) == (IneligibleReason.SUPERSEDED, AttemptState.READY)


async def test_a_request_that_names_an_upload_held_by_another_request_is_rejected(
    publishing: Publishing,
) -> None:
    attempt = await publishing.ready(CONTRIBUTOR, "a.txt", NEW)
    await publishing.publications.submit(CONTRIBUTOR, publishing.request(2, [(attempt, NEW)]))
    other = await settled_collection(publishing.lake, "run8")
    request = replace(publishing.request(2, [(attempt, NEW)]), collection_id=other)
    with pytest.raises(UploadIneligible) as raised:
        await publishing.publications.submit(CONTRIBUTOR, request)
    assert raised.value.reason is IneligibleReason.HELD
    saved = await publishing.publications.status(CONTRIBUTOR, request.request_id)
    assert saved.state is CommitState.REJECTED


@pytest.mark.parametrize(
    "change",
    [
        pytest.param({"size": len(NEW) - 1}, id="size"),
        pytest.param({"sha256": sha256(b"x" * len(NEW))}, id="sha256"),
        pytest.param({"rel_path": "elsewhere.txt"}, id="path"),
    ],
)
async def test_a_request_whose_add_is_not_the_file_of_the_upload_is_rejected(
    publishing: Publishing, change: dict[str, object]
) -> None:
    attempt = await publishing.ready(CONTRIBUTOR, "a.txt", NEW)
    request = publishing.request(2, [(attempt, NEW)])
    request = replace(request, adds=(replace(request.adds[0], **change),))
    error = await refused(publishing, CONTRIBUTOR, request, UploadIneligible)
    assert error.reason is IneligibleReason.DIFFERENT_FILE


async def test_a_request_for_another_collection_than_its_upload_is_rejected(
    publishing: Publishing,
) -> None:
    attempt = await publishing.ready(CONTRIBUTOR, "a.txt", NEW)
    other = await settled_collection(publishing.lake, "run8")
    request = replace(publishing.request(2, [(attempt, NEW)]), collection_id=other)
    with pytest.raises(UploadIneligible) as raised:
        await publishing.publications.submit(CONTRIBUTOR, request)
    assert raised.value.reason is IneligibleReason.DIFFERENT_FILE


async def test_the_same_request_two_times_gets_the_saved_outcome(publishing: Publishing) -> None:
    attempt = await publishing.ready(CONTRIBUTOR, "a.txt", NEW)
    request = publishing.request(2, [(attempt, NEW)])
    first = await publishing.publications.submit(CONTRIBUTOR, request)
    publishing.clock.advance(timedelta(seconds=1))
    assert await publishing.publications.submit(CONTRIBUTOR, request) == first
    assert len(await publishing.entries(first)) == 1


async def test_a_request_id_with_another_body_is_a_conflict(publishing: Publishing) -> None:
    request = publishing.request(2)
    await publishing.publications.submit(CONTRIBUTOR, request)
    with pytest.raises(RequestIdConflict) as raised:
        await publishing.publications.submit(CONTRIBUTOR, replace(request, host="other"))
    assert raised.value.context == {"request_id": str(request.request_id)}


async def test_one_request_id_of_two_actors_is_two_requests(publishing: Publishing) -> None:
    request = publishing.request(2)
    mine = await publishing.publications.submit(CONTRIBUTOR, request)
    with pytest.raises(CollectionBusy):
        await publishing.publications.submit(OTHER_CONTRIBUTOR, request)
    assert (await publishing.publications.status(CONTRIBUTOR, request.request_id)) == mine


async def test_the_status_of_a_request_is_for_its_creator_only(publishing: Publishing) -> None:
    request = publishing.request(2)
    outcome = await publishing.publications.submit(CONTRIBUTOR, request)
    assert await publishing.publications.status(CONTRIBUTOR, request.request_id) == outcome
    with pytest.raises(CommitRequestNotFound) as raised:
        await publishing.publications.status(OTHER_CONTRIBUTOR, request.request_id)
    assert raised.value.context == {"request_id": str(request.request_id)}


async def test_the_acceptance_reads_every_recorded_file_of_a_large_collection(
    publishing: Publishing,
) -> None:
    commit_id = new_id()
    paths = [f"f{n:04}.txt" for n in range(1001)]
    async with publishing.store.transaction() as tx:
        await tx.commits.insert(
            Commit(commit_id, publishing.collection_id, 2, 3, 1001, 0, "h", None, "dave", START)
        )
        await tx.files.upsert_many(
            [
                FileRecord(publishing.collection_id, path, path, 1, "e" * 64, START, "d", commit_id)
                for path in paths
            ]
        )
        collection = await tx.collections.get(publishing.collection_id)
        assert collection is not None
        await tx.collections.update(replace(collection, version=3, file_count=1001))
    outcome = await publishing.publications.submit(
        CONTRIBUTOR, publishing.request(3, removes=[paths[-1]])
    )
    assert [(e.action, e.rel_path) for e in await publishing.entries(outcome)] == [
        (EntryAction.REMOVE_FILE, paths[-1])
    ]
    assert (await publishing.publish(outcome)).file_count == 1000


# Entries and the final transaction.


async def test_the_entries_to_do_carry_their_paths_objects_and_old_inodes(
    publishing: Publishing,
) -> None:
    await committed(publishing)
    old = (await publishing.files())["a.txt"]
    attempt = await publishing.ready(CONTRIBUTOR, "a.txt", NEW)
    outcome = await publishing.publications.submit(
        CONTRIBUTOR, publishing.request(3, [(attempt, NEW)], ["keep.txt"])
    )
    remove, add = await publishing.publications.next_entries(outcome)
    assert (remove.entry.action, remove.path, remove.old_inode, remove.source) == (
        EntryAction.REMOVE_FILE,
        f"{DIRECTORY}/keep.txt",
        (await publishing.files())["keep.txt"].inode,
        None,
    )
    assert (add.entry.action, add.path, add.old_inode) == (
        EntryAction.ADD_FILE,
        f"{DIRECTORY}/a.txt",
        old.inode,
    )
    assert add.source == await publishing.stored(attempt.current_upload_id)
    await publishing.publications.mark_done(outcome, remove.entry.ordinal)
    await publishing.publications.mark_done(outcome, remove.entry.ordinal)
    assert await publishing.publications.next_entries(outcome) == (add,)


async def test_a_new_spelling_of_a_recorded_file_replaces_no_inode(publishing: Publishing) -> None:
    await committed(publishing)
    attempt = await publishing.ready(CONTRIBUTOR, "A.txt", NEW)
    outcome = await publishing.publications.submit(
        CONTRIBUTOR, publishing.request(3, [(attempt, NEW)])
    )
    remove, add = await publishing.publications.next_entries(outcome)
    assert (remove.entry.rel_path, remove.old_inode is None) == ("a.txt", False)
    assert (add.entry.rel_path, add.old_inode) == ("A.txt", None)
    succeeded = await publishing.publish(outcome)
    assert set(await publishing.files()) == {"keep.txt", "A.txt"}
    assert (succeeded.version, succeeded.file_count) == (4, 2)


async def test_the_final_transaction_records_the_objects_the_version_and_the_audit(
    publishing: Publishing,
) -> None:
    await committed(publishing)
    attempt = await publishing.ready(CONTRIBUTOR, "a.txt", NEW)
    added = await publishing.ready(CONTRIBUTOR, "b/c.txt", OLD)
    outcome = await publishing.publications.submit(
        CONTRIBUTOR, publishing.request(3, [(attempt, NEW), (added, OLD)], ["keep.txt"])
    )
    publishing.clock.advance(timedelta(minutes=1))
    succeeded = await publishing.publish(outcome)
    later = START + timedelta(minutes=1)
    assert (succeeded.state, succeeded.version, succeeded.file_count) == (
        CommitState.SUCCEEDED,
        4,
        2,
    )
    assert (succeeded.updated_at, succeeded.refusal) == (later, None)
    files = await publishing.files()
    assert set(files) == {"a.txt", "b/c.txt"}
    stored = await publishing.stored(attempt.current_upload_id)
    record = files["a.txt"]
    assert (record.size, record.sha256, record.inode, record.object_id) == (
        len(NEW),
        sha256(NEW),
        stored.inode,
        stored.id,
    )
    assert (record.commit_id, record.recorded_by, record.recorded_at) == (
        succeeded.commit_id,
        CONTRIBUTOR.subject,
        later,
    )
    collection = await publishing.collection()
    assert (collection.version, collection.file_count, collection.pending_request_id) == (
        4,
        2,
        None,
    )
    for each in (attempt, added):
        assert (await publishing.attempt(each)).state is AttemptState.CONSUMED
    commit = (await publishing.lake.commits.list_commits(CONTRIBUTOR, collection.id)).items[0]
    assert (commit.id, commit.base_version, commit.new_version) == (succeeded.commit_id, 3, 4)
    assert (commit.adds, commit.removes, commit.host, commit.actor) == (
        2,
        1,
        "host-1",
        CONTRIBUTOR.subject,
    )
    entry = (await publishing.lake.audit.for_collection(CONTRIBUTOR, collection.id)).items[0]
    assert (entry.action, entry.actor, entry.at) == (
        Action.COLLECTION_COMMIT,
        CONTRIBUTOR.subject,
        later,
    )
    assert entry.detail == {
        "adds": 2,
        "removes": 1,
        "host": "host-1",
        "message": "a test commit",
        "version": 4,
    }


async def test_the_final_version_follows_a_metadata_change_during_the_request(
    publishing: Publishing,
) -> None:
    attempt = await publishing.ready(CONTRIBUTOR, "a.txt", NEW)
    outcome = await publishing.publications.submit(
        CONTRIBUTOR, publishing.request(2, [(attempt, NEW)])
    )
    await publishing.lake.collections.update(
        CONTRIBUTOR, publishing.collection_id, 2, Update(metadata_patch={"note": "x"})
    )
    succeeded = await publishing.publish(outcome)
    assert succeeded.version == 4
    assert (await publishing.collection()).version == 4


async def test_a_request_finalized_two_times_publishes_one_time(publishing: Publishing) -> None:
    outcome = await committed(publishing)
    files = await publishing.files()
    assert await publishing.publications.finalize(outcome) == outcome
    assert await publishing.files() == files
    assert (await publishing.collection()).version == 3
    assert await publishing.publications.next_entries(outcome) == ()


async def test_a_request_with_an_entry_that_is_not_done_is_not_finalized(
    publishing: Publishing,
) -> None:
    attempt = await publishing.ready(CONTRIBUTOR, "a.txt", NEW)
    outcome = await publishing.publications.submit(
        CONTRIBUTOR, publishing.request(2, [(attempt, NEW)])
    )
    with pytest.raises(Conflict) as raised:
        await publishing.publications.finalize(outcome)
    assert raised.value.context == {"request_id": str(outcome.request_id), "open": [0]}
    assert (await publishing.saved(outcome)).state is CommitState.ACCEPTED


async def test_a_rejected_request_is_neither_done_nor_finalized(publishing: Publishing) -> None:
    request = publishing.request(1)
    with pytest.raises(BaseVersionConflict):
        await publishing.publications.submit(CONTRIBUTOR, request)
    rejected = await publishing.publications.status(CONTRIBUTOR, request.request_id)
    assert await publishing.publications.next_entries(rejected) == ()
    assert await publishing.publications.finalize(rejected) == rejected
    with pytest.raises(Conflict) as raised:
        await publishing.publications.mark_done(rejected, 0)
    assert raised.value.context["state"] == "rejected"
    with pytest.raises(Conflict):
        await publishing.publications.block(rejected, BLOCK)


async def test_a_blocked_request_keeps_its_hold_and_its_entries(publishing: Publishing) -> None:
    attempt = await publishing.ready(CONTRIBUTOR, "a.txt", NEW)
    outcome = await publishing.publications.submit(
        CONTRIBUTOR, publishing.request(2, [(attempt, NEW)])
    )
    blocked = await publishing.publications.block(outcome, BLOCK)
    assert (blocked.state, blocked.refusal) == (CommitState.BLOCKED, BLOCK)
    assert await publishing.saved(outcome) == blocked
    assert [p.request_id for p in await publishing.publications.pending()] == [outcome.request_id]
    assert len(await publishing.publications.next_entries(outcome)) == 1
    assert (await publishing.collection()).pending_request_id == outcome.id
    assert (await publishing.attempt(attempt)).commit_request_id == outcome.id


async def test_a_collection_with_a_pending_request_cannot_be_deleted(
    publishing: Publishing,
) -> None:
    await publishing.publications.submit(CONTRIBUTOR, publishing.request(2))
    with pytest.raises(CollectionBusy):
        await publishing.lake.collections.delete(CONTRIBUTOR, publishing.collection_id, 2)


# The operator exit.


async def blocked_overwrite(publishing: Publishing) -> CommitOutcome:
    """Version 3 with ``a.txt``, then a blocked request that replaces ``a.txt`` with NEW and
    adds ``d/e.txt``."""
    await committed(publishing)
    attempt = await publishing.ready(CONTRIBUTOR, "a.txt", NEW)
    other = await publishing.ready(CONTRIBUTOR, "d/e.txt", NEW + b"!")
    outcome = await publishing.publications.submit(
        CONTRIBUTOR, publishing.request(3, [(attempt, NEW), (other, NEW + b"!")])
    )
    return await publishing.publications.block(outcome, BLOCK)


async def test_only_a_platform_administrator_resolves_a_request(publishing: Publishing) -> None:
    blocked = await blocked_overwrite(publishing)
    with pytest.raises(Forbidden) as raised:
        await publishing.publications.resolve(
            CATALOG_ADMIN, publishing.collection_id, Resolution.RETRY
        )
    assert raised.value.context == {"role": "platform_admin", "scope": "platform"}
    assert await publishing.saved(blocked) == blocked


async def test_a_retry_makes_a_blocked_request_accepted_again(publishing: Publishing) -> None:
    outcome = await blocked_overwrite(publishing)
    retried = await publishing.publications.resolve(
        PLATFORM_ADMIN, publishing.collection_id, Resolution.RETRY
    )
    assert (retried.state, retried.refusal) == (CommitState.ACCEPTED, None)
    succeeded = await publishing.publish(retried)
    assert (succeeded.state, succeeded.version) == (CommitState.SUCCEEDED, 4)
    assert outcome.id == succeeded.id


async def test_an_abandon_with_no_done_entry_frees_the_collection_and_the_uploads(
    publishing: Publishing,
) -> None:
    outcome = await blocked_overwrite(publishing)
    files = await publishing.files()
    abandoned = await publishing.publications.resolve(
        PLATFORM_ADMIN, publishing.collection_id, Resolution.ABANDON
    )
    assert (abandoned.state, abandoned.refusal) == (CommitState.ABANDONED, BLOCK)
    collection = await publishing.collection()
    assert (collection.pending_request_id, collection.version) == (None, 3)
    assert await publishing.files() == files
    assert await publishing.publications.next_entries(outcome) == ()
    attempts = []
    for entry in await publishing.entries(outcome):
        if entry.upload_id is not None:
            async with publishing.store.transaction() as tx:
                attempts += (await tx.attempts.lock_uploads([entry.upload_id])).values()
    assert [(a.state, a.commit_request_id) for a in attempts] == [(AttemptState.READY, None)] * 2
    publishing.clock.advance(TTL + timedelta(seconds=1))
    assert len(await publishing.attempts.expire()) == 2


async def test_an_abandon_with_a_done_entry_is_refused(publishing: Publishing) -> None:
    outcome = await blocked_overwrite(publishing)
    first = (await publishing.publications.next_entries(outcome))[0]
    await publishing.publications.mark_done(outcome, first.entry.ordinal)
    with pytest.raises(Conflict) as raised:
        await publishing.publications.resolve(
            PLATFORM_ADMIN, publishing.collection_id, Resolution.ABANDON
        )
    assert raised.value.context == {
        "request_id": str(outcome.request_id),
        "done": [first.entry.ordinal],
    }
    assert (await publishing.saved(outcome)).state is CommitState.BLOCKED


async def test_a_collection_without_a_blocked_request_has_nothing_to_resolve(
    publishing: Publishing,
) -> None:
    with pytest.raises(NotFound) as raised:
        await publishing.publications.resolve(
            PLATFORM_ADMIN, publishing.collection_id, Resolution.RETRY
        )
    assert raised.value.context == {"collection": str(publishing.collection_id)}
    outcome = await publishing.publications.submit(CONTRIBUTOR, publishing.request(2))
    with pytest.raises(Conflict) as accepted:
        await publishing.publications.resolve(
            PLATFORM_ADMIN, publishing.collection_id, Resolution.ABANDON
        )
    assert accepted.value.context == {
        "request_id": str(outcome.request_id),
        "state": "accepted",
        "allowed": ["blocked"],
    }


# The defects of the earlier write path, each as the behaviour that prevents it.


async def test_a_refused_or_abandoned_overwrite_leaves_the_committed_file(
    publishing: Publishing,
) -> None:
    await committed(publishing)
    before = await publishing.files()
    attempt = await publishing.ready(CONTRIBUTOR, "a.txt", NEW)
    with pytest.raises(BaseVersionConflict):
        await publishing.publications.submit(CONTRIBUTOR, publishing.request(2, [(attempt, NEW)]))
    outcome = await publishing.publications.submit(
        CONTRIBUTOR, publishing.request(3, [(attempt, NEW)])
    )
    await publishing.publications.block(outcome, BLOCK)
    await publishing.publications.resolve(
        PLATFORM_ADMIN, publishing.collection_id, Resolution.ABANDON
    )
    assert await publishing.files() == before
    assert (await publishing.collection()).version == 3
    assert await publishing.publications.next_entries(outcome) == ()


async def test_a_commit_publishes_the_upload_that_it_names_and_not_the_newest(
    publishing: Publishing,
) -> None:
    older = await publishing.ready(CONTRIBUTOR, "a.txt", OLD)
    publishing.clock.advance(timedelta(minutes=1))
    newer = await publishing.ready(CONTRIBUTOR, "a.txt", NEW)
    outcome = await publishing.publications.submit(
        CONTRIBUTOR, publishing.request(2, [(older, OLD)])
    )
    await publishing.publish(outcome)
    record = (await publishing.files())["a.txt"]
    assert record.sha256 == sha256(OLD)
    assert record.object_id == (await publishing.stored(older.current_upload_id)).id
    assert (await publishing.attempt(newer)).state is AttemptState.READY


async def test_other_bytes_of_the_same_size_cannot_replay_an_upload(
    publishing: Publishing,
) -> None:
    attempt = await publishing.ready(CONTRIBUTOR, "a.txt", OLD)
    forged = b"x" * len(OLD)
    request = publishing.request(2, [(attempt, OLD)])
    request = replace(request, adds=(replace(request.adds[0], sha256=sha256(forged)),))
    error = await refused(publishing, CONTRIBUTOR, request, UploadIneligible)
    assert error.reason is IneligibleReason.DIFFERENT_FILE
    assert await publishing.files() == {}


async def test_a_late_seal_of_an_expired_upload_stays_private(publishing: Publishing) -> None:
    attempt = await publishing.receiving(CONTRIBUTOR, "a.txt", NEW)
    await publishing.attempts.start_seal(attempt.current_upload_id)
    publishing.clock.advance(TTL + timedelta(seconds=1))
    await publishing.attempts.expire()
    late = await publishing.attempts.finish_seal(
        attempt.current_upload_id, len(NEW), sha256(NEW), 7
    )
    assert late.state is AttemptState.EXPIRED
    error = await refused(
        publishing, CONTRIBUTOR, publishing.request(2, [(attempt, NEW)]), UploadIneligible
    )
    assert (error.reason, error.state) == (IneligibleReason.STATE, AttemptState.EXPIRED)
    assert await publishing.files() == {}


async def test_a_lost_answer_is_answered_by_the_saved_outcome(publishing: Publishing) -> None:
    attempt = await publishing.ready(CONTRIBUTOR, "a.txt", NEW)
    request = publishing.request(2, [(attempt, NEW)])
    accepted = await publishing.publications.submit(CONTRIBUTOR, request)
    assert await publishing.publications.submit(CONTRIBUTOR, request) == accepted
    succeeded = await publishing.publish(accepted)
    await publishing.commit(CONTRIBUTOR, 3, {"later.txt": OLD})
    again = await publishing.publications.submit(CONTRIBUTOR, request)
    assert again == succeeded
    assert (again.state, again.version) == (CommitState.SUCCEEDED, 3)
    stale = publishing.request(2)
    with pytest.raises(BaseVersionConflict):
        await publishing.publications.submit(CONTRIBUTOR, stale)
    rejected = await publishing.publications.submit(CONTRIBUTOR, stale)
    assert rejected.state is CommitState.REJECTED


async def test_an_expired_or_consumed_upload_is_never_published_again(
    publishing: Publishing,
) -> None:
    consumed = await publishing.ready(CONTRIBUTOR, "a.txt", NEW)
    expired = await publishing.ready(CONTRIBUTOR, "b.txt", OLD)
    publishing.clock.advance(TTL - timedelta(seconds=1))
    await publishing.publish(
        await publishing.publications.submit(CONTRIBUTOR, publishing.request(2, [(consumed, NEW)]))
    )
    publishing.clock.advance(timedelta(seconds=2))
    assert [attempt.id for attempt in await publishing.attempts.expire()] == [expired.id]
    for attempt, data, state in ((consumed, NEW, "consumed"), (expired, OLD, "expired")):
        error = await refused(
            publishing, CONTRIBUTOR, publishing.request(3, [(attempt, data)]), UploadIneligible
        )
        assert error.context["state"] == state
    assert set(await publishing.files()) == {"a.txt"}


async def test_an_upload_whose_seal_failed_cannot_be_published(publishing: Publishing) -> None:
    attempt = await publishing.receiving(CONTRIBUTOR, "a.txt", NEW)
    await publishing.attempts.start_seal(attempt.current_upload_id)
    await publishing.attempts.finish_seal(attempt.current_upload_id, 1, sha256(b"x"), 7)
    error = await refused(
        publishing, CONTRIBUTOR, publishing.request(2, [(attempt, NEW)]), UploadIneligible
    )
    assert error.context["state"] == "failed"
