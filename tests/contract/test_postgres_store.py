"""The PostgreSQL unit of work's lifecycle."""

import uuid

import pytest

from huron.core.metastore.postgres import PostgresStore, lock_key
from huron.pkg.errors import Unavailable

pytestmark = pytest.mark.contract


async def test_ping_reflects_the_pool(database_url: str) -> None:
    store = PostgresStore(database_url)
    assert await store.ping() is False
    with pytest.raises(Unavailable):
        async with store.transaction():
            pass
    await store.connect()
    assert await store.ping() is True
    async with store.transaction() as tx:
        await tx.files.upsert_many([])
        await tx.lock_catalog(uuid.uuid4())
    await store.close()
    await store.close()
    assert await store.ping() is False


async def test_unreachable_databases_are_unavailable() -> None:
    store = PostgresStore("postgresql://nobody@127.0.0.1:1/none")
    with pytest.raises(Unavailable):
        await store.connect()


async def test_a_broken_pool_does_not_ping(database_url: str) -> None:
    store = PostgresStore(database_url)
    await store.connect()
    assert store._pool is not None
    await store._pool.close()
    assert await store.ping() is False


def test_lock_keys_are_stable_signed_64_bit_integers() -> None:
    value = uuid.UUID(int=1)
    assert lock_key("catalog", value) == lock_key("catalog", value)
    assert lock_key("catalog", value) != lock_key("collection", value)
    assert -(2**63) <= lock_key("catalog", value) < 2**63
