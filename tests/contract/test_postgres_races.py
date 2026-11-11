"""Races that only a real database can show; each must resolve the same way every time."""

import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import replace
from datetime import timedelta
from typing import Any

import asyncpg
import pytest

from huron.core.lake.bootstrap import Lake, bootstrap, build_lake
from huron.core.lake.catalogs.models import Catalog
from huron.core.lake.collections.models import DeletedCollection, State, Update
from huron.core.lake.errors import NameTaken
from huron.core.lake.namespaces.errors import NamespaceNotEmpty
from huron.core.lake.publications.models import CommitDraft, CommitState, DraftAdd, Refusal
from huron.core.lake.schemas.models import BASE_SCHEMA_NAME
from huron.core.lake.uploads.models import AttemptState, UploadAttempt
from huron.core.metastore.catalogs.postgres import PostgresCatalogs
from huron.core.metastore.collections.postgres import PostgresCollections
from huron.core.metastore.postgres import PostgresStore, PostgresTransaction
from huron.pkg.errors import NotFound
from huron.pkg.identifiers import new_id
from huron.schema.validator import Validator
from tests.contract.suite import attempt, outcome, sealed, stored_collection, stored_object
from tests.support.clock import START, frozen
from tests.support.lake import (
    CATALOG_ADMIN,
    CONTRIBUTOR,
    ORG_ADMIN,
    READER,
    SETTINGS,
    World,
    seed,
    settled_collection,
)
from tests.support.publication import Publishing, publishing_of, publishing_over

pytestmark = pytest.mark.contract
SHA = "e" * 64
STRICT = {"type": "object", "properties": {"mission": {"type": "string"}}, "required": ["mission"]}


@pytest.fixture
async def lake(uow: PostgresStore) -> AsyncIterator[Lake]:
    clock = frozen()
    await bootstrap(uow, clock, SETTINGS)
    built = build_lake(uow, clock, SETTINGS)
    await seed(World(built, uow, clock))  # type: ignore[arg-type]
    yield built


async def publishing(lake: Lake, uow: PostgresStore, name: str = "run7") -> Publishing:
    """The commit operations for a new active collection ``name`` of ``lake``."""
    return publishing_of(lake, uow, frozen(), await settled_collection(lake, name))


async def test_namespace_and_collection_racing_for_one_name(lake: Lake) -> None:
    results = await asyncio.gather(
        lake.namespaces.create(CATALOG_ADMIN, "heliophysics", "solar-wind", "twin"),
        lake.collections.create(CONTRIBUTOR, "heliophysics", "solar-wind", "twin"),
        return_exceptions=True,
    )
    assert sum(isinstance(r, NameTaken) for r in results) == 1
    assert sum(not isinstance(r, Exception) for r in results) == 1


async def test_schema_assignment_racing_a_metadata_update_stays_consistent(lake: Lake) -> None:
    cid = await settled_collection(lake)
    base = (await lake.schemas.list(READER, None, None, None)).items[0].id
    strict = await lake.schemas.publish(
        ORG_ADMIN,
        "helio",
        "strict",
        base,
        {"type": "object", "properties": {"mission": {"type": "string"}}, "required": ["mission"]},
    )
    await asyncio.gather(
        lake.catalogs.assign_schema(CATALOG_ADMIN, "heliophysics", strict.id),
        lake.collections.update(CONTRIBUTOR, cid, 2, Update(metadata_patch={"note": "x"})),
        return_exceptions=True,
    )
    view = await lake.collections.get(READER, cid)
    schema = await lake.collections.resolved_schema(READER, cid)
    valid = not Validator(schema).validate(view.collection.metadata)
    assert (view.collection.state is State.ACTIVE) == valid


async def test_namespace_deletion_racing_collection_creation_leaves_no_orphan(lake: Lake) -> None:
    await lake.namespaces.create(CATALOG_ADMIN, "heliophysics", "", "doomed", True)
    results = await asyncio.gather(
        lake.namespaces.delete(CATALOG_ADMIN, "heliophysics", "doomed"),
        lake.collections.create(CONTRIBUTOR, "heliophysics", "doomed", "late"),
        return_exceptions=True,
    )
    namespace_gone = results[0] == "helio/heliophysics/doomed"
    if namespace_gone:
        assert isinstance(results[1], NotFound)
    else:
        assert isinstance(results[0], NamespaceNotEmpty)
        assert not isinstance(results[1], Exception)


async def test_a_commit_between_listing_and_recompute_is_not_overwritten(
    lake: Lake, uow: PostgresStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    published = await publishing(lake, uow)
    cid = published.collection_id
    page = await lake.schemas.list(ORG_ADMIN, None, None, None)
    base = next(entry.id for entry in page.items if entry.name == BASE_SCHEMA_NAME)
    strict = {
        "type": "object",
        "properties": {"mission": {"type": "string"}},
        "required": ["mission"],
    }
    entry = await lake.schemas.publish(ORG_ADMIN, "helio", "strict", base, strict)
    original = PostgresCollections.list_in_catalog
    committed: list[int] = []

    async def list_then_commit(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        rows = await original(self, *args, **kwargs)
        if not committed:
            outcome = await published.commit(CONTRIBUTOR, 2, {"late.txt": b"l"})
            assert outcome.version is not None
            committed.append(outcome.version)
        return rows

    monkeypatch.setattr(PostgresCollections, "list_in_catalog", list_then_commit)
    await lake.catalogs.assign_schema(ORG_ADMIN, "heliophysics", entry.id)
    view = await lake.collections.get(CONTRIBUTOR, cid)
    assert committed == [3]
    assert view.collection.version == 4 and view.collection.file_count == 1
    assert view.collection.state is State.INCOMPLETE


async def test_a_collection_deleted_between_listing_and_recompute_is_skipped(
    lake: Lake, monkeypatch: pytest.MonkeyPatch
) -> None:
    cid = await settled_collection(lake)
    kept = await settled_collection(lake, "run8")
    page = await lake.schemas.list(ORG_ADMIN, None, None, None)
    base = next(entry.id for entry in page.items if entry.name == BASE_SCHEMA_NAME)
    strict = {
        "type": "object",
        "properties": {"mission": {"type": "string"}},
        "required": ["mission"],
    }
    entry = await lake.schemas.publish(ORG_ADMIN, "helio", "strict", base, strict)
    original = PostgresCollections.list_in_catalog
    deleted: list[bool] = []

    async def list_then_delete(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        rows = await original(self, *args, **kwargs)
        if not deleted:
            await lake.collections.delete(CONTRIBUTOR, cid, 2)
            deleted.append(True)
        return rows

    monkeypatch.setattr(PostgresCollections, "list_in_catalog", list_then_delete)
    await lake.catalogs.assign_schema(ORG_ADMIN, "heliophysics", entry.id)
    assert deleted == [True]
    view = await lake.collections.get(CONTRIBUTOR, kept)
    assert view.collection.state is State.INCOMPLETE
    with pytest.raises(NotFound):
        await lake.collections.get(CONTRIBUTOR, cid)


async def test_a_dry_run_commit_writes_nothing_to_postgresql(
    lake: Lake, uow: PostgresStore
) -> None:
    published = await publishing(lake, uow)
    cid = published.collection_id
    await published.commit(CONTRIBUTOR, 2, {"a.txt": b"a"})
    log = await lake.audit.for_collection(CATALOG_ADMIN, cid)
    draft = CommitDraft(cid, 3, (DraftAdd("b.txt", 2),), ("a.txt",))
    preview = await published.publications.preview(CONTRIBUTOR, draft)
    assert preview.as_dict() == {"version": 4, "file_count": 1}
    view = await lake.collections.get(READER, cid)
    assert (view.collection.version, view.collection.file_count) == (3, 1)
    commits = await lake.commits.list_commits(READER, cid)
    assert len(commits.items) == 1
    files = await lake.commits.list_files(READER, cid)
    assert [f.rel_path for f in files.items] == ["a.txt"]
    after = await lake.audit.for_collection(CATALOG_ADMIN, cid)
    assert len(after.items) == len(log.items)
    result = await published.commit(CONTRIBUTOR, 3, {"b.txt": b"bb"}, ["a.txt"])
    assert (result.version, result.file_count) == (preview.version, preview.file_count)


async def test_an_upload_begun_during_a_collection_delete_waits_and_finds_no_collection(
    lake: Lake, uow: PostgresStore, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    published = await publishing(lake, uow)
    original = PostgresCollections.delete
    begun: list[asyncio.Task[UploadAttempt]] = []

    async def delete_while_begin_waits(self: PostgresCollections, collection_id: uuid.UUID) -> None:
        begin = asyncio.create_task(published.receiving(CONTRIBUTOR, "late.txt", b"l"))
        begun.append(begin)
        await _done_or_waiting_for_a_lock(begin, database_url)
        await original(self, collection_id)

    monkeypatch.setattr(PostgresCollections, "delete", delete_while_begin_waits)
    await lake.collections.delete(CONTRIBUTOR, published.collection_id, 2)
    with pytest.raises(NotFound, match="collection not found"):
        await begun[0]


async def test_an_upload_begun_with_a_collection_delete_never_fails_in_the_database(
    lake: Lake, uow: PostgresStore
) -> None:
    published = await publishing(lake, uow)
    begun, deleted = await asyncio.gather(
        published.receiving(CONTRIBUTOR, "late.txt", b"l"),
        lake.collections.delete(CONTRIBUTOR, published.collection_id, 2),
        return_exceptions=True,
    )
    assert deleted == DeletedCollection("helio/heliophysics/solar-wind/run7")
    if isinstance(begun, UploadAttempt):
        assert (await published.attempt(begun)).collection_id is None
    else:
        assert isinstance(begun, NotFound)


@pytest.mark.parametrize("first", ["share group", "schema"])
async def test_a_share_group_change_and_a_schema_assignment_keep_each_other(
    lake: Lake, database_url: str, monkeypatch: pytest.MonkeyPatch, first: str
) -> None:
    base = (await lake.schemas.list(READER, None, None, None)).items[0].id
    strict = await lake.schemas.publish(ORG_ADMIN, "helio", "strict", base, STRICT)
    changes: dict[str, Callable[[], Awaitable[object]]] = {
        "share group": lambda: lake.catalogs.set_share_group(
            ORG_ADMIN, "heliophysics", "helio-readers"
        ),
        "schema": lambda: lake.catalogs.assign_schema(ORG_ADMIN, "heliophysics", strict.id),
    }
    (second,) = set(changes) - {first}
    original = PostgresCatalogs.update
    waiting: list[asyncio.Task[object]] = []

    async def update_while_the_other_waits(self: PostgresCatalogs, catalog: Catalog) -> None:
        if not waiting:
            task = asyncio.create_task(changes[second]())
            waiting.append(task)
            await _done_or_waiting_for_a_lock(task, database_url)
        await original(self, catalog)

    monkeypatch.setattr(PostgresCatalogs, "update", update_while_the_other_waits)
    await changes[first]()
    await waiting[0]
    view = await lake.catalogs.get(READER, "heliophysics")
    assert (view.catalog.share_group, view.catalog.schema_id, view.catalog.version) == (
        "helio-readers",
        strict.id,
        3,
    )


async def test_a_share_group_change_waiting_for_a_catalog_delete_finds_no_catalog(
    lake: Lake, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    await lake.catalogs.create(ORG_ADMIN, "helio", "doomed")
    original = PostgresCatalogs.delete
    changes: list[asyncio.Task[object]] = []

    async def delete_while_the_change_waits(self: PostgresCatalogs, catalog_id: uuid.UUID) -> None:
        change = asyncio.create_task(lake.catalogs.set_share_group(ORG_ADMIN, "doomed", "late"))
        changes.append(change)
        await _done_or_waiting_for_a_lock(change, database_url)
        await original(self, catalog_id)

    monkeypatch.setattr(PostgresCatalogs, "delete", delete_while_the_change_waits)
    assert await lake.catalogs.delete(ORG_ADMIN, "doomed") == "helio/doomed"
    with pytest.raises(NotFound) as missing:
        await changes[0]
    assert missing.value.context == {"catalog": "doomed"}


async def test_a_share_group_change_with_a_catalog_delete_never_fails_in_the_database(
    lake: Lake,
) -> None:
    await lake.catalogs.create(ORG_ADMIN, "helio", "doomed")
    changed, deleted = await asyncio.gather(
        lake.catalogs.set_share_group(ORG_ADMIN, "doomed", "late"),
        lake.catalogs.delete(ORG_ADMIN, "doomed"),
        return_exceptions=True,
    )
    assert deleted == "helio/doomed"
    if isinstance(changed, BaseException):
        assert isinstance(changed, NotFound)
    else:
        assert changed.catalog.share_group == "late"
    with pytest.raises(NotFound):
        await lake.catalogs.get(ORG_ADMIN, "doomed")


async def test_two_first_creations_of_one_attempt_give_one_attempt(
    uow: PostgresStore, database_url: str
) -> None:
    owner = await stored_collection(uow)
    first = attempt(owner)
    second = replace(attempt(owner, size=9), attempt_id=first.attempt_id)
    reissued = new_id()
    async with uow.transaction() as tx:
        assert await tx.attempts.insert_or_lock(first) == first
        late = _Held(uow, lambda tx: tx.attempts.insert_or_lock(second))
        await _done_or_waiting_for_a_lock(late.task, database_url)
        assert not late.result.done()
        await tx.attempts.issue(first.id, reissued, START + timedelta(minutes=1))
    seen = await late.wait()
    assert seen == replace(
        first, current_upload_id=reissued, upload_ids=(first.current_upload_id, reissued)
    )
    await _locked_elsewhere(database_url, "staged_uploads", first.id)
    await late.close()
    async with uow.transaction() as tx:
        assert await tx.attempts.lock_uploads(second.upload_ids) == {}
        assert await tx.attempts.get("dave", first.attempt_id) == seen


async def test_two_connections_that_send_one_request_id_give_one_request(
    uow: PostgresStore, database_url: str
) -> None:
    owner = await stored_collection(uow)
    first = outcome(owner)
    second = replace(outcome(owner), request_id=first.request_id, body_digest="c" * 64)
    refusal = Refusal("BASE_VERSION_CONFLICT", "stale", {"current_version": 3})
    rejected = replace(first, state=CommitState.REJECTED, refusal=refusal)
    async with uow.transaction() as tx:
        assert await tx.commit_requests.insert_or_lock(first) == first
        late = _Held(uow, lambda tx: tx.commit_requests.insert_or_lock(second))
        await _done_or_waiting_for_a_lock(late.task, database_url)
        assert not late.result.done()
        await tx.commit_requests.update(rejected)
    assert await late.wait() == rejected
    await _locked_elsewhere(database_url, "commit_requests", first.id)
    await late.close()
    async with uow.transaction() as tx:
        assert await tx.commit_requests.lock(second.id) is None


async def test_a_second_request_for_one_collection_sees_the_first_hold_it(
    uow: PostgresStore, database_url: str
) -> None:
    owner = await stored_collection(uow)
    first, second = outcome(owner), outcome(owner)
    async with uow.transaction() as tx:
        await tx.commit_requests.insert_or_lock(first)
        await tx.commit_requests.insert_or_lock(second)
    async with uow.transaction() as tx:
        locked = await tx.collections.lock(owner.id)
        assert locked == owner
        late = _Held(uow, lambda tx: tx.collections.lock(owner.id))
        await _done_or_waiting_for_a_lock(late.task, database_url)
        assert not late.result.done()
        await tx.collections.update(replace(owner, pending_request_id=first.id))
    assert await late.wait() == replace(owner, pending_request_id=first.id)
    await late.close()


async def test_a_second_request_for_one_upload_sees_the_first_hold_it(
    uow: PostgresStore, database_url: str
) -> None:
    owner = await stored_collection(uow)
    first, second, upload = outcome(owner), outcome(owner), attempt(owner)
    ready = replace(upload, state=AttemptState.READY)
    async with uow.transaction() as tx:
        await tx.commit_requests.insert_or_lock(first)
        await tx.commit_requests.insert_or_lock(second)
        await tx.attempts.insert_or_lock(upload)
        await tx.attempts.update(ready)
    held = replace(ready, commit_request_id=first.id)
    async with uow.transaction() as tx:
        current = upload.current_upload_id
        assert await tx.attempts.lock_uploads(upload.upload_ids) == {current: ready}
        late = _Held(uow, lambda tx: tx.attempts.lock_uploads(upload.upload_ids))
        await _done_or_waiting_for_a_lock(late.task, database_url)
        assert not late.result.done()
        await tx.attempts.update(held)
    assert await late.wait() == {current: held}
    await late.close()


async def test_a_seal_that_runs_again_on_another_connection_uses_the_same_object(
    uow: PostgresStore, database_url: str
) -> None:
    owner = await stored_collection(uow)
    upload = attempt(owner)
    made = stored_object(upload.current_upload_id)
    again = stored_object(upload.current_upload_id, "helio/.huron-objects/again")
    async with uow.transaction() as tx:
        await tx.attempts.insert_or_lock(upload)
    async with uow.transaction() as tx:
        assert await tx.objects.insert_or_lock(made) == made
        late = _Held(uow, lambda tx: tx.objects.insert_or_lock(again))
        await _done_or_waiting_for_a_lock(late.task, database_url)
        assert not late.result.done()
        await tx.objects.update(sealed(made))
    assert await late.wait() == sealed(made)
    await _locked_elsewhere(database_url, "objects", made.id)
    await late.close()


async def test_idle_attempts_skip_an_attempt_that_another_transaction_holds(
    uow: PostgresStore,
) -> None:
    owner = await stored_collection(uow)
    busy, idle = attempt(owner), attempt(owner, minute=1)
    async with uow.transaction() as tx:
        await tx.attempts.insert_or_lock(busy)
        await tx.attempts.insert_or_lock(idle)
    holder = _Held(uow, lambda tx: tx.attempts.lock_uploads(busy.upload_ids))
    assert await holder.wait() == {busy.current_upload_id: busy}
    async with uow.transaction() as tx:
        assert await tx.attempts.lock_idle(START + timedelta(hours=1), 10) == [idle]
    await holder.close()


async def test_two_first_submissions_of_one_request_give_one_saved_outcome(
    uow: PostgresStore, database_url: str
) -> None:
    publishing = await publishing_over(uow)
    request = publishing.request(2)
    holder = _Held(uow, lambda tx: tx.collections.lock(publishing.collection_id))
    await holder.wait()
    submits = [
        asyncio.create_task(publishing.publications.submit(CONTRIBUTOR, request)) for _ in range(2)
    ]
    await _done_or_waiting_for_a_lock(submits[1], database_url, waiting=2)
    await holder.close()
    first, second = await asyncio.gather(*submits)
    assert first == second
    assert first.state is CommitState.ACCEPTED
    assert (await publishing.collection()).pending_request_id == first.id


async def test_a_finalize_that_waits_for_an_abandon_changes_nothing(
    uow: PostgresStore, database_url: str
) -> None:
    publishing = await publishing_over(uow)
    outcome = await publishing.publications.submit(CONTRIBUTOR, publishing.request(2))
    blocked = await publishing.publications.block(outcome, Refusal("STORAGE_FAILED", "blocked", {}))
    abandoned = replace(blocked, state=CommitState.ABANDONED)

    async def abandon(tx: PostgresTransaction) -> None:
        collection = await tx.collections.lock(publishing.collection_id)
        assert collection is not None
        await tx.commit_requests.update(abandoned)
        await tx.collections.update(replace(collection, pending_request_id=None))

    holder = _Held(uow, abandon)
    await holder.wait()
    late = asyncio.create_task(publishing.publications.finalize(outcome))
    await _done_or_waiting_for_a_lock(late, database_url)
    assert not late.done()
    await holder.close()
    assert await late == abandoned
    assert (await publishing.collection()).version == 2


async def _done_or_waiting_for_a_lock(
    task: asyncio.Task[Any], database_url: str, waiting: int = 1
) -> None:
    """Return once ``task`` is done or ``waiting`` transactions of this database wait for a lock.

    Fail the test when neither happens within 5 seconds.
    """
    connection = await asyncpg.connect(database_url)
    try:
        async with asyncio.timeout(5):
            while not task.done() and (
                await connection.fetchval(
                    "select count(distinct a.pid) from pg_locks l"
                    " join pg_stat_activity a on a.pid = l.pid"
                    " where not l.granted and a.datname = current_database()"
                )
                < waiting
            ):
                await asyncio.sleep(0.01)
    except TimeoutError:
        pytest.fail("the task did not finish or wait for a lock within 5 seconds")
    finally:
        await connection.close()


class _Held[T]:
    """A transaction in a task of its own that runs ``work``, then stays open until closed."""

    def __init__(
        self, uow: PostgresStore, work: Callable[[PostgresTransaction], Awaitable[T]]
    ) -> None:
        self.result: asyncio.Future[T] = asyncio.get_running_loop().create_future()
        self._release = asyncio.Event()
        self.task = asyncio.create_task(self._run(uow, work))

    async def wait(self) -> T:
        """The result of ``work``; fail the test when it takes more than 5 seconds."""
        async with asyncio.timeout(5):
            return await self.result

    async def close(self) -> None:
        """Commit the transaction and end the task."""
        self._release.set()
        await self.task

    async def _run(
        self, uow: PostgresStore, work: Callable[[PostgresTransaction], Awaitable[T]]
    ) -> None:
        async with uow.transaction() as tx:
            self.result.set_result(await work(tx))
            await self._release.wait()


async def _locked_elsewhere(database_url: str, table: str, row_id: uuid.UUID) -> None:
    """Fail unless another transaction holds the row of ``table`` with ``row_id`` locked."""
    connection = await asyncpg.connect(database_url)
    try:
        with pytest.raises(asyncpg.LockNotAvailableError):
            await connection.fetchval(
                f"select id from huron.{table} where id = $1 for update nowait", row_id
            )
    finally:
        await connection.close()
