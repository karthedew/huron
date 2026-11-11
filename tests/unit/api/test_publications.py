"""Publication of accepted commit requests on the lake, and its recovery at startup."""

import asyncio
import errno
import threading
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass

import pytest

from huron.applications.api.disk import PUBLISH_WAIT, wait_for
from huron.core.lake.audit.models import Action
from huron.core.lake.files.models import FileRecord
from huron.core.lake.publications.models import CommitOutcome, CommitState, Refusal
from huron.core.lake.uploads.models import UploadAttempt
from huron.core.storage import MARKER_FILE, LakePath, LakeUnavailable, StorageError
from huron.pkg.identifiers import new_id
from huron.schema.naming import rel_path_key
from tests.support.clock import START
from tests.support.disk import SIGNAL_TIMEOUT
from tests.support.lake import CONTRIBUTOR
from tests.support.orchestration import COLLECTION, OBJECTS, Bench, bench

WIND, SUN = b"solar wind", b"sunspots"


@pytest.fixture
async def lab() -> AsyncIterator[Bench]:
    async with bench() as built:
        yield built


@dataclass
class Flag:
    """A writer whose lock the test takes away."""

    writable: bool = True


async def submit(
    lab: Bench,
    base_version: int,
    files: dict[str, bytes],
    removes: Sequence[str] = (),
) -> CommitOutcome:
    """Seal ``files`` on the lake and submit one request with them and ``removes``."""
    adds: list[tuple[UploadAttempt, bytes]] = [
        (await lab.sealed(path, data), data) for path, data in files.items()
    ]
    request = lab.publishing.request(base_version, adds, removes)
    return await lab.publishing.publications.submit(CONTRIBUTOR, request)


def on_lake(lab: Bench, rel_path: str) -> bytes | None:
    return lab.storage.read_bytes(COLLECTION.joinpath(*rel_path.split("/")))


async def commits(lab: Bench) -> int:
    """The number of commit audit records of the collection."""
    async with lab.publishing.store.transaction() as tx:
        entries = await tx.audit.for_object(lab.publishing.collection_id, None, 100)
    return sum(1 for entry in entries if entry.action is Action.COLLECTION_COMMIT)


async def test_a_request_is_published_on_the_lake_and_finalized(lab: Bench) -> None:
    accepted = await submit(lab, 2, {"a.cdf": WIND, "sub/b.cdf": SUN})
    task = lab.materializer.start(accepted)
    assert lab.materializer.start(accepted) is task
    done = await wait_for(task, PUBLISH_WAIT)
    assert done is not None and done.state is CommitState.SUCCEEDED
    assert (done.version, done.file_count) == (3, 2)
    assert on_lake(lab, "a.cdf") == WIND and on_lake(lab, "sub/b.cdf") == SUN
    files = await lab.publishing.files()
    assert all(record.object_id is not None for record in files.values())
    assert (await lab.publishing.collection()).pending_request_id is None
    assert all(entry.done_at == START for entry in await lab.publishing.entries(accepted))


async def test_a_replace_and_a_remove_change_only_the_named_files(lab: Bench) -> None:
    first = await lab.materializer.start(await submit(lab, 2, {"a.cdf": WIND, "sub/b.cdf": SUN}))
    replaced = await submit(lab, first.version or 0, {"a.cdf": SUN}, removes=["sub/b.cdf"])
    done = await lab.materializer.start(replaced)
    assert (done.state, done.version, done.file_count) == (CommitState.SUCCEEDED, 4, 1)
    assert on_lake(lab, "a.cdf") == SUN
    assert lab.storage.stat(COLLECTION.joinpath("sub")) is None
    assert await commits(lab) == 2


async def test_a_storage_error_leaves_the_request_pending_and_a_second_run_ends_it_once(
    lab: Bench,
) -> None:
    accepted = await submit(lab, 2, {"a.cdf": WIND})
    (attempt_id,) = [entry.upload_id for entry in await lab.publishing.entries(accepted)]
    temporary = COLLECTION.joinpath(f".a.cdf.{attempt_id}.huron-part")
    lab.storage.faults[("link", temporary)] = errno.ENOSPC
    with pytest.raises(StorageError):
        await lab.materializer.start(accepted)
    saved = await lab.publishing.saved(accepted)
    assert saved.state is CommitState.ACCEPTED
    assert [entry.done_at for entry in await lab.publishing.entries(accepted)] == [None]
    assert await lab.publishing.files() == {}
    assert on_lake(lab, "a.cdf") is None
    assert (await lab.publishing.collection()).version == 2
    done = await lab.materializer.start(accepted)
    assert (done.state, done.version) == (CommitState.SUCCEEDED, 3)
    again = await lab.materializer.start(accepted)
    assert again == done
    assert (await lab.publishing.collection()).version == 3
    assert await commits(lab) == 1
    assert on_lake(lab, "a.cdf") == WIND


async def test_a_foreign_file_at_the_target_blocks_the_request_and_stays(lab: Bench) -> None:
    accepted = await submit(lab, 2, {"a.cdf": WIND})
    target = COLLECTION.joinpath("a.cdf")
    lab.storage.write_bytes(target, b"foreign", 0o644)
    blocked = await lab.materializer.start(accepted)
    assert blocked.state is CommitState.BLOCKED
    path = "helio/heliophysics/solar-wind/run7/a.cdf"
    assert blocked.refusal == Refusal(
        "PUBLICATION_BLOCKED",
        f"{path} is not the entry that the request expects. Huron did not change it."
        " A platform administrator must resolve the commit request",
        {"ordinal": 0, "reason": "foreign_entry", "path": path},
    )
    assert lab.storage.read_bytes(target) == b"foreign"
    assert (await lab.publishing.collection()).pending_request_id == accepted.id


async def test_recovery_continues_the_accepted_and_the_blocked_requests(lab: Bench) -> None:
    accepted = await submit(lab, 2, {"a.cdf": WIND})
    lab.storage.write_bytes(COLLECTION.joinpath("a.cdf"), b"foreign", 0o644)
    blocked = await lab.materializer.start(accepted)
    assert blocked.state is CommitState.BLOCKED
    lab.storage.remove_file(COLLECTION.joinpath("a.cdf"))
    (task,) = await lab.materializer.recover_pending()
    done = await task
    assert done.state is CommitState.SUCCEEDED
    assert on_lake(lab, "a.cdf") == WIND
    assert await lab.materializer.recover_pending() == []


async def test_a_blocked_request_whose_entries_are_all_done_is_finalized(lab: Bench) -> None:
    accepted = await submit(lab, 2, {"a.cdf": WIND})
    publications = lab.publishing.publications
    for target in await publications.next_entries(accepted):
        await publications.mark_done(accepted, target.entry.ordinal)
    await publications.block(accepted, Refusal("PUBLICATION_BLOCKED", "a test", {}))
    (task,) = await lab.materializer.recover_pending()
    done = await task
    assert done.state is CommitState.SUCCEEDED
    assert (await lab.publishing.collection()).version == 3


async def test_a_removal_of_a_file_whose_inode_huron_never_learned_blocks(lab: Bench) -> None:
    owner = lab.publishing.collection_id
    record = FileRecord(
        owner, "old.cdf", rel_path_key("old.cdf"), 3, "a" * 64, START, "t", new_id()
    )
    async with lab.publishing.store.transaction() as tx:
        await tx.files.upsert_many([record])
    lab.storage.write_bytes(COLLECTION.joinpath("old.cdf"), b"old", 0o644)
    request = lab.publishing.request(2, removes=["old.cdf"])
    accepted = await lab.publishing.publications.submit(CONTRIBUTOR, request)
    blocked = await lab.materializer.start(accepted)
    path = "helio/heliophysics/solar-wind/run7/old.cdf"
    assert blocked.state is CommitState.BLOCKED
    assert blocked.refusal is not None
    assert blocked.refusal.context == {"ordinal": 0, "reason": "inode_unknown", "path": path}
    assert blocked.refusal.detail.startswith(f"Huron does not know the inode of {path}.")
    assert on_lake(lab, "old.cdf") == b"old"


async def test_a_lake_whose_marker_is_gone_gives_no_step_and_no_success(lab: Bench) -> None:
    published = await lab.materializer.start(await submit(lab, 2, {"a.cdf": WIND}))
    request = lab.publishing.request(published.version or 0, removes=["a.cdf"])
    accepted = await lab.publishing.publications.submit(CONTRIBUTOR, request)
    lab.storage.remove_file(LakePath.of(MARKER_FILE))
    with pytest.raises(LakeUnavailable):
        await lab.materializer.start(accepted)
    assert (await lab.publishing.saved(accepted)).state is CommitState.ACCEPTED
    assert [entry.done_at for entry in await lab.publishing.entries(accepted)] == [None]
    assert on_lake(lab, "a.cdf") == WIND


async def test_a_process_that_lost_the_writer_lock_starts_no_step() -> None:
    writer = Flag()
    async with bench(writer=writer) as lab:
        accepted = await submit(lab, 2, {"a.cdf": WIND})
        writer.writable = False
        calls = len(lab.storage.calls)
        with pytest.raises(LakeUnavailable) as refused:
            await lab.materializer.start(accepted)
        assert refused.value.context == {"reason": "writer_lock"}
        assert refused.value.message == (
            "this API process does not hold the writer lock. Another API process writes the lake"
        )
        assert len(lab.storage.calls) == calls
        assert (await lab.publishing.saved(accepted)).state is CommitState.ACCEPTED


async def test_the_objects_of_a_published_request_stay_in_the_object_area(lab: Bench) -> None:
    done = await lab.materializer.start(await submit(lab, 2, {"a.cdf": WIND}))
    assert done.state is CommitState.SUCCEEDED
    (record,) = (await lab.publishing.files()).values()
    published = lab.storage.stat(COLLECTION.joinpath("a.cdf"))
    assert published is not None and record.inode == published.inode
    (upload_id,) = [entry.upload_id for entry in await lab.publishing.entries(done)]
    assert upload_id is not None
    kept = lab.storage.stat(OBJECTS.joinpath(str(upload_id)))
    assert kept is not None and kept.inode == published.inode
    assert (await lab.publishing.stored(upload_id)).id == record.object_id


async def test_an_add_at_the_path_of_a_directory_removes_that_directory_first(
    lab: Bench,
) -> None:
    first = await lab.materializer.start(await submit(lab, 2, {"x/y.cdf": WIND}))
    request = await submit(lab, first.version or 0, {"x": SUN}, removes=["x/y.cdf"])
    done = await lab.materializer.start(request)
    assert (done.state, done.file_count) == (CommitState.SUCCEEDED, 1)
    assert on_lake(lab, "x") == SUN
    assert set(await lab.publishing.files()) == {"x"}


async def test_the_loop_completes_a_request_that_a_storage_error_left_accepted(
    lab: Bench,
) -> None:
    accepted = await submit(lab, 2, {"a.cdf": WIND})
    (upload_id,) = [entry.upload_id for entry in await lab.publishing.entries(accepted)]
    lab.storage.faults[("link", COLLECTION.joinpath(f".a.cdf.{upload_id}.huron-part"))] = (
        errno.ESTALE
    )
    with pytest.raises(StorageError):
        await lab.materializer.start(accepted)
    (task,) = await lab.materializer.resume_accepted()
    done = await task
    assert (done.state, done.version) == (CommitState.SUCCEEDED, 3)
    assert await lab.materializer.resume_accepted() == []
    assert await commits(lab) == 1


async def test_the_loop_leaves_a_blocked_request_to_the_operator(lab: Bench) -> None:
    accepted = await submit(lab, 2, {"a.cdf": WIND})
    lab.storage.write_bytes(COLLECTION.joinpath("a.cdf"), b"foreign", 0o644)
    assert (await lab.materializer.start(accepted)).state is CommitState.BLOCKED
    lab.storage.remove_file(COLLECTION.joinpath("a.cdf"))
    assert await lab.materializer.resume_accepted() == []
    assert (await lab.publishing.saved(accepted)).state is CommitState.BLOCKED


async def test_the_loop_joins_a_request_whose_task_runs(
    lab: Bench, monkeypatch: pytest.MonkeyPatch
) -> None:
    accepted = await submit(lab, 2, {"a.cdf": WIND})
    linking, release = threading.Event(), threading.Event()
    link = lab.storage.link_once

    def paused(source: LakePath, destination: LakePath) -> None:
        linking.set()
        assert release.wait(SIGNAL_TIMEOUT)
        link(source, destination)

    monkeypatch.setattr(lab.storage, "link_once", paused)
    running = lab.materializer.start(accepted)
    assert await asyncio.to_thread(linking.wait, SIGNAL_TIMEOUT)
    assert await lab.materializer.resume_accepted() == [running]
    release.set()
    assert (await running).state is CommitState.SUCCEEDED
    assert await commits(lab) == 1
