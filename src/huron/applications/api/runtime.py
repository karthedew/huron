"""Everything the service builds once at startup and shares across requests."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Protocol

import httpx
import structlog

from huron import __version__
from huron.applications.api.disk import (
    PROBE_TIMEOUT,
    Directories,
    LakeDirectories,
    LakeDisk,
    NoLake,
    Placements,
)
from huron.applications.api.settings import Settings
from huron.core.lake.bootstrap import BootstrapResult, Lake, LakeSettings, bootstrap, build_lake
from huron.core.lake.organizations.declarations import UNMANAGED, Declarations
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
from huron.core.storage import (
    DirectoryWriter,
    LakePath,
    LakeUnavailable,
    OrganizationPlace,
    Placer,
    Storage,
)
from huron.core.storage.posix import PosixStorage
from huron.pkg.clock import Clock, SystemClock

__all__ = ["VERSION", "ClosableStore", "Runtime", "build_runtime"]

VERSION = __version__

#: The startup reconcile report's logger: one ``bootstrap.*`` event per organization it touched.
_bootstrap_log = structlog.get_logger("huron.api.bootstrap")


class ClosableStore(UnitOfWork, Protocol):
    """A unit of work the runtime can close."""

    async def close(self) -> None:
        """Release connections."""
        ...


@dataclass
class Runtime:
    """The service's shared objects.

    ``disk`` and ``placements`` are ``None`` when the service has no lake, and ``directories``
    is then :class:`NoLake`.
    """

    settings: Settings
    store: ClosableStore
    clock: Clock
    lake: Lake
    http: httpx.AsyncClient
    company: CompanyTokenVerifier
    groups: GroupDirectory
    owns_http: bool = False
    declarations: Declarations = UNMANAGED
    disk: LakeDisk | None = None
    placements: Placements | None = None
    directories: Directories = field(default_factory=NoLake)
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
        """Readiness of each dependency; ``lake`` only when the service has a lake."""
        ping = getattr(self.store, "ping", None)
        database = True if ping is None else bool(await ping())
        try:
            keys = bool((await self.ring()).current.kid)
        except LookupError:
            keys = False
        checks = {"database": database, "signing_keys": keys}
        if self.disk is not None:
            checks["lake"] = await self.disk.ready()
        return checks

    async def close(self) -> None:
        """Release the disk pool, the store and the HTTP client the runtime created."""
        if self.disk is not None:
            self.disk.close()
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
    storage: Storage | None = None,
    probe_timeout: float = PROBE_TIMEOUT,
) -> Runtime:
    """Connect the store, bootstrap the lake, open the lake's disk and assemble the runtime.

    With ``lake_path``, ``storage`` stands in for the POSIX storage rooted there, and
    ``probe_timeout`` bounds the readiness probe of the lake's disk.
    """
    clock = clock or SystemClock()
    if store is None:
        store = await _store(settings)
    declarations = settings.declarations
    lake_settings = LakeSettings(
        settings.platform_admin_group,
        settings.key_overlap,
        declarations,
        receipt_mode=settings.receipt_mode,
        upload_ttl=settings.upload_ttl,
        upload_max_size=settings.upload_max_size,
    )
    _report(await bootstrap(store, clock, lake_settings))
    lake_path = settings.lake_path
    disk = placements = None
    directories: Directories = NoLake()
    if lake_path is not None:
        storage = storage or PosixStorage(root=lake_path)
        disk = LakeDisk(
            storage,
            _places(declarations, lake_path),
            str(settings.instance_id),
            clock=clock,
            probe_timeout=probe_timeout,
        )
        await _open(disk, lake_path)
        placements = Placements(disk, Placer(storage))
        # The service group is the pod's runAsGroup, not a setting.
        directories = LakeDirectories(disk, DirectoryWriter(storage, os.getgid()))
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
        declarations=declarations,
        disk=disk,
        placements=placements,
        directories=directories,
    )


def _places(declarations: Declarations, lake_path: Path) -> dict[str, OrganizationPlace]:
    """The place of each declared organization: its root as a lake path, with its own marker."""
    return {
        declared.name: OrganizationPlace(
            declared.name,
            LakePath()
            if declared.root is None
            else LakePath.of(*PurePosixPath(declared.root).relative_to(lake_path).parts),
            own_marker=True,
        )
        for declared in declarations
    }


async def _open(disk: LakeDisk, lake_path: Path) -> None:
    """Open the lake's disk; a refusal names ``lake_path``, and the disk is closed again."""
    try:
        await disk.open()
    except LakeUnavailable as error:
        disk.close()
        raise LakeUnavailable(
            f"the lake at {lake_path} is not available: {error.message}",
            {**error.context, "lake_path": str(lake_path)},
        ) from error
    except BaseException:
        disk.close()
        raise


def _report(result: BootstrapResult) -> None:
    """Log what the reconcile of the declared organizations changed, one event per change.

    Created, updated (display name or description) and regranted organizations are ``INFO``;
    organizations the configuration no longer declares are kept and reported at ``WARNING``.
    """
    reconciled = result.organizations
    for name in reconciled.created:
        _bootstrap_log.info("bootstrap.organization_created", name=name)
    for name in reconciled.updated:
        _bootstrap_log.info("bootstrap.organization_updated", name=name)
    for name in reconciled.regranted:
        _bootstrap_log.info("bootstrap.organization_regranted", name=name)
    for organization in reconciled.undeclared:
        _bootstrap_log.warning(
            "bootstrap.organization_undeclared",
            name=organization.name,
            catalog_count=organization.catalog_count,
        )


async def _store(settings: Settings) -> ClosableStore:
    if settings.store == "memory":
        return MemoryStore()
    store = PostgresStore(settings.database_url, settings.pool_size)
    await store.connect()
    return store
