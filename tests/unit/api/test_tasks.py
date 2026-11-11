"""Work that outlives its request: one task for each key, waits with a limit, repeated work."""

import asyncio

import pytest
import structlog

from huron.applications.api.disk import Tasks, repeat, wait_for
from tests.support.clock import LoopClock


class Boom(Exception):
    """The error of a task that fails."""


async def test_a_second_caller_of_a_key_joins_the_running_task() -> None:
    tasks: Tasks[str, int] = Tasks("work")
    release = asyncio.Event()
    starts: list[str] = []

    async def work(value: int) -> int:
        starts.append("start")
        await release.wait()
        return value

    first = tasks.start("a", lambda: work(1))
    assert tasks.start("a", lambda: work(2)) is first
    other = tasks.start("b", lambda: work(3))
    assert tasks.running("a") and tasks.running("b") and not tasks.running("c")
    release.set()
    assert await first == 1 and await other == 3
    await asyncio.sleep(0)
    assert not tasks.running("a")
    assert starts == ["start", "start"]


async def test_a_task_that_ended_is_not_joined() -> None:
    tasks: Tasks[str, int] = Tasks("work")

    async def value(result: int) -> int:
        return result

    assert await tasks.start("a", lambda: value(1)) == 1
    await asyncio.sleep(0)
    assert await tasks.start("a", lambda: value(2)) == 2


async def test_a_failed_task_is_logged_and_its_error_reaches_its_callers(
    loop_errors: list[dict[str, object]],
) -> None:
    tasks: Tasks[str, None] = Tasks("work")

    async def failing() -> None:
        raise Boom("no disk")

    with structlog.testing.capture_logs() as captured:
        task = tasks.start("a", failing)
        with pytest.raises(Boom):
            await task
        await asyncio.sleep(0)
    assert captured == [
        {
            "event": "task.failed",
            "log_level": "error",
            "work": "work",
            "key": "a",
            "error": "Boom('no disk')",
        }
    ]
    assert not tasks.running("a")
    assert loop_errors == []


async def test_close_cancels_and_awaits_every_running_task() -> None:
    tasks: Tasks[int, None] = Tasks("work")
    started = asyncio.Event()

    async def forever() -> None:
        started.set()
        await asyncio.Event().wait()

    running = [tasks.start(key, forever) for key in (1, 2)]
    await started.wait()
    with structlog.testing.capture_logs() as captured:
        await tasks.close()
    assert all(task.cancelled() for task in running)
    assert captured == []
    assert not tasks.running(1)
    await Tasks[int, None]("empty").close()


async def test_wait_for_gives_the_result_or_none_after_the_limit_and_never_cancels(
    loop_clock: LoopClock,
) -> None:
    release = asyncio.Event()

    async def slow() -> str:
        await release.wait()
        return "sealed"

    task = asyncio.create_task(slow())
    waiting = asyncio.create_task(wait_for(task, 20))
    await asyncio.sleep(0)
    loop_clock.advance(19.9)
    await asyncio.sleep(0)
    assert not waiting.done()
    loop_clock.advance(0.1)
    assert await waiting is None
    assert not task.done()
    caller = asyncio.create_task(wait_for(task, 20))
    await asyncio.sleep(0)
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    assert not task.cancelled()
    release.set()
    assert await wait_for(task, 20) == "sealed"


async def test_wait_for_raises_the_error_of_a_failed_task() -> None:
    async def failing() -> None:
        raise Boom("refused")

    task = asyncio.create_task(failing())
    with pytest.raises(Boom):
        await wait_for(task, 5)


async def test_repeat_runs_the_action_after_each_interval_and_logs_a_failed_run(
    loop_clock: LoopClock,
) -> None:
    runs: list[int] = []
    ran = asyncio.Event()

    async def action() -> None:
        runs.append(len(runs))
        ran.set()
        if len(runs) == 1:
            raise Boom("first run")

    with structlog.testing.capture_logs() as captured:
        loop = asyncio.create_task(repeat("cleanup", 600, action))
        await ran.wait()
        ran.clear()
        await asyncio.sleep(0)
        assert runs == [0]
        loop_clock.advance(600)
        await ran.wait()
        loop.cancel()
        with pytest.raises(asyncio.CancelledError):
            await loop
    assert runs == [0, 1]
    assert captured == [
        {
            "event": "task.failed",
            "log_level": "error",
            "work": "cleanup",
            "error": "Boom('first run')",
        }
    ]
