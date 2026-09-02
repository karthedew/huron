"""FastAPI composition root for the Huron control plane.

This module only wires: settings, the repository, the optional OIDC verifier,
exception mapping, and the versioned routers. Authorization policy lives in
``pkg/rbac`` (the pure engine plus the role model), request guards in
``huron.service.api.authorization``, and route handlers under ``routes/v1``.
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

from huron.pkg.auth import JwksVerifier, OidcClient, OidcResolver
from huron.pkg.rawstore import PosixRawStore
from huron.pkg.rbac import ScopeType

from .errors import DependencyUnavailable
from .problems import Problem, install_error_handlers, problem_response
from .repository import HierarchyRepository
from .routes import auth as auth_routes
from .routes import v1
from .runtime import ApiRuntime, Runtime
from .settings import ApiSettings
from .stores import (
    PostgresApiKeyStore,
    PostgresCredentialStore,
    PostgresPrincipalStore,
    PostgresRbacStore,
    PostgresSessionStore,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Mapping


async def _postgres_repository(settings: ApiSettings) -> tuple[HierarchyRepository, asyncpg.Pool]:
    """The RBAC and auth tables opted into Postgres together, sharing a pool.

    The organization/project/dataset hierarchy stays in-memory until it
    gets its own store, so this is only safe once the rows those foreign
    keys target (organizations, projects) are real Postgres rows - which
    requires choosing ``store_backend="postgres"`` explicitly rather than
    inferring it from "no repository was injected".
    """
    pool = await asyncpg.create_pool(settings.database_url)
    repository = HierarchyRepository(
        PosixRawStore(settings.data_root),
        classification_vocabulary=tuple(value.code for value in settings.classification_vocabulary),
        rbac_store=PostgresRbacStore(pool),
        api_key_store=PostgresApiKeyStore(pool),
        credential_store=PostgresCredentialStore(pool),
        session_store=PostgresSessionStore(pool),
        principal_store=PostgresPrincipalStore(pool),
    )
    return repository, pool


async def _configure_oidc(
    settings: ApiSettings,
    oidc_verify: Callable[[str], Mapping[str, object]] | None,
) -> tuple[OidcResolver | None, OidcClient | None, httpx.AsyncClient | None]:
    """Wire the bearer-JWT resolver: a test-injected verifier wins outright,
    otherwise a configured provider is discovered for real. Neither branch
    - or an unconfigured deployment - leaves the resolver unset; the caller
    always gets an explicit ``None`` rather than an absent attribute."""
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
        if self.openapi_schema is None:
            schema = get_openapi(title=self.title, version=self.version, routes=self.routes)
            schema["components"]["schemas"]["Problem"] = Problem.model_json_schema()
            self.openapi_schema = schema
        return self.openapi_schema


def create_app(
    *,
    settings: ApiSettings,
    repository: HierarchyRepository | None = None,
    oidc_verify: Callable[[str], Mapping[str, object]] | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        pool: asyncpg.Pool | None = None
        if repository is not None:
            wired = repository
        elif settings.store_backend == "postgres":
            wired, pool = await _postgres_repository(settings)
        else:
            wired = HierarchyRepository(
                PosixRawStore(settings.data_root),
                classification_vocabulary=tuple(
                    value.code for value in settings.classification_vocabulary
                ),
            )
        oidc_resolver, oidc_client, http = await _configure_oidc(settings, oidc_verify)
        app.state.runtime = ApiRuntime(
            settings=settings,
            repository=wired,
            oidc_resolver=oidc_resolver,
            oidc_client=oidc_client,
            database_pool=pool,
        )
        try:
            await _bootstrap(wired, settings)
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
        return {"status": "ok"}

    @app.get("/readyz", responses={503: problem_response("a dependency is unavailable")})
    async def readyz(runtime: Runtime) -> dict[str, str]:
        """Refuse traffic unless every dependency this instance needs answers.

        A readiness probe that reports the process rather than its
        dependencies sends traffic to an instance whose first authenticated
        request will fail, so the failure is a 503 - the status an
        orchestrator is configured to act on - and never a 4xx.
        """
        failed = {name: reason for name, reason in await _dependency_checks(runtime) if reason}
        if failed:
            raise DependencyUnavailable("a dependency is unavailable", context={"checks": failed})
        return {"status": "ready"}

    app.include_router(auth_routes.router)
    app.include_router(v1.router)
    return app


async def _dependency_checks(runtime: ApiRuntime) -> list[tuple[str, str | None]]:
    checks = [("raw_store", await asyncify(_raw_store_failure)(runtime.repository))]
    if runtime.database_pool is not None:
        checks.append(("database", await _database_failure(runtime.database_pool)))
    return checks


def _raw_store_failure(repository: HierarchyRepository) -> str | None:
    """Stat the raw root; a hung mount must never stall the event loop."""
    return None if repository.raw_store.root.exists() else "root is unavailable"


async def _database_failure(pool: asyncpg.Pool) -> str | None:
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
    through the API's own guarded binding routes.
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
