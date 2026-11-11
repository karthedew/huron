"""The writer lock of the lake on PostgreSQL: one writer, readers, and the loss of the lock."""

import asyncpg
import pytest

from huron.applications.api.runtime import build_runtime
from huron.core.metastore.postgres import KEEPALIVES, WRITER_APPLICATION, PostgresWriterLock
from huron.core.storage import LakeUnavailable
from tests.support.api import settings
from tests.support.disk import LAKE, memory_lake
from tests.support.postgres import truncate

pytestmark = pytest.mark.contract


async def terminate_writer(database_url: str) -> None:
    """End the session of the writer's connection, as a dropped connection ends it."""
    connection = await asyncpg.connect(database_url)
    try:
        ended = await connection.fetchval(
            "select count(*) from (select pg_terminate_backend(pid) from pg_stat_activity"
            " where application_name = $1) as ended",
            WRITER_APPLICATION,
        )
        assert ended >= 1
    finally:
        await connection.close()


async def test_one_session_holds_the_lock_and_it_ends_with_the_session(database_url: str) -> None:
    first, second = PostgresWriterLock(database_url), PostgresWriterLock(database_url)
    try:
        assert await first.acquire() is True
        assert await second.acquire() is False
        assert await first.held() is True
        assert await second.held() is False
        await first.release()
        assert await first.held() is False
        assert await second.acquire() is True
    finally:
        await first.release()
        await second.release()


async def test_a_dropped_connection_loses_the_lock(database_url: str) -> None:
    lock = PostgresWriterLock(database_url)
    other = PostgresWriterLock(database_url)
    try:
        assert await lock.acquire() is True
        await terminate_writer(database_url)
        assert await lock.held() is False
        assert await other.acquire() is True
    finally:
        await lock.release()
        await other.release()


async def test_the_server_takes_the_keepalives_of_the_writer_connection(
    database_url: str,
) -> None:
    connection = await asyncpg.connect(database_url, server_settings=KEEPALIVES)
    try:
        shown = {name: await connection.fetchval(f"show {name}") for name in KEEPALIVES}
    finally:
        await connection.close()
    assert (
        shown
        == KEEPALIVES
        == {
            "tcp_keepalives_idle": "30",
            "tcp_keepalives_interval": "10",
            "tcp_keepalives_count": "3",
        }
    )


async def test_a_second_runtime_on_the_same_database_serves_reads_only(database_url: str) -> None:
    await truncate(database_url)
    storage, lost = memory_lake(), []
    values = {"store": "postgres", "database_url": database_url, "lake_path": LAKE}
    first = await build_runtime(
        settings(**values), storage=storage, on_writer_lost=lambda: lost.append("first")
    )
    try:
        second = await build_runtime(settings(**values), storage=storage)
        try:
            assert first.orchestration is not None and second.orchestration is not None
            assert first.orchestration.ownership.writable
            assert not second.orchestration.ownership.writable
            assert second.disk is not None
            with pytest.raises(LakeUnavailable) as refused:
                await second.disk.work(second.disk.locate("helio"), lambda: None)
            assert refused.value.context == {"reason": "writer_lock"}
            assert (await second.ready())["database"] is True
        finally:
            await second.close()
        await terminate_writer(database_url)
        assert await first.orchestration.ownership.check() is False
        assert lost == ["first"]
        assert first.disk is not None
        calls = list(storage.calls)
        with pytest.raises(LakeUnavailable):
            await first.disk.work(
                first.disk.locate("helio"), lambda: storage.calls.append(("x", LAKE))
            )
        assert storage.calls == calls
    finally:
        await first.close()
