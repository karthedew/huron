"""Section 1 of the plan, end to end: a real HTTP server over PostgreSQL, the CLI over a
real directory standing in for the share, every role doing its part."""

import asyncio
import grp
import io
import json
import os
import socket
import subprocess
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import uvicorn
from rich.console import Console

from huron.applications.api.app import create_app
from huron.applications.api.runtime import Runtime, build_runtime
from huron.applications.cli.app import run
from huron.applications.cli.config import Config
from huron.applications.cli.services import Services
from huron.applications.cli.state import StateDir, Tokens
from huron.core.metastore.postgres import PostgresStore
from huron.core.security.broker import TokenIssuer
from huron.core.storage.factory import storage_for
from tests.fakes.groups import FakeGroups
from tests.fakes.issuer import FakeIssuer
from tests.fakes.prompter import ScriptedPrompter
from tests.support.api import INSTANCE_ID, USERS, settings
from tests.support.cli import LoopThread
from tests.support.clock import frozen
from tests.support.postgres import truncate

pytestmark = pytest.mark.integration
SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "init-root.sh"


class Stack:
    """A uvicorn server on a free port and a CLI pointed at it."""

    def __init__(self, database_url: str, home: Path) -> None:
        self.loop = LoopThread()
        self.loop.call(truncate(database_url))
        store = PostgresStore(database_url)
        self.loop.call(store.connect())
        self.clock = frozen()
        self.runtime: Runtime = self.loop.call(
            build_runtime(
                settings(store="postgres", database_url=database_url),
                store=store,
                http=httpx.AsyncClient(transport=FakeIssuer().transport()),
                groups=FakeGroups(USERS),
                clock=self.clock,
            )
        )
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        config = uvicorn.Config(
            create_app(runtime=self.runtime),
            host="127.0.0.1",
            port=self.port,
            log_level="warning",
            lifespan="off",
        )
        self.server = uvicorn.Server(config)
        self.serving = asyncio.run_coroutine_threadsafe(self.server.serve(), self.loop.loop)
        for _ in range(200):
            if self.server.started:
                break
            self.loop.call(asyncio.sleep(0.02))
        self.share = home / "share"
        self.share.mkdir()
        group = grp.getgrgid(os.getgid()).gr_name
        subprocess.run(
            [
                "bash",
                str(SCRIPT),
                str(self.share),
                group,
                f"http://127.0.0.1:{self.port}",
                str(INSTANCE_ID),
            ],
            check=True,
            capture_output=True,
        )
        self.config_path = home / "config.yaml"
        Config(
            api_url=f"http://127.0.0.1:{self.port}",
            issuer="https://idp.test",
            mount_prefix=str(self.share),
            acl_backend="none",
        ).save(self.config_path)
        self.state = StateDir(home / "state")
        self.http = httpx.Client(timeout=10)
        self.prompter = ScriptedPrompter()

    def login(self, user: str) -> None:
        ring = self.loop.call(self.runtime.ring())
        issuer = TokenIssuer(
            ring, self.clock, "https://huron.test", "huron", self.runtime.settings.token_ttl
        )
        token, claims = issuer.issue(user, user, USERS[user])
        self.state.write_tokens(Tokens(token, claims.exp.timestamp(), user, None))

    def huron(self, *argv: str, expect: int = 0) -> str:
        out, err = io.StringIO(), io.StringIO()
        services = Services(
            environ={},
            config_path=self.config_path,
            config=Config.load(self.config_path, {}),
            state=self.state,
            http=self.http,
            clock=self.clock,
            out=Console(file=out, width=200, color_system=None),
            err=Console(file=err, width=200, color_system=None),
            prompter=self.prompter,
            sleep=lambda _: None,
            open_browser=lambda _: None,
            hostname="ws1",
            storage_factory=lambda config: storage_for(config.acl_backend),
        )
        code = run(services, list(argv))
        assert code == expect, f"huron {' '.join(argv)} → {code}\n{err.getvalue()}"
        return out.getvalue()

    def close(self) -> None:
        self.server.should_exit = True
        self.serving.result(timeout=10)
        self.http.close()
        self.loop.call(self.runtime.close())
        self.loop.stop()


@pytest.fixture
def stack(database_url: str, tmp_path: Path) -> Iterator[Stack]:
    running = Stack(database_url, tmp_path)
    yield running
    running.close()


def test_every_role_end_to_end(stack: Stack, tmp_path: Path) -> None:
    stack.login("alice")
    stack.huron("platform", "verify-root")
    stack.huron("org", "create", "helio")
    stack.huron("org", "grant", "helio", "helio-org-admins")
    stack.login("bob")
    stack.huron("catalog", "create", "helio", "heliophysics")
    stack.huron("catalog", "grant", "heliophysics", "catalog_admin", "helio-catalog-admins")
    stack.login("carol")
    for role, group in (("contributor", "helio-contributors"), ("reader", "helio-readers")):
        stack.huron("catalog", "grant", "heliophysics", role, group)
    stack.huron("namespace", "create", "heliophysics.solar-wind", "--allow-collections")
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
    base = json.loads(stack.huron("-o", "json", "schema", "list"))[0]["id"]
    stack.huron("schema", "publish", "helio", "helio", str(schema), "--extends", base)
    helio = json.loads(stack.huron("-o", "json", "schema", "list", "helio"))[0]["id"]
    stack.login("carol")
    stack.huron("schema", "assign", "heliophysics", helio)

    stack.login("dave")
    stack.huron("catalog", "use", "heliophysics")
    stack.prompter.answers.extend(["Run 7", "Solar wind", "parker", *([False] * 7)])
    stack.huron("collection", "create", "solar-wind.run7")
    directory = stack.share / "helio" / "heliophysics" / "solar-wind" / "run7"
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
    stack.huron("meta", "edit")
    stack.huron("meta", "publish")
    (data / "d.txt").write_text("d")
    stack.huron("add", str(data / "d.txt"))
    copy = stack.state.read_copy(Config.load(stack.config_path, {}).current_collection or "")
    assert copy is not None
    stack.state.write_copy(copy.__class__(copy.collection_id, copy.identifier, 3, copy.path))
    stack.huron("push", expect=6)
    stack.huron("pull")
    stack.huron("push")

    stack.login("erin")
    assert "run7" in stack.huron("search", "heliophysics", "-q", "run")
    listed = json.loads(stack.huron("-o", "json", "files", "solar-wind.run7"))
    assert [f["rel_path"] for f in listed] == ["a.txt", "b.txt", "c.txt", "d.txt"]
    stack.huron("checkout", "solar-wind.run7")
    stack.huron("add", str(data / "a.txt"), "--as", "e.txt")
    stack.huron("push", expect=4)
    sidecar = json.loads((directory / "metadata.json").read_text())
    assert sidecar["metadata"]["keywords"] == ["wind", "sun"]
