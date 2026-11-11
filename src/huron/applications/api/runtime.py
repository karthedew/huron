"""Everything the service builds once at startup and shares across requests."""

from __future__ import annotations

import os
import signal
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Protocol

import httpx
import structlog

from huron import __version__
from huron.applications.api.disk import (
    PROBE_TIMEOUT,
    Capacity,
    Cleanup,
    Directories,
    LakeDirectories,
    LakeDisk,
    LakeRepair,
    Materializer,
    NoLake,
    Ownership,
    Placements,
    Sealing,
    Tasks,
    WriterLock,
    repeat,
)
from huron.applications.api.settings import Settings
from huron.core.lake.bootstrap import BootstrapResult, Lake, LakeSettings, bootstrap, build_lake
from huron.core.lake.organizations.declarations import UNMANAGED, Declarations
from huron.core.lake.publications.operations import Publications
from huron.core.lake.transaction import UnitOfWork
from huron.core.lake.uploads.attempts import Attempts
from huron.core.lake.uploads.leftovers import Leftovers
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
    OBJECT_DIR,
    DirectoryWriter,
    LakePath,
    LakeUnavailable,
    OrganizationPlace,
    Placer,
    Publisher,
    Repairer,
    Sealer,
    Storage,
)
from huron.core.storage.posix import PosixStorage
from huron.pkg.clock import Clock, SystemClock

__all__ = [
    "SERVICE_UMASK",
    "VERSION",
    "ClosableStore",
    "Orchestration",
    "Runtime",
    "build_runtime",
]

VERSION = __version__

#: The umask of the API process. ``mkdir`` applies it, and a new directory below a catalog gets
#: no ``chmod`` (a ``chmod`` by a caller outside the directory's group clears the setgid bit), so
#: it must keep the bits of ``0750``.
SERVICE_UMASK = 0o022

#: The startup reconcile report's logger: one ``bootstrap.*`` event per organization it touched.
_bootstrap_log = structlog.get_logger("huron.api.bootstrap")


class ClosableStore(UnitOfWork, Protocol):
    """A unit of work the runtime can close, with the writer lock of the lake."""

    async def close(self) -> None:
        """Release connections."""
        ...

    def writer_lock(self) -> WriterLock:
        """The lock that the one writer of the lake holds."""
        ...


@dataclass
class Orchestration:
    """The work on the lake that outlives a request.

    ``ownership`` says whether this process writes the lake. ``sealing`` seals uploads,
    ``materializer`` publishes commit requests, ``capacity`` checks the free space of a new
    upload and ``cleanup`` removes leftovers. ``background`` runs :meth:`maintain` every
    ``sweep_interval``.
    """

    ownership: Ownership
    sealing: Sealing
    materializer: Materializer
    capacity: Capacity
    cleanup: Cleanup
    background: Tasks[str, None]

    async def start(self, interval: timedelta) -> None:
        """Continue the pending requests and start the periodic loop, in the writer only."""
        if not self.ownership.writable:
            return
        await self.materializer.recover_pending()
        self.background.start(
            "maintenance", lambda: repeat("maintenance", interval.total_seconds(), self.maintain)
        )

    async def maintain(self) -> None:
        """One run of the periodic loop: continue each ``accepted`` request that has no task,
        then clean up the lake.
        """
        await self.materializer.resume_accepted()
        await self.cleanup.run()

    async def close(self) -> None:
        """Stop the background work, the seals and the publications, then give the lock back."""
        await self.background.close()
        await self.sealing.close()
        await self.materializer.close()
        await self.ownership.close()


@dataclass
class Runtime:
    """The service's shared objects.

    ``disk``, ``placements``, ``repair`` and ``orchestration`` are ``None`` when the service
    has no lake, and ``directories`` is then :class:`NoLake`. ``attempts`` and ``publications``
    are the upload attempt and commit request operations.
    """

    settings: Settings
    store: ClosableStore
    clock: Clock
    lake: Lake
    http: httpx.AsyncClient
    company: CompanyTokenVerifier
    groups: GroupDirectory
    attempts: Attempts
    publications: Publications
    owns_http: bool = False
    declarations: Declarations = UNMANAGED
    disk: LakeDisk | None = None
    placements: Placements | None = None
    repair: LakeRepair | None = None
    directories: Directories = field(default_factory=NoLake)
    orchestration: Orchestration | None = None
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
        """Stop the work on the lake, then release the disk pool, the store and the HTTP client
        the runtime created.
        """
        if self.orchestration is not None:
            await self.orchestration.close()
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
    on_writer_lost: Callable[[], None] | None = None,
) -> Runtime:
    """Connect the store, bootstrap the lake, open the lake's disk and assemble the runtime.

    First it sets the process umask to :data:`SERVICE_UMASK`, before any disk pool starts. With
    ``lake_path``, ``storage`` stands in for the POSIX storage rooted there, and
    ``probe_timeout`` bounds the readiness probe of the lake's disk. With ``lake_path`` the
    runtime also takes the writer lock before any disk work. A process that gets the lock opens
    the lake, continues the pending commit requests and starts the periodic loop. A process
    that does not get it serves reads only. A failure after the lock gives the lock back and
    closes the disk before it propagates. ``on_writer_lost`` runs when the writer loses its
    lock. By default it stops the process with ``SIGTERM``.
    """
    os.umask(SERVICE_UMASK)
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
    attempts = Attempts(
        store,
        clock,
        ttl=settings.attempt_ttl,
        object_dir=OBJECT_DIR,
        max_upload_bytes=settings.max_upload_bytes,
        max_staged_bytes=settings.max_staged_bytes,
    )
    publications = Publications(store, clock)
    lake_path = settings.lake_path
    disk = placements = repair = orchestration = None
    directories: Directories = NoLake()
    if lake_path is not None:
        storage = storage or PosixStorage(root=lake_path)
        ownership = Ownership(store.writer_lock(), on_writer_lost or _stop_process)
        await ownership.start()
        disk = LakeDisk(
            storage,
            _places(declarations, lake_path),
            str(settings.instance_id),
            clock=clock,
            probe_timeout=probe_timeout,
            writer=ownership,
        )
        orchestration = _orchestration(
            disk, storage, store, attempts, publications, ownership, settings.min_free_bytes
        )
        await _start(disk, orchestration, lake_path, settings.sweep_interval)
        placements = Placements(disk, Placer(storage))
        # The service group is the pod's runAsGroup, not a setting.
        writer = DirectoryWriter(storage, os.getgid())
        directories = LakeDirectories(disk, writer)
        repair = LakeRepair(disk, Repairer(storage, writer))
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
        attempts=attempts,
        publications=publications,
        owns_http=owns_http,
        declarations=declarations,
        disk=disk,
        placements=placements,
        repair=repair,
        directories=directories,
        orchestration=orchestration,
    )


def _orchestration(
    disk: LakeDisk,
    storage: Storage,
    store: ClosableStore,
    attempts: Attempts,
    publications: Publications,
    ownership: Ownership,
    min_free_bytes: int,
) -> Orchestration:
    sealer = Sealer(storage)
    sealing = Sealing(disk, attempts, sealer)
    return Orchestration(
        ownership=ownership,
        sealing=sealing,
        materializer=Materializer(disk, publications, Publisher(storage)),
        capacity=Capacity(disk, storage, min_free_bytes),
        cleanup=Cleanup(disk, storage, attempts, Leftovers(store), sealing, sealer),
        background=Tasks("background"),
    )


def _stop_process() -> None:
    """Stop the service as the platform stops it; the platform then starts it again."""
    os.kill(os.getpid(), signal.SIGTERM)


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


async def _start(
    disk: LakeDisk, orchestration: Orchestration, lake_path: Path, interval: timedelta
) -> None:
    """Open the lake's disk in the writer, then start the orchestration.

    A failure stops the orchestration, gives the writer lock back and closes the disk before
    it propagates. A refusal of the lake names ``lake_path``.
    """
    try:
        if orchestration.ownership.writable:
            await disk.open()
        await orchestration.start(interval)
    except BaseException as error:
        await orchestration.close()
        disk.close()
        if isinstance(error, LakeUnavailable):
            raise LakeUnavailable(
                f"the lake at {lake_path} is not available: {error.message}",
                {**error.context, "lake_path": str(lake_path)},
            ) from error
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
