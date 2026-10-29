"""Run the CLI against an in-process service, a fake identity provider and a chosen storage."""

import asyncio
import io
import threading
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import httpx
from rich.console import Console

from huron.applications.api.app import create_app
from huron.applications.api.runtime import Runtime, build_runtime
from huron.applications.cli.app import run
from huron.applications.cli.config import Config
from huron.applications.cli.services import Services
from huron.applications.cli.state import StateDir, Tokens
from huron.core.metastore.store import MemoryStore
from huron.core.security.broker import TokenIssuer
from tests.fakes.groups import FakeGroups
from tests.fakes.issuer import ISSUER, FakeIssuer
from tests.fakes.prompter import ScriptedPrompter
from tests.support.api import USERS, settings
from tests.support.clock import START, frozen

API = "http://huron.test"


@dataclass(frozen=True)
class Result:
    """What one CLI run produced."""

    exit_code: int
    stdout: str
    stderr: str


class LoopThread:
    """An event loop on its own thread, for running the async service under a sync client."""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self._thread.start()

    def call[T](self, coroutine: Coroutine[Any, Any, T]) -> T:
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop).result(timeout=30)

    def stop(self) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)
        self._thread.join(timeout=5)


class SyncASGITransport(httpx.BaseTransport):
    """A synchronous transport that hands requests to an ASGI app on the loop thread."""

    def __init__(self, loop: LoopThread, app: Any) -> None:
        self._loop = loop
        self._inner = httpx.ASGITransport(app=app)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        async def send() -> httpx.Response:
            body = request.read()
            forwarded = httpx.Request(
                request.method, request.url, headers=request.headers, content=body
            )
            response = await self._inner.handle_async_request(forwarded)
            content = await response.aread()
            return httpx.Response(response.status_code, headers=response.headers, content=content)

        return self._loop.call(send())


class Router(httpx.BaseTransport):
    """Send identity-provider requests to the fake issuer and the rest to the service."""

    def __init__(self, issuer: FakeIssuer, service: httpx.BaseTransport) -> None:
        self._issuer = httpx.MockTransport(issuer.handler)
        self._service = service
        self.fail_commits: str | None = None

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "idp.test":
            return self._issuer.handle_request(request)
        if self.fail_commits and request.method == "POST" and request.url.path.endswith("/commits"):
            mode, self.fail_commits = self.fail_commits, None
            if mode == "before":
                raise httpx.ConnectError("connection refused", request=request)
            self._service.handle_request(request)
            raise httpx.ReadError("connection reset", request=request)
        return self._service.handle_request(request)


class Cli:
    """A CLI wired to an in-process service; ``run`` executes one command line."""

    def __init__(
        self, home: Path, storage_factory: Callable[[Config], Any], mount_prefix: Path
    ) -> None:
        self.loop = LoopThread()
        self.issuer = FakeIssuer()
        self.issuer.now = START.timestamp()
        self.clock = frozen()
        self.runtime: Runtime = self.loop.call(
            build_runtime(
                settings(),
                store=MemoryStore(),
                http=httpx.AsyncClient(transport=self.issuer.transport()),
                groups=FakeGroups(USERS),
                clock=self.clock,
            )
        )
        self.router = transport = Router(
            self.issuer, SyncASGITransport(self.loop, create_app(runtime=self.runtime))
        )
        self.http = httpx.Client(transport=transport)
        self.prompter = ScriptedPrompter()
        self.opened: list[str] = []
        self.slept: list[float] = []
        self.home = home
        config = Config(api_url=API, issuer=ISSUER, mount_prefix=str(mount_prefix))
        self.config_path = home / "config" / "huron" / "config.yaml"
        config.save(self.config_path)
        self.state = StateDir(home / "state" / "huron")
        self.storage_factory = storage_factory
        self.environ: dict[str, str] = {}

    def services(self) -> tuple[Services, io.StringIO, io.StringIO]:
        out, err = io.StringIO(), io.StringIO()
        services = Services(
            environ=self.environ,
            config_path=self.config_path,
            config=Config.load(self.config_path, self.environ),
            state=self.state,
            http=self.http,
            clock=self.clock,
            out=Console(file=out, width=200, color_system=None, soft_wrap=True),
            err=Console(file=err, width=200, color_system=None, soft_wrap=True),
            prompter=self.prompter,
            sleep=self.slept.append,
            open_browser=self.opened.append,
            hostname="ws1",
            storage_factory=self.storage_factory,
        )
        return services, out, err

    def run(self, *argv: str) -> Result:
        services, out, err = self.services()
        code = run(services, list(argv))
        return Result(code, out.getvalue(), err.getvalue())

    def ok(self, *argv: str) -> Result:
        result = self.run(*argv)
        assert result.exit_code == 0, (
            f"huron {' '.join(argv)} → {result.exit_code}\n{result.stderr}"
        )
        return result

    def login_as(self, user: str) -> None:
        ring = self.loop.call(self.runtime.ring())
        issuer = TokenIssuer(
            ring,
            self.clock,
            self.runtime.settings.issuer,
            self.runtime.settings.audience,
            self.runtime.settings.token_ttl,
        )
        token, claims = issuer.issue(user, user.title(), USERS[user])
        self.state.write_tokens(Tokens(token, claims.exp.timestamp(), user, f"refresh-{user}"))

    def config_current(self) -> str:
        current = Config.load(self.config_path, {}).current_collection
        assert current is not None
        return current

    def configure(self, **values: Any) -> None:
        config = Config.load(self.config_path, {})
        replace(config, **values).save(self.config_path)

    def close(self) -> None:
        self.http.close()
        self.loop.call(self.runtime.close())
        self.loop.stop()
