"""In-process locks per path."""

import asyncio

import pytest

from huron.core.storage import LakePath, PathLocks

TARGET = LakePath.of("helio", "heliophysics")


async def test_holders_of_one_path_take_turns() -> None:
    locks = PathLocks()
    order: list[str] = []
    first_inside = asyncio.Event()
    release = asyncio.Event()

    async def first() -> None:
        async with locks.hold(TARGET):
            first_inside.set()
            await release.wait()
            order.append("first")

    async def second() -> None:
        await first_inside.wait()
        async with locks.hold(TARGET):
            order.append("second")

    running = [asyncio.create_task(first()), asyncio.create_task(second())]
    await first_inside.wait()
    await asyncio.sleep(0)
    assert order == [] and len(locks) == 1
    release.set()
    await asyncio.gather(*running)
    assert order == ["first", "second"]


async def test_other_paths_do_not_wait() -> None:
    locks = PathLocks()
    async with locks.hold(TARGET):
        async with asyncio.timeout(5):
            async with locks.hold(TARGET.parent):
                assert len(locks) == 2


async def test_a_path_is_forgotten_once_released_even_after_an_error() -> None:
    locks = PathLocks()
    with pytest.raises(RuntimeError):
        async with locks.hold(TARGET):
            raise RuntimeError("disk work failed")
    assert len(locks) == 0
    async with asyncio.timeout(5), locks.hold(TARGET):
        assert len(locks) == 1
    assert len(locks) == 0


async def test_a_cancelled_waiter_is_forgotten() -> None:
    locks = PathLocks()

    async def wait() -> None:
        async with locks.hold(TARGET):
            pytest.fail("the waiter entered a held lock")

    async with locks.hold(TARGET):
        waiter = asyncio.create_task(wait())
        await asyncio.sleep(0)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert len(locks) == 1
    assert len(locks) == 0
