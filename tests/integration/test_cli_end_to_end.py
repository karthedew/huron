"""Section 1 of the plan, end to end: a real HTTP server over PostgreSQL and a temporary lake,
the real upload proxy and tusd in front of it, and the CLI on the host, every role doing its
part.

The service declares the organization helio, directly below the lake path. The storage
administrator prepares the lake with ``huron adm provision-orgs`` as the host user, who is the
service user. The directory verbs, the pushes, ``huron adm repair`` and ``huron adm check`` then
run end to end.
"""

import asyncio
import contextlib
import grp
import json
import os
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import uvicorn

from huron.applications.api.app import create_app
from huron.applications.api.runtime import Runtime, build_runtime
from huron.applications.cli.config import Config
from huron.core.metastore.postgres import PostgresStore
from huron.core.security.broker import TokenIssuer
from huron.pkg.clock import SystemClock
from tests.fakes.groups import FakeGroups
from tests.fakes.issuer import FakeIssuer
from tests.support.api import USERS, free_port, settings
from tests.support.cli import LoopThread
from tests.support.hostcli import HostCli
from tests.support.postgres import truncate
from tests.support.uploadstack import HOOK_TIMEOUT, UploadStack

pytestmark = pytest.mark.integration


class Stack:
    """A uvicorn server on a free port with a lake, the upload stack, and a CLI pointed at it.

    When a step of the start fails, the stack stops what it started, then raises.
    """

    def __init__(self, database_url: str, home: Path) -> None:
        self._cleanup = contextlib.ExitStack()
        try:
            self._start(database_url, home)
        except BaseException:
            self._cleanup.close()
            raise

    def login(self, user: str) -> None:
        ring = self.loop.call(self.runtime.ring())
        issuer = TokenIssuer(
            ring, self.clock, "https://huron.test", "huron", self.runtime.settings.token_ttl
        )
        token, claims = issuer.issue(user, user, USERS[user])
        self.cli.login(user, token, claims.exp.timestamp())

    def huron(self, *argv: str, expect: int = 0) -> str:
        return self.cli.huron(*argv, expect=expect)

    def close(self) -> None:
        """Stop the CLI, the upload stack, the server, the runtime and the loop, in this order."""
        self._cleanup.close()

    def _start(self, database_url: str, home: Path) -> None:
        self.lake = home / "lake"
        self.lake.mkdir()
        self.uploads = UploadStack(self.lake, home)
        self.loop = LoopThread()
        self._cleanup.callback(self.loop.stop)
        self.loop.call(truncate(database_url))
        store = PostgresStore(database_url)
        self.loop.call(store.connect())
        self.clock = SystemClock()
        helio = {"name": "helio", "groups": {"org_admin": ["helio-org-admins"]}}
        try:
            self.runtime: Runtime = self.loop.call(
                build_runtime(
                    settings(
                        store="postgres",
                        database_url=database_url,
                        lake_path=self.lake,
                        uploads_url=self.uploads.url,
                        upload_hook_timeout=HOOK_TIMEOUT,
                        service_group=grp.getgrgid(os.getgid()).gr_name,
                        organizations=[helio],
                    ),
                    store=store,
                    http=httpx.AsyncClient(transport=FakeIssuer().transport()),
                    groups=FakeGroups(USERS),
                    clock=self.clock,
                )
            )
        except BaseException:
            self.loop.call(store.close())
            raise
        self._cleanup.callback(lambda: self.loop.call(self.runtime.close()))
        self.port = free_port()
        config = uvicorn.Config(
            create_app(runtime=self.runtime),
            host="127.0.0.1",
            port=self.port,
            log_level="warning",
            lifespan="off",
        )
        self.server = uvicorn.Server(config)
        self.serving = asyncio.run_coroutine_threadsafe(self.server.serve(), self.loop.loop)
        self._cleanup.callback(self._stop_server)
        for _ in range(200):
            if self.server.started:
                break
            self.loop.call(asyncio.sleep(0.02))
        self._cleanup.callback(self.uploads.close)
        self.uploads.start(self.port)
        self.cli = HostCli(home / "cli", f"http://127.0.0.1:{self.port}", self.lake)
        self._cleanup.callback(self.cli.close)
        self.prompter = self.cli.prompter
        self.state = self.cli.state
        self.config_path = self.cli.config_path

    def _stop_server(self) -> None:
        self.server.should_exit = True
        self.serving.result(timeout=10)


@pytest.fixture
def stack(database_url: str, tmp_path: Path) -> Iterator[Stack]:
    home = tmp_path / "home"
    home.mkdir(parents=True)
    running = Stack(database_url, home)
    try:
        yield running
    finally:
        running.close()


def test_every_role_end_to_end(stack: Stack, tmp_path: Path) -> None:
    stack.login("alice")
    assert "missing" in stack.huron("adm", "verify-mounts", expect=1)
    stack.huron("adm", "provision-orgs")
    stack.huron("adm", "verify-mounts")
    assert (stack.lake / ".huron").is_file() and (stack.lake / "helio" / ".huron").is_file()
    stack.login("bob")
    stack.huron("create", "catalog", "heliophysics", "--org", "helio")
    stack.huron(
        "adm", "grant", "catalog_admin", "helio-catalog-admins", "--catalog", "heliophysics"
    )
    stack.login("carol")
    for role, group in (("contributor", "helio-contributors"), ("reader", "helio-readers")):
        stack.huron("adm", "grant", role, group, "--catalog", "heliophysics")
    stack.huron("create", "namespace", "heliophysics.solar-wind", "--allow-collections")
    schema = tmp_path / "helio.json"
    schema.write_text(
        json.dumps(
            {
                "type": "object",
                "required": ["mission"],
                "properties": {"mission": {"type": "string"}},
            }
        )
    )
    stack.login("bob")
    base = json.loads(stack.huron("-o", "json", "get", "schemas"))[0]["id"]
    stack.huron("adm", "publish", "schema", "helio", "helio", str(schema), "--extends", base)
    helio = json.loads(stack.huron("-o", "json", "get", "schemas", "helio"))[0]["id"]
    stack.login("carol")
    stack.huron("adm", "assign", "schema", helio, "--catalog", "heliophysics")

    stack.login("dave")
    stack.huron("catalog", "heliophysics")
    stack.prompter.answers.extend(["Run 7", "Solar wind", "parker", *([False] * 7)])
    stack.huron("create", "collection", "solar-wind.run7")
    directory = stack.lake / "helio" / "heliophysics" / "solar-wind" / "run7"
    assert json.loads((directory / "metadata.json").read_text())["metadata"]["mission"] == "parker"
    data = tmp_path / "data"
    data.mkdir()
    for name in ("a.txt", "b.txt", "c.txt"):
        (data / name).write_text(name)
    stack.huron("add", str(data), "--recursive")
    stack.huron("push", "-m", "three files")
    assert sorted(p.name for p in directory.iterdir()) == [
        "a.txt",
        "b.txt",
        "c.txt",
        "metadata.json",
    ]
    stack.prompter.answers.extend(
        [None, None, None, False, False, False, False, True, "wind, sun", False, False]
    )
    stack.huron("edit", "meta")
    stack.huron("publish", "meta")
    (data / "d.txt").write_text("d")
    stack.huron("add", str(data / "d.txt"))
    with stack.state.changing(Config.load(stack.config_path, {}).current_collection or "") as copy:
        copy.base_version = 3
    stack.huron("push", expect=6)
    stack.huron("pull")
    stack.huron("push")

    stack.login("erin")
    assert "run7" in stack.huron("--catalog", "heliophysics", "search", "-q", "run")
    listed = json.loads(stack.huron("-o", "json", "get", "files", "solar-wind.run7"))
    assert [f["rel_path"] for f in listed] == ["a.txt", "b.txt", "c.txt", "d.txt"]
    stack.huron("checkout", "solar-wind.run7")
    stack.huron("add", str(data / "a.txt"), "--as", "e.txt")
    stack.huron("push", expect=4)
    sidecar = json.loads((directory / "metadata.json").read_text())
    assert sidecar["metadata"]["keywords"] == ["wind", "sun"]

    stack.login("alice")
    repaired = stack.huron("adm", "repair", "heliophysics.solar-wind.run7")
    assert repaired == "The API changed nothing\n"
    assert json.loads(stack.huron("-o", "json", "adm", "check")) == []
