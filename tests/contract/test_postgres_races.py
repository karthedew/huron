"""Races that only a real database can show; each must resolve the same way every time."""

import asyncio
import uuid
from collections.abc import AsyncIterator, Sequence

import asyncpg
import pytest

from huron.core.lake.bootstrap import Lake, bootstrap, build_lake
from huron.core.lake.collections.models import State, Update
from huron.core.lake.errors import NameTaken
from huron.core.lake.files.errors import BaseVersionConflict
from huron.core.lake.files.models import CommitRequest, FileAdd
from huron.core.lake.namespaces.errors import NamespaceNotEmpty
from huron.core.lake.schemas.models import BASE_SCHEMA_NAME
from huron.core.lake.uploads.errors import UploadNotFound
from huron.core.lake.uploads.models import Upload
from huron.core.metastore.collections.postgres import PostgresCollections
from huron.core.metastore.postgres import PostgresStore
from huron.core.metastore.uploads.postgres import PostgresUploads
from huron.pkg.errors import NotFound
from huron.schema.validator import Validator
from tests.support.clock import frozen
from tests.support.lake import (
    CATALOG_ADMIN,
    CONTRIBUTOR,
    ORG_ADMIN,
    READER,
    SETTINGS,
    World,
    commit_uploaded,
    placed_upload,
    seed,
    settled_collection,
)

pytestmark = pytest.mark.contract
SHA = "e" * 64


@pytest.fixture
async def lake(uow: PostgresStore) -> AsyncIterator[Lake]:
    clock = frozen()
    await bootstrap(uow, clock, SETTINGS)
    built = build_lake(uow, clock, SETTINGS)
    await seed(World(built, uow, clock))  # type: ignore[arg-type]
    yield built


async def test_concurrent_commits_on_one_base_version(lake: Lake) -> None:
    cid = await settled_collection(lake)
    requests = [CommitRequest(2, (FileAdd(f"{i}.txt", 1, SHA),), (), f"h{i}") for i in range(2)]
    for request in requests:
        await placed_upload(lake, CONTRIBUTOR, cid, request.adds[0].rel_path, 1, SHA)
    results = await asyncio.gather(
        *(lake.commits.commit(CONTRIBUTOR, cid, r) for r in requests),
        return_exceptions=True,
    )
    assert sum(isinstance(r, BaseVersionConflict) for r in results) == 1
    assert sum(not isinstance(r, Exception) for r in results) == 1
    view = await lake.collections.get(READER, cid)
    assert (view.collection.version, view.collection.file_count) == (3, 1)


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
    namespace_gone = results[0] is None
    if namespace_gone:
        assert isinstance(results[1], NotFound)
    else:
        assert isinstance(results[0], NamespaceNotEmpty)
        assert not isinstance(results[1], Exception)


async def test_a_commit_between_listing_and_recompute_is_not_overwritten(
    lake: Lake, monkeypatch: pytest.MonkeyPatch
) -> None:
    cid = await settled_collection(lake)
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
            request = CommitRequest(2, (FileAdd("late.txt", 1, SHA),), (), "h")
            committed.append((await commit_uploaded(lake, CONTRIBUTOR, cid, request)).version)
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


async def test_a_dry_run_commit_writes_nothing_to_postgresql(lake: Lake) -> None:
    cid = await settled_collection(lake)
    added = CommitRequest(2, (FileAdd("a.txt", 1, SHA),), (), "h")
    await commit_uploaded(lake, CONTRIBUTOR, cid, added)
    log = await lake.audit.for_collection(CATALOG_ADMIN, cid)
    request = CommitRequest(3, (FileAdd("b.txt", 2, None),), ("a.txt",), "h")
    preview = await lake.commits.commit(CONTRIBUTOR, cid, request, dry_run=True)
    assert preview.as_dict() == {"version": 4, "file_count": 1, "commit_id": None}
    view = await lake.collections.get(READER, cid)
    assert (view.collection.version, view.collection.file_count) == (3, 1)
    commits = await lake.commits.list_commits(READER, cid)
    assert len(commits.items) == 1
    files = await lake.commits.list_files(READER, cid)
    assert [f.rel_path for f in files.items] == ["a.txt"]
    after = await lake.audit.for_collection(CATALOG_ADMIN, cid)
    assert len(after.items) == len(log.items)
    hashed = CommitRequest(3, (FileAdd("b.txt", 2, SHA),), ("a.txt",), "h")
    result = await commit_uploaded(lake, CONTRIBUTOR, cid, hashed)
    assert (result.version, result.file_count) == (preview.version, preview.file_count)


async def test_a_receipt_waits_for_a_collection_delete_that_read_the_placed_uploads(
    lake: Lake, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    cid = await settled_collection(lake)
    upload = await lake.uploads.begin(CONTRIBUTOR, cid, "late.txt", 1)
    original = PostgresUploads.placed
    receipts: list[asyncio.Task[Upload]] = []

    async def placed_then_receipt(
        self: PostgresUploads, collection_id: uuid.UUID
    ) -> Sequence[Upload]:
        rows = await original(self, collection_id)
        receipt = asyncio.create_task(lake.uploads.receipt(upload.id, 1, SHA))
        receipts.append(receipt)
        await _done_or_waiting_for_a_lock(receipt, database_url)
        return rows

    monkeypatch.setattr(PostgresUploads, "placed", placed_then_receipt)
    await lake.collections.delete(CONTRIBUTOR, cid, 2)
    with pytest.raises(UploadNotFound):
        await receipts[0]
    assert await lake.uploads.claim_removals() == []


async def test_an_upload_begun_during_a_collection_delete_waits_and_finds_no_collection(
    lake: Lake, database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    cid = await settled_collection(lake)
    original = PostgresUploads.placed
    begun: list[asyncio.Task[Upload]] = []

    async def placed_then_begin(
        self: PostgresUploads, collection_id: uuid.UUID
    ) -> Sequence[Upload]:
        rows = await original(self, collection_id)
        begin = asyncio.create_task(lake.uploads.begin(CONTRIBUTOR, cid, "late.txt", 1))
        begun.append(begin)
        await _done_or_waiting_for_a_lock(begin, database_url)
        return rows

    monkeypatch.setattr(PostgresUploads, "placed", placed_then_begin)
    await lake.collections.delete(CONTRIBUTOR, cid, 2)
    with pytest.raises(NotFound, match="collection not found"):
        await begun[0]
    assert await lake.uploads.claim_removals() == []


async def test_an_upload_begun_with_a_collection_delete_never_fails_in_the_database(
    lake: Lake,
) -> None:
    cid = await settled_collection(lake)
    begun, deleted = await asyncio.gather(
        lake.uploads.begin(CONTRIBUTOR, cid, "late.txt", 1),
        lake.collections.delete(CONTRIBUTOR, cid, 2),
        return_exceptions=True,
    )
    assert deleted is None
    if isinstance(begun, Upload):
        with pytest.raises(UploadNotFound):
            await lake.uploads.get(CONTRIBUTOR, begun.id)
    else:
        assert isinstance(begun, NotFound)


async def _done_or_waiting_for_a_lock(task: asyncio.Task[Upload], database_url: str) -> None:
    """Return once ``task`` is done or a transaction of this database waits for a lock.

    Fail the test when neither happens within 5 seconds.
    """
    connection = await asyncpg.connect(database_url)
    try:
        async with asyncio.timeout(5):
            while not task.done() and not await connection.fetchval(
                "select exists (select from pg_locks l join pg_stat_activity a on a.pid = l.pid"
                " where not l.granted and a.datname = current_database())"
            ):
                await asyncio.sleep(0.01)
    except TimeoutError:
        pytest.fail("the task did not finish or wait for a lock within 5 seconds")
    finally:
        await connection.close()
