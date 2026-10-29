"""The ``huron`` console script."""

from __future__ import annotations

import os
import socket
import sys
import time
import webbrowser

import httpx
from rich.console import Console

from huron.applications.cli.app import run
from huron.applications.cli.config import Config, config_path
from huron.applications.cli.prompts import QuestionaryPrompter
from huron.applications.cli.services import Services
from huron.applications.cli.state import StateDir, state_root
from huron.core.storage.factory import storage_for
from huron.pkg.clock import SystemClock

__all__ = ["main"]


def main() -> None:
    """Build the real services from the environment and run the CLI."""
    if sys.platform == "win32":
        sys.stderr.write("huron: Windows is not supported; use a Linux or macOS machine\n")
        raise SystemExit(1)
    environ = dict(os.environ)
    path = config_path(environ)
    timeout = httpx.Timeout(30.0, connect=10.0)
    with httpx.Client(timeout=timeout, follow_redirects=False) as http:
        services = Services(
            environ=environ,
            config_path=path,
            config=Config.load(path, environ),
            state=StateDir(state_root(environ)),
            http=http,
            clock=SystemClock(),
            out=Console(),
            err=Console(stderr=True),
            prompter=QuestionaryPrompter(),
            sleep=time.sleep,
            open_browser=webbrowser.open,
            hostname=socket.gethostname(),
            storage_factory=lambda config: storage_for(config.acl_backend),
        )
        raise SystemExit(run(services, sys.argv[1:]))
