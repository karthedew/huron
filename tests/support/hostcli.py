"""The CLI on the host against a running API over real HTTP, as a test user."""

from __future__ import annotations

import io
import time
from collections.abc import Callable
from pathlib import Path

import httpx
from rich.console import Console

from huron.applications.cli.app import run
from huron.applications.cli.config import Config
from huron.applications.cli.localstate import LocalState, Tokens
from huron.applications.cli.services import Services
from huron.core.storage.posix import PosixStorage
from huron.pkg.clock import Clock, SystemClock
from tests.fakes.prompter import ScriptedPrompter

__all__ = ["HostCli"]


class HostCli:
    """The CLI with its configuration and state in ``home``, for the API at ``api_url``.

    ``mount_prefix`` is the lake path on this machine. The CLI waits with ``sleep`` and reads
    the time from ``clock``. :meth:`login` stores a Huron token as ``huron login`` does.
    """

    def __init__(
        self,
        home: Path,
        api_url: str,
        mount_prefix: Path,
        *,
        clock: Clock | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config_path = home / "config.yaml"
        Config(api_url=api_url, issuer="https://idp.test", mount_prefix=str(mount_prefix)).save(
            self.config_path
        )
        self.state = LocalState(home / "state")
        self.prompter = ScriptedPrompter()
        self._http = httpx.Client(timeout=30)
        self._clock = clock or SystemClock()
        self._sleep = sleep

    def login(self, subject: str, token: str, expires_at: float) -> None:
        """Store ``token`` of ``subject``, valid until ``expires_at`` (a POSIX time)."""
        self.state.write_tokens(Tokens(token, expires_at, subject, None))

    def huron(self, *argv: str, expect: int = 0) -> str:
        """Run ``huron argv``; check that it exits with ``expect`` and return its output."""
        out, err = io.StringIO(), io.StringIO()
        services = Services(
            environ={},
            config_path=self.config_path,
            config=Config.load(self.config_path, {}),
            state=self.state,
            http=self._http,
            clock=self._clock,
            out=Console(file=out, width=200, color_system=None),
            err=Console(file=err, width=200, color_system=None),
            prompter=self.prompter,
            sleep=self._sleep,
            open_browser=lambda _: None,
            hostname="ws1",
            storage_factory=PosixStorage,
        )
        code = run(services, list(argv))
        assert code == expect, f"huron {' '.join(argv)} → {code}\n{out.getvalue()}{err.getvalue()}"
        return out.getvalue() + err.getvalue()

    def close(self) -> None:
        """Close the HTTP client."""
        self._http.close()
