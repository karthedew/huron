"""Everything the service builds once at startup and shares across requests."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

import httpx

from huron import __version__
from huron.applications.api.settings import Settings
from huron.core.lake.bootstrap import Lake, LakeSettings, bootstrap, build_lake
from huron.core.lake.transaction import UnitOfWork
from huron.core.metastore.postgres import PostgresStore
from huron.core.metastore.store import MemoryStore
from huron.core.security.broker import (
    CompanyTokenVerifier,
    GroupDirectory,
    HttpGroupDirectory,
    KeyRing,
    TokenExchange,
    TokenIssuer,
    TokenVerifier,
)
from huron.pkg.clock import Clock, SystemClock

__all__ = ["VERSION", "ClosableStore", "Runtime", "build_runtime"]

VERSION = __version__


class ClosableStore(UnitOfWork, Protocol):
    """A unit of work the runtime can close."""

    async def close(self) -> None:
        """Release connections."""
        ...


@dataclass
class Runtime:
    """The service's shared objects."""

    settings: Settings
    store: ClosableStore
    clock: Clock
    lake: Lake
    http: httpx.AsyncClient
    company: CompanyTokenVerifier
    groups: GroupDirectory
    owns_http: bool = False
    _ring: KeyRing | None = field(default=None, repr=False)
    _ring_loaded_at: datetime | None = field(default=None, repr=False)

    async def ring(self, *, refresh: bool = False) -> KeyRing:
        """The key ring, reloaded at most every ``key_cache_seconds`` unless ``refresh``."""
        now = self.clock.now()
        stale = self._ring_loaded_at is None or now - self._ring_loaded_at >= timedelta(
            seconds=self.settings.key_cache_seconds
        )
        if self._ring is None or stale or refresh:
            self._ring = await self.lake.keys.ring()
            self._ring_loaded_at = now
        return self._ring

    async def verifier(self) -> TokenVerifier:
        """A verifier over the current key ring."""
        return TokenVerifier(
            await self.ring(), self.settings.issuer, self.settings.audience, self.clock
        )

    async def exchange(self) -> TokenExchange:
        """The token exchange over the current key ring."""
        issuer = TokenIssuer(
            await self.ring(),
            self.clock,
            self.settings.issuer,
            self.settings.audience,
            self.settings.token_ttl,
        )
        return TokenExchange(self.company, self.groups, issuer)

    async def ready(self) -> dict[str, bool]:
        """Readiness of each dependency."""
        ping = getattr(self.store, "ping", None)
        database = True if ping is None else bool(await ping())
        try:
            keys = bool((await self.ring()).current.kid)
        except LookupError:
            keys = False
        return {"database": database, "signing_keys": keys}

    async def close(self) -> None:
        """Release the store and the HTTP client the runtime created."""
        await self.store.close()
        if self.owns_http:
            await self.http.aclose()


async def build_runtime(
    settings: Settings,
    *,
    store: ClosableStore | None = None,
    http: httpx.AsyncClient | None = None,
    groups: GroupDirectory | None = None,
    clock: Clock | None = None,
) -> Runtime:
    """Connect the store, bootstrap the lake and assemble the runtime."""
    clock = clock or SystemClock()
    if store is None:
        store = await _store(settings)
    lake_settings = LakeSettings(settings.platform_admin_group, settings.key_overlap)
    await bootstrap(store, clock, lake_settings)
    owns_http = http is None
    client = http or httpx.AsyncClient(timeout=httpx.Timeout(10.0))
    return Runtime(
        settings=settings,
        store=store,
        clock=clock,
        lake=build_lake(store, clock, lake_settings),
        http=client,
        company=CompanyTokenVerifier(
            client, settings.company_issuer, settings.company_audience, clock
        ),
        groups=groups or HttpGroupDirectory(client, settings.group_directory_url),
        owns_http=owns_http,
    )


async def _store(settings: Settings) -> ClosableStore:
    if settings.store == "memory":
        return MemoryStore()
    store = PostgresStore(settings.database_url, settings.pool_size)
    await store.connect()
    return store
