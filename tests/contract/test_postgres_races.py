"""Races that only a real database can show; each must resolve the same way every time."""

import asyncio
from collections.abc import AsyncIterator

import pytest

from huron.core.lake.bootstrap import Lake, bootstrap, build_lake
from huron.core.lake.collections.models import State, Update
from huron.core.lake.errors import NameTaken
from huron.core.lake.files.errors import BaseVersionConflict
from huron.core.lake.files.models import CommitRequest, FileAdd
from huron.core.lake.namespaces.errors import NamespaceNotEmpty
from huron.core.lake.schemas.models import BASE_SCHEMA_NAME
from huron.core.metastore.collections.postgres import PostgresCollections
from huron.core.metastore.postgres import PostgresStore
from huron.pkg.errors import NotFound
from huron.schema.validator import Validator
from tests.support.clock import frozen
from tests.support.lake import (
    CATALOG_ADMIN,
    CONTRIBUTOR,
    ORG_ADMIN,
    READER,
    SETTINGS,
    VALID_METADATA,
    World,
    seed,
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


async def active_collection(lake: Lake, name: str = "run7") -> object:
    draft = await lake.collections.create(
        CONTRIBUTOR, "heliophysics", "solar-wind", name, dict(VALID_METADATA)
    )
    return (await lake.collections.activate(CONTRIBUTOR, draft.collection.id, 1)).collection.id


async def test_concurrent_commits_on_one_base_version(lake: Lake) -> None:
    cid = await active_collection(lake)
    requests = [CommitRequest(2, (FileAdd(f"{i}.txt", 1, SHA),), (), f"h{i}") for i in range(2)]
    results = await asyncio.gather(
        *(lake.commits.commit(CONTRIBUTOR, cid, r) for r in requests),  # type: ignore[arg-type]
        return_exceptions=True,
    )
    assert sum(isinstance(r, BaseVersionConflict) for r in results) == 1
    assert sum(not isinstance(r, Exception) for r in results) == 1
    view = await lake.collections.get(READER, cid)  # type: ignore[arg-type]
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
    cid = await active_collection(lake)
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
        lake.collections.update(CONTRIBUTOR, cid, 2, Update(metadata_patch={"note": "x"})),  # type: ignore[arg-type]
        return_exceptions=True,
    )
    view = await lake.collections.get(READER, cid)  # type: ignore[arg-type]
    schema = await lake.collections.resolved_schema(READER, cid)  # type: ignore[arg-type]
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
    cid = await active_collection(lake)
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
            committed.append((await lake.commits.commit(CONTRIBUTOR, cid, request)).version)  # type: ignore[arg-type]
        return rows

    monkeypatch.setattr(PostgresCollections, "list_in_catalog", list_then_commit)
    await lake.catalogs.assign_schema(ORG_ADMIN, "heliophysics", entry.id)
    view = await lake.collections.get(CONTRIBUTOR, cid)  # type: ignore[arg-type]
    assert committed == [3]
    assert view.collection.version == 4 and view.collection.file_count == 1
    assert view.collection.state is State.INCOMPLETE


async def test_a_collection_deleted_between_listing_and_recompute_is_skipped(
    lake: Lake, monkeypatch: pytest.MonkeyPatch
) -> None:
    cid = await active_collection(lake)
    kept = await active_collection(lake, "run8")
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
            await lake.collections.delete(CONTRIBUTOR, cid, 2)  # type: ignore[arg-type]
            deleted.append(True)
        return rows

    monkeypatch.setattr(PostgresCollections, "list_in_catalog", list_then_delete)
    await lake.catalogs.assign_schema(ORG_ADMIN, "heliophysics", entry.id)
    assert deleted == [True]
    view = await lake.collections.get(CONTRIBUTOR, kept)  # type: ignore[arg-type]
    assert view.collection.state is State.INCOMPLETE
    with pytest.raises(NotFound):
        await lake.collections.get(CONTRIBUTOR, cid)  # type: ignore[arg-type]
