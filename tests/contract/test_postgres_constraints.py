"""Rows the domain never writes, which PostgreSQL refuses on its own."""

from collections.abc import Callable
from dataclasses import replace

import asyncpg
import pytest

from huron.core.lake.uploads.models import Upload, UploadState
from huron.core.metastore.postgres import PostgresStore
from huron.pkg.identifiers import new_id
from tests.contract.suite import collection, commit, placed, removal, tree, upload

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
