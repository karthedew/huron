"""FastAPI composition root for the Huron control plane.

This module only wires: settings, the repository, the optional OIDC verifier,
exception mapping, and the versioned routers. Authorization policy lives in
``pkg/rbac`` (the pure engine plus the role model), request guards in
``huron.applications.api.authorization``, and route handlers under ``routes/v1``.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import asyncpg
import httpx
from asyncer import asyncify
from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from huron.core._catalog import HierarchyRepository
from huron.core._ingest import IngestService
from huron.core._revision_reader import RevisionService
from huron.pkg.auth import JwksVerifier, OidcClient, OidcResolver
from huron.pkg.catalog.failures import DependencyUnavailable
from huron.pkg.metastore import (
    PostgresApiKeyStore,
    PostgresCredentialStore,
    PostgresHierarchyStore,
    PostgresPrincipalStore,
    PostgresRbacStore,
    PostgresSessionStore,
    SystemClock,
)
from huron.pkg.rawstore import PosixRawStore
from huron.pkg.rbac import Classification, RoleBindingAuthorizer, ScopeType

from .expiry import ExpirySweep
from .problems import Problem, install_error_handlers, problem_response
from .routes import auth as auth_routes
from .routes import v1
from .runtime import ApiRuntime, ApiStores, Runtime
from .settings import ApiSettings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Mapping

    from huron.pkg.catalog.ports import Clock


def _postgres_stores(pool: asyncpg.Pool, clock: Clock) -> ApiStores:
    """Wire the Postgres-backed RBAC and authentication stores over one shared pool.

    Args:
        pool: The already-open pool every store shares. The caller owns
            the pool and closes it at shutdown; the stores never do.
        clock: The source of the current time for the hierarchy store's
            idempotency and lease arithmetic.

    Returns:
        The six stores, each a thin wrapper around the pool.
    """
    return ApiStores(
        hierarchy=PostgresHierarchyStore(pool, clock=clock),
        rbac=PostgresRbacStore(pool),
        api_keys=PostgresApiKeyStore(pool),
        credentials=PostgresCredentialStore(pool),
        sessions=PostgresSessionStore(pool),
        principals=PostgresPrincipalStore(pool),
    )


def _build_runtime(
    settings: ApiSettings,
    wired: ApiStores,
    clock: Clock,
    pool: asyncpg.Pool | None,
    oidc: tuple[OidcResolver | None, OidcClient | None],
) -> ApiRuntime:
    """Compose the repository, the facades and the authorizer into one published runtime.

    Args:
        settings: The validated configuration; read for ``data_root`` and
            the classification vocabulary every facade shares.
        wired: The RBAC and authentication stores, injected or freshly
            wired to Postgres.
        clock: The source of the current time for the ingest facade; the
            hierarchy store's own clock was already set when ``wired`` was
            built.
        pool: The database pool this instance opened, or None when
            ``wired`` was injected; published unchanged for ``/readyz``.
        oidc: The resolver and client ``_configure_oidc`` produced.

    Returns:
        The runtime every injected route reads through
        ``huron.applications.api.runtime``.
    """
    raw_store = PosixRawStore(
        settings.data_root,
        max_concurrent_completions=settings.completion_max_concurrent,
        completion_reserve_bytes=settings.completion_reserve_bytes,
    )
    repository = HierarchyRepository(raw_store, wired.hierarchy, rbac_store=wired.rbac)
    oidc_resolver, oidc_client = oidc
    return ApiRuntime(
        settings=settings,
        repository=repository,
        hierarchy=wired.hierarchy,
        rbac=wired.rbac,
        ingest=IngestService(raw_store, wired.hierarchy, clock=clock),
        revisions=RevisionService(raw_store, wired.hierarchy),
        authorizer=RoleBindingAuthorizer(
            classifications=tuple(
                Classification(value.code, value.order, value.discoverable)
                for value in settings.classification_vocabulary
            )
        ),
        api_keys=wired.api_keys,
        credentials=wired.credentials,
        sessions=wired.sessions,
        principals=wired.principals,
        oidc_resolver=oidc_resolver,
        oidc_client=oidc_client,
        database_pool=pool,
    )


async def _configure_oidc(
    settings: ApiSettings,
    oidc_verify: Callable[[str], Mapping[str, object]] | None,
) -> tuple[OidcResolver | None, OidcClient | None, httpx.AsyncClient | None]:
    """Wire the bearer-JWT resolver from an injected verifier or a real provider.

    A test-injected verifier wins outright, otherwise a configured provider
    is discovered for real. Neither branch - or an unconfigured deployment -
    leaves the resolver unset; the caller always gets an explicit ``None``
    rather than an absent attribute.

    Args:
        settings: Read for ``oidc``, the configured identity provider, which
            is ``None`` in a deployment that accepts no bearer JWTs.
        oidc_verify: A verifier mapping a bearer token to its claims, or
            None. When given it replaces provider discovery entirely, so a
            test never needs a reachable issuer.

    Returns:
        A ``(resolver, client, http)`` triple. With an injected verifier only
        the resolver is set; with no provider configured all three are
        ``None``; after real discovery all three are set, and the HTTP
        client is the caller's to close at shutdown because the OIDC client
        keeps using it for the authorization-code flow.

    Raises:
        Exception: Whatever provider discovery raised, re-raised unchanged
            after the HTTP client has been closed, so a failed startup does
            not leave an open connection pool behind.
    """
    if oidc_verify is not None:
        return OidcResolver(oidc_verify), None, None
    if settings.oidc is None:
        return None, None, None
    oidc = settings.oidc
    http = httpx.AsyncClient()
    try:
        client = await OidcClient.discover(
            http,
            oidc.issuer,
            client_id=oidc.client_id,
            client_secret=oidc.client_secret,
            redirect_url=oidc.redirect_url,
            scopes=oidc.scopes,
            groups_claim=oidc.groups_claim,
        )
    except Exception:
        await http.aclose()
        raise
    verifier = JwksVerifier(
        issuer=oidc.issuer,
        audience=oidc.audience or oidc.client_id,
        jwks_url=client.provider.jwks_uri,
    )
    return OidcResolver(verifier), client, http


class _HuronFastAPI(FastAPI):
    """Injects the ``Problem`` schema FastAPI never derives on its own.

    No operation returns ``Problem`` as a 2xx body, so nothing in the route
    table gives ``get_openapi`` a reason to generate it, yet every
    ``responses=`` entry ``$ref``s it. FastAPI's own docs cover this by
    assigning a replacement function to ``app.openapi`` directly, but that
    assignment is unsound against ``FastAPI.openapi``'s real signature - a
    bound ``(self) -> dict[str, Any]`` method - so neither type checker
    accepts it. Overriding the method on a subclass is the type-checkable
    form of the same fix: it still computes and caches the schema on
    ``app.openapi_schema`` the first time anything calls ``app.openapi()``,
    so the docs UI and every other caller keep reading from one schema.
    """

    def openapi(self) -> dict[str, object]:
        """Return the OpenAPI document, computing and caching it on first use.

        Returns:
            The document FastAPI derives from the route table, with the
            ``Problem`` schema added under ``components.schemas`` so every
            error response's ``$ref`` resolves.
        """
        if self.openapi_schema is None:
            schema = get_openapi(title=self.title, version=self.version, routes=self.routes)
            schema["components"]["schemas"]["Problem"] = Problem.model_json_schema()
            self.openapi_schema = schema
        return self.openapi_schema


def create_app(
    *,
    settings: ApiSettings,
    stores: ApiStores | None = None,
    oidc_verify: Callable[[str], Mapping[str, object]] | None = None,
) -> FastAPI:
    """Build the application, deferring every connection to its lifespan.

    Nothing is connected when this returns. The lifespan builds one
    :class:`ApiRuntime` - the repository, the authorizer, the RBAC and
    authentication stores, the optional OIDC resolver and client, the
    optional database pool - and publishes it on ``app.state.runtime`` as
    the application's only piece of mutable state; every injected route
    reads it through ``huron.applications.api.runtime``. An application whose
    lifespan never started therefore refuses to serve rather than falling
    through to defaults, because the cost of guessing at wiring is an
    unauthenticated request answered as though it were authenticated.

    The unversioned ``/healthz`` and ``/readyz`` probes, the error handlers
    that keep every failure in the problem+json shape, and the ``/auth`` and
    ``/api/v1`` routers are all mounted here and nowhere else.

    Args:
        settings: The validated configuration; ``database_url`` is where
            the lifespan opens its pool when no stores are injected.
        stores: The RBAC and authentication stores built by the caller,
            which skip opening a pool entirely. Tests inject a set built on
            the in-memory implementations.
        oidc_verify: A verifier mapping a bearer token to its claims. When
            given it replaces provider discovery, so bearer JWTs are
            accepted without a reachable issuer.

    Returns:
        The application, ready for an ASGI server to run its lifespan.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Wire the runtime for the server's lifetime, then release it.

        The RBAC and authentication stores come from the injected set, else
        the lifespan opens a fresh pool from ``settings.database_url`` and
        wires every store to Postgres; the hierarchy repository and the
        authorizer are always built fresh here, over the raw store and the
        classification vocabulary the settings declare. The bearer-JWT
        resolver follows the same injected-first rule as the stores.
        Opening the pool, discovering the OIDC provider, running the
        bootstrap grant, running the ingest expiry sweep and suspending at
        ``yield`` all happen inside one block whose ``finally`` closes the
        pool and the HTTP client, so a failure at any point after the pool
        opens releases it before the error surfaces - including a
        discovery failure that happens after the pool is already open.
        The sweep's task starts only once the runtime is published and the
        bootstrap grant has run, and is cancelled and awaited before the
        ``finally`` closes the pool, so no pass ever runs against a
        connection that has already gone away.

        Args:
            app: The application whose ``state.runtime`` is set for the
                duration of the lifespan.

        Yields:
            Nothing. The application serves while suspended here. Whether
            startup completed or raised, every resource it acquired - the
            database pool, the OIDC discovery HTTP client - is closed
            before the lifespan exits.
        """
        pool: asyncpg.Pool | None = None
        http: httpx.AsyncClient | None = None
        try:
            clock = SystemClock()
            if stores is not None:
                wired = stores
            else:
                pool = await asyncpg.create_pool(settings.database_url)
                wired = _postgres_stores(pool, clock)
            oidc_resolver, oidc_client, http = await _configure_oidc(settings, oidc_verify)
            runtime = _build_runtime(settings, wired, clock, pool, (oidc_resolver, oidc_client))
            app.state.runtime = runtime
            await _bootstrap(runtime.repository, settings)
            async with ExpirySweep(
                runtime.ingest,
                interval_seconds=settings.ingest_sweep_interval_seconds,
                limit=settings.ingest_sweep_limit,
            ):
                yield
        finally:
            if pool is not None:
                await pool.close()
            if http is not None:
                await http.aclose()

    app = _HuronFastAPI(title="Huron API", version="1.0.0", lifespan=lifespan)
    install_error_handlers(app)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        """Report that the process is up and answering requests.

        Liveness only: nothing beyond the process itself is consulted, so
        an instance whose dependencies are gone still answers 200 here and
        relies on the readiness probe to be taken out of rotation.
        \f
        Returns:
            ``{"status": "ok"}``, unconditionally.
        """
        return {"status": "ok"}

    @app.get("/readyz", responses={503: problem_response("a dependency is unavailable")})
    async def readyz(runtime: Runtime) -> dict[str, str]:
        """Refuse traffic unless every dependency this instance needs answers.

        A readiness probe that reports the process rather than its
        dependencies sends traffic to an instance whose first authenticated
        request will fail, so the failure is a 503 - the status an
        orchestrator is configured to act on - and never a 4xx. The raw
        store's root is always probed; the database is probed only when
        this instance was wired with a pool.
        \f
        Args:
            runtime: The wiring the lifespan published, naming the
                dependencies to probe.

        Returns:
            ``{"status": "ready"}`` once every probe passed.

        Raises:
            DependencyUnavailable: If any probe failed; its ``context``
                carries ``checks``, a mapping from each failed dependency's
                name to the reason it gave.
        """
        failed = {name: reason for name, reason in await _dependency_checks(runtime) if reason}
        if failed:
            raise DependencyUnavailable("a dependency is unavailable", context={"checks": failed})
        return {"status": "ready"}

    app.include_router(auth_routes.router)
    app.include_router(v1.router)
    return app


async def _dependency_checks(runtime: ApiRuntime) -> list[tuple[str, str | None]]:
    """Probe each dependency this instance was wired with.

    The raw store's stat runs on a worker thread so a hung mount never
    stalls the event loop the other requests share, and the database
    round-trip runs on the loop directly; both are bounded by the same
    ``READINESS_TIMEOUT_SECONDS`` so neither can hang the probe past it.

    Args:
        runtime: The wiring the lifespan published; a ``None`` pool means
            there is no database to probe.

    Returns:
        One ``(name, failure)`` pair per probed dependency, in probe order,
        where ``failure`` is ``None`` for a dependency that answered and
        the reason it did not otherwise.
    """
    checks = [("raw_store", await _raw_store_probe(runtime.repository))]
    if runtime.database_pool is not None:
        checks.append(("database", await _database_failure(runtime.database_pool)))
    return checks


async def _raw_store_probe(repository: HierarchyRepository) -> str | None:
    """Stat the raw root on a worker thread, within the readiness timeout.

    A mount that never answers ``stat`` must not hang the probe forever, so
    the wait is bounded the same way the database round-trip is. Timing out
    abandons the worker thread rather than cancelling it: threads have no
    interrupt point to cancel into, so the thread stays blocked in ``stat``
    and exits on its own whenever the mount eventually answers or the
    process shuts down. It never blocks a later probe, which starts a fresh
    thread of its own, but under a mount that stays wedged and is polled
    repeatedly, each abandoned thread stays alive until the mount answers,
    so blocked threads accumulate for as long as the hang persists.

    Args:
        repository: The wired repository, whose raw store names the root
            directory the data plane writes under.

    Returns:
        ``None`` while the root exists, ``"root is unavailable"`` while it
        does not, and the readiness-timeout message once the bound above
        is reached.
    """
    try:
        async with asyncio.timeout(READINESS_TIMEOUT_SECONDS):
            return await asyncify(_raw_store_failure)(repository)
    except TimeoutError:
        return f"did not answer within {READINESS_TIMEOUT_SECONDS}s"


def _raw_store_failure(repository: HierarchyRepository) -> str | None:
    """Stat the raw root; a hung mount must never stall the event loop.

    Deliberately synchronous: the ``stat`` behind ``exists()`` can block on
    a network filesystem, so the caller runs this on a worker thread rather
    than from a coroutine.

    Args:
        repository: The wired repository, whose raw store names the root
            directory the data plane writes under.

    Returns:
        ``None`` while the root exists, otherwise the reason the probe
        reports for it.
    """
    return None if repository.raw_store.root.exists() else "root is unavailable"


async def _database_failure(pool: asyncpg.Pool) -> str | None:
    """Round-trip the pool once, within the readiness timeout.

    A pool that cannot answer ``SELECT 1`` promptly is reported rather than
    waited for: the connection-level, server-level and timeout failures are
    all caught, so a wedged database turns into a 503 instead of a stalled
    probe.

    Args:
        pool: The pool the lifespan opened for the Postgres-backed stores.

    Returns:
        ``None`` when the query answered in time, otherwise the failure's
        class name and message, which is what ``/readyz`` reports for the
        ``database`` check.
    """
    try:
        async with asyncio.timeout(READINESS_TIMEOUT_SECONDS):
            await pool.fetchval("SELECT 1")
    except (OSError, asyncpg.PostgresError, TimeoutError) as exc:
        return f"{type(exc).__name__}: {exc}"
    return None


#: A readiness probe that waits longer than the orchestrator's own probe
#: timeout reports nothing; two seconds is well inside the usual five.
READINESS_TIMEOUT_SECONDS = 2.0


async def _bootstrap(repository: HierarchyRepository, settings: ApiSettings) -> None:
    """Give the configured bootstrap subject platform ownership, once.

    Without one SYSTEM-scope ``platform_owner`` binding nothing can create
    organizations or grant further roles; every other permission then flows
    through the API's own guarded binding routes. The grant is idempotent
    across restarts: an existing binding for the same subject is left
    alone, so a persistent store never accumulates duplicates.

    Args:
        repository: Where SYSTEM-scope bindings are read and the grant is
            stored.
        settings: Read for ``bootstrap_platform_owner``; an unset subject
            makes this a no-op.
    """
    subject = settings.bootstrap_platform_owner
    if not subject:
        return
    principal = f"user:{subject}"
    existing = await repository.bindings_at(ScopeType.SYSTEM, None)
    already = any(
        item.principal == principal and item.role_code == "platform_owner" for item in existing
    )
    if not already:
        await repository.grant_role(
            principal=principal,
            role_code="platform_owner",
            scope_type=ScopeType.SYSTEM,
            scope_id=None,
            created_by="bootstrap",
        )
