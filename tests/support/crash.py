"""The API in a child process that stops at a named point, then a kill and a new start.

The child is the real application: ``build_runtime`` over PostgreSQL, the POSIX storage of a
temporary lake and the writer lock, served by uvicorn on a port that the test chooses. Two seams
stop it, and nothing else differs from the service:

- :class:`StoppingStorage` is the POSIX storage. It stops before or after a copy, a link, a
  rename or an unlink.
- :class:`StoppingStore` is the PostgreSQL store. It stops before or after the commit of the
  transaction that records a seal, accepts a commit request, marks an entry done or finalizes a
  request. "Before" stops in the transaction, so a kill rolls it back.

The test arms one point with a file in the child's state directory (:meth:`ChildApi.arm`). The
child writes a second file when it stops there, and then waits without end. The test kills it
with ``SIGKILL`` and starts a new child, which recovers by the application's own means: its
startup, its periodic loop, the writer lock and the API's own seal check. Every wait of the test
is on state that it can see, with :data:`DEADLINE`.

The child runs as ``python -m tests.support.crash <configuration file>``.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections import Counter
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import asyncpg
import httpx
import uvicorn

from huron.applications.api.app import create_app
from huron.applications.api.logs import configure_logging
from huron.applications.api.runtime import build_runtime
from huron.core.lake.bootstrap import LakeSettings, build_lake
from huron.core.lake.uploads.models import ObjectState
from huron.core.metastore.postgres import WRITER_APPLICATION, PostgresStore, PostgresTransaction
from huron.core.security.broker import KeyRing
from huron.core.storage import LakePath, Outcome, SealedFile, StorageError
from huron.core.storage.posix import PosixStorage
from huron.pkg.clock import SystemClock
from tests.fakes.groups import FakeGroups
from tests.fakes.issuer import FakeIssuer
from tests.support.api import USERS, free_port, issue_token, settings

#: How long a wait on the child's state lasts before the test fails, in seconds.
DEADLINE = 30.0
#: How long a wait sleeps between two looks at the state, in seconds.
POLL_INTERVAL = 0.02
#: The file in the state directory that arms a point.
ARM_FILE = "arm.json"
#: The file in the state directory that the child writes when it stops at the armed point.
STOPPED_FILE = "stopped.json"
#: The directory from which the child imports ``tests``: the repository root.
ROOT = Path(__file__).resolve().parents[2]


class Point(StrEnum):
    """A named point where the child can stop.

    The first four are storage calls, the last four are the commits of transactions.
    """

    COPY = "copy"
    LINK = "link"
    RENAME = "rename"
    UNLINK = "unlink"
    SEAL_COMMIT = "seal commit"
    ACCEPTANCE = "acceptance"
    ENTRY_DONE = "entry done"
    FINAL = "final transaction"


class Phase(StrEnum):
    """Before or after the call or the commit of a point."""

    BEFORE = "before"
    AFTER = "after"


class Action(StrEnum):
    """What the child does at an armed point.

    ``stop``: signal, then wait without end. ``pause``: signal, then wait until the test
    disarms the point, then go on (storage points only). ``fail``: raise a ``StorageError``
    at each call while the point is armed (storage points, before the call, only).
    """

    STOP = "stop"
    PAUSE = "pause"
    FAIL = "fail"


@dataclass(frozen=True, slots=True)
class Arm:
    """The point where the child acts, at the ``nth`` call after the arm.

    ``scope`` limits a link, a rename or an unlink to the paths below that lake path, so that a
    readiness probe or a cleanup does not count.
    """

    point: Point
    phase: Phase = Phase.BEFORE
    nth: int = 1
    action: Action = Action.STOP
    scope: str = ""

    def dumps(self) -> str:
        """The arm as JSON."""
        return json.dumps(asdict(self))

    @classmethod
    def loads(cls, text: str) -> Arm:
        """The arm that :meth:`dumps` wrote."""
        document = json.loads(text)
        return cls(
            Point(document["point"]),
            Phase(document["phase"]),
            int(document["nth"]),
            Action(document["action"]),
            str(document["scope"]),
        )


class Stops:
    """The child's side of the arm: it counts the calls of the armed point and acts on it."""

    def __init__(self, state: Path) -> None:
        self._arm = state / ARM_FILE
        self._stopped = state / STOPPED_FILE
        self._hits: Counter[Point] = Counter()
        self._lock = threading.Lock()

    def armed(self) -> Arm | None:
        """The armed point now, or ``None``."""
        try:
            return Arm.loads(self._arm.read_text())
        except FileNotFoundError:
            return None

    def reached(self, point: Point, phase: Phase, location: LakePath | None = None) -> None:
        """Act on a storage call at ``location`` when it is the armed one; it runs in a disk
        thread, so a stop blocks that thread.
        """
        arm = self._due(point, phase, location)
        if arm is None:
            return
        if arm.action is Action.FAIL:
            raise StorageError("the test makes this storage call fail", {"point": str(point)})
        self._signal(arm)
        if arm.action is Action.PAUSE:
            while self.armed() is not None:
                time.sleep(POLL_INTERVAL)
            return
        threading.Event().wait()

    async def reached_commit(self, point: Point, phase: Phase) -> None:
        """Stop at the commit of a transaction when it is the armed one."""
        arm = self._due(point, phase, None)
        if arm is not None:
            self._signal(arm)
            await asyncio.Event().wait()

    def _due(self, point: Point, phase: Phase, location: LakePath | None) -> Arm | None:
        arm = self.armed()
        if arm is None or arm.point is not point:
            return None
        if location is not None and arm.scope and not str(location).startswith(f"{arm.scope}/"):
            return None
        with self._lock:
            if phase is Phase.BEFORE:
                self._hits[point] += 1
            hit = self._hits[point]
        if arm.phase is not phase:
            return None
        return arm if arm.action is Action.FAIL or hit == arm.nth else None

    def _signal(self, arm: Arm) -> None:
        written = self._stopped.with_suffix(".tmp")
        written.write_text(arm.dumps())
        os.replace(written, self._stopped)


class StoppingStorage(PosixStorage):
    """The POSIX storage of the lake at ``root``, with the storage points of ``stops``."""

    def __init__(self, root: Path, stops: Stops) -> None:
        super().__init__(root)
        self._stops = stops

    def copy_sealed(
        self, source: LakePath, destination: LakePath, expected_size: int
    ) -> SealedFile:
        """Copy as the POSIX storage does, at the point ``copy``."""
        self._stops.reached(Point.COPY, Phase.BEFORE)
        sealed = super().copy_sealed(source, destination, expected_size)
        self._stops.reached(Point.COPY, Phase.AFTER)
        return sealed

    def link_once(self, source: LakePath, destination: LakePath) -> None:
        """Link as the POSIX storage does, at the point ``link``."""
        self._stops.reached(Point.LINK, Phase.BEFORE, destination)
        super().link_once(source, destination)
        self._stops.reached(Point.LINK, Phase.AFTER, destination)

    def rename(self, source: LakePath, destination: LakePath) -> None:
        """Rename as the POSIX storage does, at the point ``rename``."""
        self._stops.reached(Point.RENAME, Phase.BEFORE, destination)
        super().rename(source, destination)
        self._stops.reached(Point.RENAME, Phase.AFTER, destination)

    def remove_file(self, location: LakePath, *, inode: int | None = None) -> Outcome:
        """Remove as the POSIX storage does, at the point ``unlink``."""
        self._stops.reached(Point.UNLINK, Phase.BEFORE, location)
        outcome = super().remove_file(location, inode=inode)
        self._stops.reached(Point.UNLINK, Phase.AFTER, location)
        return outcome


class StoppingStore(PostgresStore):
    """The PostgreSQL store over ``dsn``, with the transaction points of ``stops``.

    A transaction is the one of a point when it calls the adapter method of that point: the
    object update that records a seal, the entries of an accepted request, the mark of a done
    entry, or the commit row of a final transaction.
    """

    def __init__(self, dsn: str, stops: Stops) -> None:
        super().__init__(dsn, pool_size=4)
        self._stops = stops

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[PostgresTransaction]:
        """A transaction that stops before or after its commit when it is the armed one."""
        reached: set[Point] = set()
        async with super().transaction() as tx:
            self._watch(tx, reached)
            yield tx
            for point in reached:
                await self._stops.reached_commit(point, Phase.BEFORE)
        for point in reached:
            await self._stops.reached_commit(point, Phase.AFTER)

    def _watch(self, tx: PostgresTransaction, reached: set[Point]) -> None:
        arm = self._stops.armed()
        if arm is None or arm.point not in _WATCHED:
            return
        area_name, method, matches = _WATCHED[arm.point]
        area = getattr(tx, area_name)
        real = getattr(area, method)

        async def watched(*args: Any, **kwargs: Any) -> Any:
            result = await real(*args, **kwargs)
            if matches(args):
                reached.add(arm.point)
            return result

        setattr(area, method, watched)


@dataclass(frozen=True, slots=True)
class Facts:
    """The rows of a collection: its version, file count and pending request, each file row by
    path as its sha256 and inode, and the versions of the commit audit records, oldest first.
    """

    version: int
    file_count: int
    pending_request_id: uuid.UUID | None
    files: dict[str, tuple[str, int | None]]
    commit_versions: list[int]


async def read_facts(database_url: str, collection_id: str) -> Facts:
    """The rows of the collection ``collection_id`` now."""
    connection = await asyncpg.connect(database_url)
    try:
        row = await connection.fetchrow(
            "select version, file_count, pending_request_id from huron.collections where id = $1",
            uuid.UUID(collection_id),
        )
        files = await connection.fetch(
            "select rel_path, sha256, inode from huron.files where collection_id = $1",
            uuid.UUID(collection_id),
        )
        audits = await connection.fetch(
            "select detail from huron.audit where action = 'collection.commit'"
            " and object_id = $1 order by id",
            uuid.UUID(collection_id),
        )
    finally:
        await connection.close()
    assert row is not None
    return Facts(
        row["version"],
        row["file_count"],
        row["pending_request_id"],
        {f["rel_path"]: (f["sha256"], f["inode"]) for f in files},
        [json.loads(a["detail"])["version"] for a in audits],
    )


async def object_count(database_url: str, upload_id: str) -> int:
    """How many ``objects`` rows name ``upload_id``."""
    connection = await asyncpg.connect(database_url)
    try:
        count = await connection.fetchval(
            "select count(*) from huron.objects where upload_id = $1", uuid.UUID(upload_id)
        )
    finally:
        await connection.close()
    return int(count)


async def until(check: Callable[[], Awaitable[bool]], what: str) -> None:
    """Wait until ``check()`` is true; fail with ``what`` after :data:`DEADLINE`."""
    deadline = time.monotonic() + DEADLINE
    while not await check():
        if time.monotonic() > deadline:
            raise AssertionError(f"not true within {DEADLINE} s: {what}")
        await asyncio.sleep(POLL_INTERVAL)


class ChildApi:
    """The API in a child process over ``database_url`` and the lake ``lake``.

    ``state`` holds the child's configuration, its log, the arm and the stop signal.
    ``overrides`` are more settings of the child, each a value that JSON can hold, such as
    ``uploads_url``. The object calls the child as one of the test users
    (:class:`~tests.support.api.Caller`), and keeps that role over each new start:
    :attr:`client` then names the new child.
    """

    def __init__(self, database_url: str, lake: Path, state: Path, **overrides: Any) -> None:
        state.mkdir(parents=True, exist_ok=True)
        self._database_url = database_url
        self._lake = lake
        self._state = state
        self._overrides = overrides
        self._settings = settings(
            store="postgres", database_url=database_url, lake_path=lake, **overrides
        )
        self._process: subprocess.Popen[bytes] | None = None
        self._client: httpx.AsyncClient | None = None
        self._ring: KeyRing | None = None
        self._starts = 0

    @property
    def database_url(self) -> str:
        """The database of the child."""
        return self._database_url

    @property
    def lake(self) -> Path:
        """The lake directory of the child."""
        return self._lake

    @property
    def client(self) -> httpx.AsyncClient:
        """The client of the running child."""
        assert self._client is not None, "the child API is not running"
        return self._client

    async def headers(self, user: str, **extra: str) -> dict[str, str]:
        """Authorization headers for ``user``, with a token from the key ring in the database."""
        if self._ring is None:
            self._ring = await _key_ring(self._database_url, self._settings.platform_admin_group)
        token = issue_token(self._ring, SystemClock(), self._settings, user)
        return {"Authorization": f"Bearer {token}", **extra}

    async def start(self) -> None:
        """Start a child on a free port; return when it is ready and holds the writer lock."""
        if self._client is not None:
            await self._client.aclose()
        port = free_port()
        configuration = self._state / f"child-{self._starts}.json"
        configuration.write_text(
            json.dumps(
                {
                    "database_url": self._database_url,
                    "lake": str(self._lake),
                    "state": str(self._state),
                    "port": port,
                    "overrides": self._overrides,
                }
            )
        )
        log = self._log()
        with log.open("wb") as output:
            self._process = subprocess.Popen(
                [sys.executable, "-m", "tests.support.crash", str(configuration)],
                cwd=ROOT,
                stdout=output,
                stderr=subprocess.STDOUT,
                env=_environment(),
            )
        self._starts += 1
        self._client = httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=DEADLINE)
        await until(self._ready, "the child API answers that it is ready")
        await until(lambda: self._writers(1), "the child API holds the writer lock")

    def arm(self, arm: Arm) -> None:
        """Arm ``arm`` in the running child."""
        written = self._state / f"{ARM_FILE}.tmp"
        written.write_text(arm.dumps())
        os.replace(written, self._state / ARM_FILE)

    def disarm(self) -> None:
        """Remove the arm and the stop signal: a paused child goes on, a new child stops nowhere."""
        (self._state / ARM_FILE).unlink(missing_ok=True)
        (self._state / STOPPED_FILE).unlink(missing_ok=True)

    async def stopped(self) -> Arm:
        """Wait until the child acts at the armed point; the arm that it signalled."""
        signal_file = self._state / STOPPED_FILE

        async def signalled() -> bool:
            self._require_running()
            return signal_file.exists()

        await until(signalled, "the child API reaches the armed point")
        return Arm.loads(signal_file.read_text())

    async def kill(self) -> None:
        """Kill the child with ``SIGKILL``; return when its writer session has ended."""
        process, self._process = self._process, None
        assert process is not None, "the child API is not running"
        process.kill()
        process.wait(DEADLINE)
        await until(lambda: self._writers(0), "the writer session of the killed child ends")

    async def restart(self, *interrupted: asyncio.Task[httpx.Response]) -> None:
        """Kill the child, check that no request of ``interrupted`` got an answer, disarm and
        start a new child.
        """
        await self.kill()
        for task in interrupted:
            with contextlib.suppress(httpx.TransportError):
                answer = await task
                raise AssertionError(f"an interrupted request got an answer: {answer.text}")
        self.disarm()
        await self.start()

    async def close(self) -> None:
        """Stop the child (``SIGTERM``, then ``SIGKILL`` after :data:`DEADLINE`) and the client."""
        process, self._process = self._process, None
        if process is not None:
            process.send_signal(signal.SIGTERM)
            try:
                process.wait(DEADLINE)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(DEADLINE)
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _log(self) -> Path:
        return self._state / f"child-{self._starts}.log"

    def _require_running(self) -> None:
        process = self._process
        assert process is not None, "the child API is not running"
        if process.poll() is not None:
            log = (self._state / f"child-{self._starts - 1}.log").read_text()
            raise AssertionError(f"the child API ended with {process.returncode}:\n{log}")

    async def _ready(self) -> bool:
        self._require_running()
        try:
            answer = await self.client.get("/readyz")
        except httpx.TransportError:
            return False
        return answer.status_code == 200

    async def _writers(self, expected: int) -> bool:
        connection = await asyncpg.connect(self._database_url)
        try:
            count = await connection.fetchval(
                "select count(*) from pg_stat_activity"
                " where application_name = $1 and datname = current_database()",
                WRITER_APPLICATION,
            )
        finally:
            await connection.close()
        return bool(count == expected)


def main(argv: list[str]) -> None:
    """Run the child API with the configuration file ``argv[1]`` until a signal ends it."""
    configuration = json.loads(Path(argv[1]).read_text())
    asyncio.run(_serve(configuration))


_WATCHED: dict[Point, tuple[str, str, Callable[[tuple[Any, ...]], bool]]] = {
    Point.SEAL_COMMIT: (
        "objects",
        "update",
        lambda args: getattr(args[0], "state", None) is ObjectState.SEALED,
    ),
    Point.ACCEPTANCE: ("commit_requests", "insert_entries", lambda _: True),
    Point.ENTRY_DONE: ("commit_requests", "mark_done", lambda _: True),
    Point.FINAL: ("commits", "insert", lambda _: True),
}
"""The adapter method that marks the transaction of each transaction point, and the test of
its arguments."""


async def _serve(configuration: dict[str, Any]) -> None:
    """Build the real runtime with the two stopping seams and serve it."""
    state, lake = Path(configuration["state"]), Path(configuration["lake"])
    stops = Stops(state)
    store = StoppingStore(configuration["database_url"], stops)
    await store.connect()
    service_settings = settings(
        store="postgres",
        database_url=configuration["database_url"],
        lake_path=lake,
        **configuration["overrides"],
    )
    configure_logging(service_settings.log_level)
    runtime = await build_runtime(
        service_settings,
        store=store,
        http=httpx.AsyncClient(transport=FakeIssuer().transport()),
        groups=FakeGroups(USERS),
        storage=StoppingStorage(lake, stops),
    )
    config = uvicorn.Config(
        create_app(runtime=runtime),
        host="127.0.0.1",
        port=int(configuration["port"]),
        log_level="warning",
        access_log=False,
    )
    try:
        await uvicorn.Server(config).serve()
    finally:
        await runtime.close()


async def _key_ring(database_url: str, platform_admin_group: str) -> KeyRing:
    store = PostgresStore(database_url, pool_size=1)
    await store.connect()
    try:
        lake = build_lake(store, SystemClock(), LakeSettings(platform_admin_group))
        return await lake.keys.ring()
    finally:
        await store.close()


def _environment() -> dict[str, str]:
    """The child's environment: this one without the service configuration of the shell."""
    return {name: value for name, value in os.environ.items() if not name.startswith("HURON_")}


if __name__ == "__main__":
    main(sys.argv)
