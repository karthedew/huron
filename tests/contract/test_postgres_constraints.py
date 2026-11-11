"""Rows the domain never writes, which PostgreSQL refuses on its own."""

import uuid
from collections.abc import Callable
from dataclasses import replace

import asyncpg
import pytest

from huron.core.lake.publications.models import EntryAction
from huron.core.lake.uploads.models import Failure, Upload, UploadState
from huron.core.metastore.postgres import PostgresStore
from huron.pkg.identifiers import new_id
from tests.contract.suite import collection, commit, placed, removal, tree, upload
from tests.support.clock import START

pytestmark = pytest.mark.contract


@pytest.mark.parametrize(
    "broken",
    [
        pytest.param(lambda row: replace(placed(row), sha256=None), id="placed without hash"),
        pytest.param(lambda row: replace(placed(row), placed_at=None), id="placed without time"),
        pytest.param(
            lambda row: replace(placed(row), state=UploadState.COMMITTED),
            id="committed without commit",
        ),
        pytest.param(lambda row: replace(row, state=UploadState.FAILED), id="failed without why"),
        pytest.param(lambda row: replace(row, size=-1), id="negative size"),
        pytest.param(lambda row: replace(placed(row), inode=None), id="placed without inode"),
        pytest.param(lambda row: replace(row, inode=1), id="pending with inode"),
        pytest.param(
            lambda row: replace(row, state=UploadState.FAILED, failure=Failure("X", "x"), inode=1),
            id="failed with inode",
        ),
    ],
)
async def test_an_upload_row_keeps_its_state_and_columns_in_step(
    uow: PostgresStore, broken: Callable[[Upload], Upload]
) -> None:
    _, cat, ns = await tree(uow)
    owner = collection(cat, ns, "run7")
    async with uow.transaction() as tx:
        await tx.collections.insert(owner)
    with pytest.raises(asyncpg.CheckViolationError):
        async with uow.transaction() as tx:
            await tx.uploads.insert(broken(upload(owner, "a.txt")))


async def test_only_a_committed_upload_names_a_commit(uow: PostgresStore) -> None:
    _, cat, ns = await tree(uow)
    owner = collection(cat, ns, "run7")
    made = commit(owner)
    async with uow.transaction() as tx:
        await tx.collections.insert(owner)
        await tx.commits.insert(made)
    with pytest.raises(asyncpg.CheckViolationError):
        async with uow.transaction() as tx:
            await tx.uploads.insert(replace(placed(upload(owner, "a.txt")), commit_id=made.id))


async def test_uploads_and_removals_name_only_stored_commits(uow: PostgresStore) -> None:
    _, cat, ns = await tree(uow)
    owner = collection(cat, ns, "run7")
    async with uow.transaction() as tx:
        await tx.collections.insert(owner)
    committed = replace(placed(upload(owner, "a.txt")), state=UploadState.COMMITTED)
    with pytest.raises(asyncpg.ForeignKeyViolationError):
        async with uow.transaction() as tx:
            await tx.uploads.insert(replace(committed, commit_id=new_id()))
    with pytest.raises(asyncpg.ForeignKeyViolationError):
        async with uow.transaction() as tx:
            await tx.uploads.insert_removals([removal(owner, "a.txt", new_id())])


async def test_an_attempt_key_is_unique_for_one_subject(
    uow: PostgresStore, database_url: str
) -> None:
    attempt_id = new_id()
    connection = await asyncpg.connect(database_url)
    try:
        await _attempt(connection, "dave", attempt_id, [new_id()])
        await _attempt(connection, "erin", attempt_id, [new_id()])
        with pytest.raises(asyncpg.UniqueViolationError):
            await _attempt(connection, "dave", attempt_id, [new_id()])
    finally:
        await connection.close()


async def test_an_upload_id_is_issued_for_one_attempt_only(
    uow: PostgresStore, database_url: str
) -> None:
    upload_id = new_id()
    connection = await asyncpg.connect(database_url)
    try:
        await _attempt(connection, "dave", new_id(), [upload_id])
        with pytest.raises(asyncpg.UniqueViolationError):
            await _attempt(connection, "erin", new_id(), [upload_id])
    finally:
        await connection.close()


async def test_an_attempt_keeps_every_issued_id_with_one_of_them_current(
    uow: PostgresStore, database_url: str
) -> None:
    first, current = new_id(), new_id()
    connection = await asyncpg.connect(database_url)
    try:
        attempt = await _attempt(connection, "dave", new_id(), [first, current])
        issued = await connection.fetch(
            "select upload_id from huron.staged_upload_ids where staged_upload_id = $1",
            attempt,
        )
        assert {row["upload_id"] for row in issued} == {first, current}
    finally:
        await connection.close()


async def test_the_current_upload_id_must_be_issued_for_its_own_attempt(
    uow: PostgresStore, database_url: str
) -> None:
    foreign = new_id()
    connection = await asyncpg.connect(database_url)
    try:
        await _attempt(connection, "erin", new_id(), [foreign])
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            async with connection.transaction():
                attempt = await _staged(connection, "dave", new_id(), foreign)
                await _issue(connection, attempt, new_id())
    finally:
        await connection.close()


async def test_a_request_key_is_unique_for_one_subject(
    uow: PostgresStore, database_url: str
) -> None:
    request_id = new_id()
    connection = await asyncpg.connect(database_url)
    try:
        await _request(connection, "dave", request_id)
        await _request(connection, "erin", request_id)
        with pytest.raises(asyncpg.UniqueViolationError):
            await _request(connection, "dave", request_id)
    finally:
        await connection.close()


async def test_a_pending_request_holds_one_collection_only(
    uow: PostgresStore, database_url: str
) -> None:
    _, cat, ns = await tree(uow)
    first, second = collection(cat, ns, "run7"), collection(cat, ns, "run8")
    async with uow.transaction() as tx:
        await tx.collections.insert(first)
        await tx.collections.insert(second)
    connection = await asyncpg.connect(database_url)
    try:
        request = await _request(connection, "dave", new_id())
        hold = "update huron.collections set pending_request_id = $1 where id = $2"
        await connection.execute(hold, request, first.id)
        with pytest.raises(asyncpg.UniqueViolationError):
            await connection.execute(hold, request, second.id)
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await connection.execute(hold, new_id(), second.id)
    finally:
        await connection.close()


async def test_every_entry_action_is_stored_and_only_an_add_names_an_upload(
    uow: PostgresStore, database_url: str
) -> None:
    upload_id = new_id()
    connection = await asyncpg.connect(database_url)
    try:
        await _attempt(connection, "dave", new_id(), [upload_id])
        request = await _request(connection, "dave", new_id())
        for ordinal, action in enumerate(EntryAction):
            named = upload_id if action is EntryAction.ADD_FILE else None
            await _entry(connection, request, ordinal, str(action), named)
        refused = [
            ("rename_file", None),
            (str(EntryAction.ADD_FILE), None),
            (str(EntryAction.PRUNE_DIRECTORY), upload_id),
        ]
        for action_name, named in refused:
            with pytest.raises(asyncpg.CheckViolationError):
                await _entry(connection, request, 99, action_name, named)
    finally:
        await connection.close()


@pytest.mark.parametrize("column", ["base_version", "version", "file_count"])
async def test_a_request_keeps_its_versions_and_count_at_zero_or_more(
    uow: PostgresStore, database_url: str, column: str
) -> None:
    connection = await asyncpg.connect(database_url)
    try:
        request = await _request(connection, "dave", new_id())
        await connection.execute(
            "update huron.commit_requests set base_version = 0, version = 0, file_count = 0"
            " where id = $1",
            request,
        )
        with pytest.raises(asyncpg.CheckViolationError):
            await connection.execute(
                f"update huron.commit_requests set {column} = -1 where id = $1", request
            )
    finally:
        await connection.close()


async def _entry(
    connection: asyncpg.Connection,
    request: uuid.UUID,
    ordinal: int,
    action: str,
    upload_id: uuid.UUID | None,
) -> None:
    await connection.execute(
        "insert into huron.commit_entries (commit_request_id, ordinal, action, rel_path, upload_id)"
        " values ($1, $2, $3, 'a.txt', $4)",
        request,
        ordinal,
        action,
        upload_id,
    )


async def _attempt(
    connection: asyncpg.Connection, subject: str, attempt_id: uuid.UUID, issued: list[uuid.UUID]
) -> uuid.UUID:
    """A receiving attempt with the issued upload IDs, the last one current."""
    async with connection.transaction():
        attempt = await _staged(connection, subject, attempt_id, issued[-1])
        for upload_id in issued:
            await _issue(connection, attempt, upload_id)
    return attempt


async def _staged(
    connection: asyncpg.Connection, subject: str, attempt_id: uuid.UUID, current: uuid.UUID
) -> uuid.UUID:
    attempt = new_id()
    await connection.execute(
        "insert into huron.staged_uploads (id, subject, attempt_id, rel_path, size, state,"
        " current_upload_id, created_at, active_at)"
        " values ($1, $2, $3, 'a.txt', 4, 'receiving', $4, $5, $5)",
        attempt,
        subject,
        attempt_id,
        current,
        START,
    )
    return attempt


async def _issue(connection: asyncpg.Connection, attempt: uuid.UUID, upload_id: uuid.UUID) -> None:
    await connection.execute(
        "insert into huron.staged_upload_ids (upload_id, staged_upload_id, issued_at)"
        " values ($1, $2, $3)",
        upload_id,
        attempt,
        START,
    )


async def _request(
    connection: asyncpg.Connection, subject: str, request_id: uuid.UUID
) -> uuid.UUID:
    row_id = new_id()
    await connection.execute(
        "insert into huron.commit_requests (id, subject, request_id, body_digest, base_version,"
        " host, state, created_at, updated_at) values ($1, $2, $3, $4, 1, 'h', 'accepted', $5, $5)",
        row_id,
        subject,
        request_id,
        "b" * 64,
        START,
    )
    return row_id
