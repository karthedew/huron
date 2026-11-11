"""The one writer of the lake: the lock, a second process that only reads, and the loss."""

import asyncio

import pytest
import structlog

from huron.applications.api.disk import WRITER_CHECK_INTERVAL, Ownership
from huron.core.metastore.postgres import PostgresWriterLock
from huron.core.metastore.store import MemoryStore
from huron.pkg.errors import Unavailable
from tests.support.clock import LoopClock


def ownership(store: MemoryStore, lost: list[str]) -> Ownership:
    return Ownership(store.writer_lock(), lambda: lost.append("lost"))


async def test_the_first_process_writes_and_a_second_one_only_reads() -> None:
    store, lost = MemoryStore(), []
    first, second = ownership(store, lost), ownership(store, lost)
    assert first.writable is False
    assert await first.start() is True
    with structlog.testing.capture_logs() as captured:
        assert await second.start() is False
    assert captured == [{"event": "ownership.reader", "log_level": "warning"}]
    assert first.writable and not second.writable
    assert await second.check() is False
    await second.close()
    assert await first.check() is True
    await first.close()
    assert first.writable is False
    third = ownership(store, lost)
    assert await third.start() is True
    await third.close()
    assert lost == []


async def test_the_loss_of_the_lock_ends_the_writes_and_calls_on_lost_one_time() -> None:
    store, lost = MemoryStore(), []
    owner = ownership(store, lost)
    await owner.start()
    store.writer = None
    with structlog.testing.capture_logs() as captured:
        assert await owner.check() is False
        assert await owner.check() is False
    assert owner.writable is False
    assert lost == ["lost"]
    assert captured == [{"event": "ownership.lost", "log_level": "error"}]
    await owner.close()


async def test_the_watch_checks_the_lock_after_each_interval(loop_clock: LoopClock) -> None:
    store = MemoryStore()
    lost = asyncio.Event()
    owner = Ownership(store.writer_lock(), lost.set)
    await owner.start()
    loop_clock.advance(WRITER_CHECK_INTERVAL)
    await asyncio.sleep(0)
    assert owner.writable
    store.writer = None
    loop_clock.advance(WRITER_CHECK_INTERVAL)
    await lost.wait()
    assert owner.writable is False
    await owner.close()


async def test_a_memory_lock_is_held_by_one_lock_of_its_store() -> None:
    store = MemoryStore()
    first, second = store.writer_lock(), store.writer_lock()
    assert await first.held() is False
    assert await first.acquire() is True
    assert await first.acquire() is False
    assert await second.acquire() is False
    await second.release()
    assert await first.held() is True and store.writer is first
    await first.release()
    assert store.writer is None
    assert await second.acquire() is True


async def test_a_postgres_lock_of_an_unreachable_database_is_unavailable() -> None:
    lock = PostgresWriterLock("postgresql://huron@127.0.0.1:9/huron", timeout=1)
    assert await lock.held() is False
    with pytest.raises(Unavailable) as refused:
        await lock.acquire()
    assert refused.value.message == "the database is unreachable"
    await lock.release()
