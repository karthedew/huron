"""Work that outlives the request that starts it: one task for each key, and repeated work.

A seal or a publication must not stop when tusd's hook or the client goes away. So the API runs
it in an ``asyncio`` task that a registry holds, and a caller only waits for that task. The
registry keeps a reference to each task until the task ends, so the garbage collector never
drops one, and it logs the error of a task that fails. Shutdown cancels and awaits every task.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Coroutine, Hashable

__all__ = ["Tasks", "repeat", "wait_for"]

_log = structlog.get_logger(__name__)


class Tasks[K: Hashable, T]:
    """At most one running task for each key; ``name`` names the work in the log."""

    def __init__(self, name: str) -> None:
        self._name = name
        self._tasks: dict[K, asyncio.Task[T]] = {}

    def start(self, key: K, work: Callable[[], Coroutine[Any, Any, T]]) -> asyncio.Task[T]:
        """The running task of ``key``, or a new task that runs ``work()`` when none runs.

        A second caller of a key thus joins the task of the first caller. A task that ended
        is not joined: the next call starts a new one.
        """
        running = self._tasks.get(key)
        if running is not None:
            return running
        task = asyncio.create_task(work(), name=f"{self._name}:{key}")
        self._tasks[key] = task
        task.add_done_callback(lambda ended: self._ended(key, ended))
        return task

    def running(self, key: K) -> bool:
        """Whether a task of ``key`` runs now."""
        return key in self._tasks

    async def close(self) -> None:
        """Cancel every running task and wait until each one ended."""
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def _ended(self, key: K, task: asyncio.Task[T]) -> None:
        if self._tasks.get(key) is task:
            del self._tasks[key]
        if not task.cancelled() and (error := task.exception()) is not None:
            _log.error("task.failed", work=self._name, key=str(key), error=repr(error))


async def wait_for[T](task: asyncio.Task[T], timeout: float) -> T | None:
    """The result of ``task`` when it ends within ``timeout`` seconds, else ``None``.

    The wait never cancels ``task``, also when the caller is cancelled. A task that failed
    raises its error here.
    """
    done, _ = await asyncio.wait({task}, timeout=timeout)
    return task.result() if done else None


async def repeat(name: str, interval: float, action: Callable[[], Awaitable[object]]) -> None:
    """Await ``action()``, then wait ``interval`` seconds, again and again until cancelled.

    A run that fails is logged with ``name``, and the next run follows after the interval.
    """
    while True:
        try:
            await action()
        except Exception as error:
            _log.error("task.failed", work=name, error=repr(error))
        await asyncio.sleep(interval)
