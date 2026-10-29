"""Smaller behaviors: ports import, renderings, resolver caching and lookups."""

import importlib
import uuid

import pytest

from huron.core.lake.bootstrap import build_lake
from huron.core.lake.collections.models import UNSET
from huron.core.lake.files.models import Commit, FileRecord
from huron.core.lake.lookups import find_collection
from huron.core.lake.schemas import registry
from huron.core.lake.schemas.models import BASE_SCHEMA_NAME
from huron.core.lake.schemas.registry import SchemaResolver
from huron.core.metastore.store import MemoryStore
from huron.core.security.rbac import PLATFORM, Authorizer, Role
from huron.pkg.errors import NotFound
from tests.support.clock import START, frozen
from tests.support.lake import CONTRIBUTOR, PLATFORM_ADMIN, SETTINGS, VALID_METADATA, World

PORTS = [
    "huron.core.lake.organizations.ports",
    "huron.core.lake.catalogs.ports",
    "huron.core.lake.namespaces.ports",
    "huron.core.lake.collections.ports",
    "huron.core.lake.files.ports",
    "huron.core.lake.schemas.ports",
]


@pytest.mark.parametrize("module", PORTS)
def test_ports_are_protocols(module: str) -> None:
    loaded = importlib.import_module(module)
    for name in loaded.__all__:
        assert getattr(getattr(loaded, name), "_is_protocol", False)


def test_unset_has_a_readable_repr() -> None:
    assert repr(UNSET) == "UNSET"


def test_file_and_commit_renderings() -> None:
    commit_id = uuid.uuid4()
    record = FileRecord(uuid.uuid4(), "a/B.txt", "a/b.txt", 3, "f" * 64, START, "dave", commit_id)
    assert record.as_dict()["commit_id"] == str(commit_id)
    commit = Commit(commit_id, uuid.uuid4(), 1, 2, 1, 0, "h", None, "dave", START)
    assert commit.as_dict()["new_version"] == 2


async def test_resolver_caches_and_evicts(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry, "_CACHE_SIZE", 0)
    resolver = SchemaResolver()
    async with world.store.transaction() as tx:
        base = await tx.schemas.latest(None, BASE_SCHEMA_NAME)
        assert base is not None
        first = await resolver.resolve(tx.schemas, base.id)
        assert await resolver.resolve(tx.schemas, base.id) == first
        with pytest.raises(NotFound):
            await resolver.resolve(tx.schemas, uuid.uuid4())
    monkeypatch.setattr(registry, "_CACHE_SIZE", 10)
    cached = SchemaResolver()
    async with world.store.transaction() as tx:
        one = await cached.resolve(tx.schemas, base.id)
        assert await cached.resolve(tx.schemas, base.id) is one


async def test_collections_can_be_locked_by_identifier(seeded: World) -> None:
    draft = await seeded.lake.collections.create(
        CONTRIBUTOR, "heliophysics", "solar-wind", "run7", dict(VALID_METADATA)
    )
    async with seeded.store.transaction() as tx:
        found, catalog = await find_collection(
            tx,
            Authorizer(tx.grants),
            CONTRIBUTOR,
            identifier=draft.collection.identifier,
            lock=True,
        )
        assert found.id == draft.collection.id and catalog.name == "heliophysics"


async def test_catalog_creation_needs_the_base_schema() -> None:
    store = MemoryStore()
    lake = build_lake(store, frozen(), SETTINGS)
    async with store.transaction() as tx:
        await tx.grants.replace(PLATFORM, Role.PLATFORM_ADMIN, [SETTINGS.platform_admin_group], "t")
    await lake.organizations.create(PLATFORM_ADMIN, "helio")
    with pytest.raises(NotFound):
        await lake.catalogs.create(PLATFORM_ADMIN, "helio", "heliophysics")
