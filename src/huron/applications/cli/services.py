"""Services: the one place the CLI's collaborators are assembled."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from rich.console import Console

from huron.applications.cli.client import ApiClient
from huron.applications.cli.config import Config
from huron.applications.cli.errors import UsageError
from huron.applications.cli.localstate import LocalState
from huron.applications.cli.login import Oidc, Session
from huron.applications.cli.mount import Mount
from huron.applications.cli.output import OutputFormat
from huron.applications.cli.prompts import Prompter
from huron.core.storage import ShareReader, Storage
from huron.core.storage.posix import PosixStorage
from huron.pkg.clock import Clock

__all__ = ["Services"]


@dataclass
class Services:
    """Everything a command needs; ``main`` builds the real ones, tests build fakes.

    ``storage_factory`` gives the read-only storage of :class:`Mount` rooted at a directory of
    this machine. ``provision_storage`` gives the writable storage of the provision commands,
    which the storage admin runs, rooted at the mount prefix.
    """

    environ: Mapping[str, str]
    config_path: Path
    config: Config
    state: LocalState
    http: httpx.Client
    clock: Clock
    out: Console
    err: Console
    prompter: Prompter
    sleep: Callable[[float], None]
    open_browser: Callable[[str], object]
    hostname: str
    storage_factory: Callable[[Path], ShareReader]
    provision_storage: Callable[[Path], Storage] = PosixStorage
    output: OutputFormat = OutputFormat.TABLE
    catalog_override: str | None = None
    _session: Session | None = field(default=None, repr=False)
    _mount: Mount | None = field(default=None, repr=False)

    def oidc(self) -> Oidc:
        """The company identity provider."""
        return Oidc(self.http, self.config.issuer, self.config.client_id)

    def session(self) -> Session:
        """The login session."""
        if self._session is None:
            anonymous = ApiClient(self.http, self.config.api_url, None, self.sleep)
            self._session = Session(anonymous, self.oidc, self.state, self.clock)
        return self._session

    def api(self) -> ApiClient:
        """The API client, authenticated as the logged-in user."""
        return ApiClient(self.http, self.config.api_url, self.session().token, self.sleep)

    def mount(self) -> Mount:
        """The share as this machine sees it; one per command, so its checks are cached."""
        if self._mount is None:
            self._mount = Mount(self)
        return self._mount

    def organization(self) -> str | None:
        """The current organization: catalogs are listed and created in it, if any."""
        return self.config.current_organization

    def catalog(self) -> str | None:
        """The catalog relative identifiers resolve against, if any."""
        return self.catalog_override or self.config.current_catalog

    def require_catalog(self) -> str:
        """The current catalog; refuses when none is set."""
        catalog = self.catalog()
        if catalog is None:
            raise UsageError(
                "there is no current catalog",
                hint="to list the catalogs, run `huron catalog`. Then run `huron catalog <name>`",
            )
        return catalog

    def save_config(self, config: Config) -> None:
        """Persist and adopt ``config``, under the state lock."""
        with self.state.locked():
            config.save(self.config_path)
        self.config = config
