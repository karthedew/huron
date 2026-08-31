"""FastAPI composition root for the Huron control plane.

This module only wires: settings, the repository, the optional OIDC verifier,
exception mapping, and the versioned routers. Authorization policy lives in
``pkg/rbac`` (the pure engine plus the role model), request guards in
``huron.service.api.authorization``, and route handlers under ``routes/v1``.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import asyncpg
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from huron.pkg.auth import AuthError, JwksVerifier, OidcClient, OidcResolver
from huron.pkg.catalog.errors import DomainError, ProjectionUnavailable
from huron.pkg.rawstore import PosixRawStore
from huron.pkg.rbac import ScopeType
from huron.pkg.rbac.roles import RoleError

from .postgres_auth import PostgresCredentialStore, PostgresPrincipalStore, PostgresSessionStore
from .postgres_rbac import PostgresApiKeyStore, PostgresRbacStore
from .repository import HierarchyRepository
from .routes import auth as auth_routes
from .routes import v1
from .settings import ApiSettings

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
        rbac_store=PostgresRbacStore(pool),
        api_key_store=PostgresApiKeyStore(pool),
        credential_store=PostgresCredentialStore(pool),
        session_store=PostgresSessionStore(pool),
        principal_store=PostgresPrincipalStore(pool),
    )
    return repository, pool


async def _configure_oidc(
    app: FastAPI,
    settings: ApiSettings,
    oidc_verify: Callable[[str], Mapping[str, object]] | None,
) -> httpx.AsyncClient | None:
    """Wire the bearer-JWT resolver: a test-injected verifier wins outright,
    otherwise a configured provider is discovered for real. Neither branch
    - or an unconfigured deployment - leaves ``oidc_resolver`` unset, so
    ``current_principal`` can always ``getattr`` it safely."""
    if oidc_verify is not None:
        app.state.oidc_resolver = OidcResolver(oidc_verify)
        app.state.oidc_client = None
        return None
    if settings.oidc is None:
        app.state.oidc_resolver = None
        app.state.oidc_client = None
        return None
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
    app.state.oidc_client = client
    app.state.oidc_resolver = OidcResolver(verifier)
    return http


def create_app(
    *,
    settings: ApiSettings | None = None,
    repository: HierarchyRepository | None = None,
    oidc_verify: Callable[[str], Mapping[str, object]] | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        resolved_settings = settings or ApiSettings()  # type: ignore[call-arg]
        app.state.settings = resolved_settings
        app.state.database_pool = None
        if repository is not None:
            app.state.repository = repository
        elif resolved_settings.store_backend == "postgres":
            app.state.repository, app.state.database_pool = await _postgres_repository(
                resolved_settings
            )
        else:
            app.state.repository = HierarchyRepository(PosixRawStore(resolved_settings.data_root))
        app.state.http_client = await _configure_oidc(app, resolved_settings, oidc_verify)
        await _bootstrap(app.state.repository, resolved_settings)
        yield
        if app.state.database_pool is not None:
            await app.state.database_pool.close()
        if app.state.http_client is not None:
            await app.state.http_client.aclose()

    app = FastAPI(title="Huron API", version="1.0.0", lifespan=lifespan)
    if repository is not None:
        # Set eagerly (in addition to the lifespan above) so a TestClient
        # used without its context manager - which never runs ASGI
        # lifespan events - still finds a working app.state. Bootstrap
        # itself stays lifespan-only: it is async and must run exactly
        # once, and a TestClient that needs it entered must use ``with``.
        app.state.repository = repository
        app.state.settings = settings
        app.state.oidc_resolver = OidcResolver(oidc_verify) if oidc_verify else None
        app.state.oidc_client = None

    @app.exception_handler(DomainError)
    async def domain_error_handler(_request: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.as_problem(),
            media_type="application/problem+json",
        )

    @app.exception_handler(AuthError)
    async def auth_error_handler(_request: Request, exc: AuthError) -> JSONResponse:
        return JSONResponse(
            status_code=401,
            content={
                "type": f"urn:huron:error:{exc.code.lower()}",
                "title": "Authentication failed",
                "status": 401,
                "code": exc.code,
                "detail": str(exc),
            },
            media_type="application/problem+json",
        )

    @app.exception_handler(RoleError)
    async def role_error_handler(_request: Request, exc: RoleError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "type": f"urn:huron:error:{exc.code.lower()}",
                "title": "Role model violation",
                "status": 422,
                "code": exc.code,
                "detail": str(exc),
            },
            media_type="application/problem+json",
        )

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz(request: Request) -> dict[str, str]:
        repository_state: HierarchyRepository = request.app.state.repository
        if not repository_state.raw_store.root.exists():
            raise DomainError("raw root is unavailable")
        return {"status": "ready"}

    @app.get("/api/v1/search")
    async def search_unavailable() -> dict[str, object]:
        raise ProjectionUnavailable("search projection is not configured")

    # The only unauthenticated routes in the service besides /healthz and
    # /readyz: password login, OIDC start/callback, and the provider-
    # discovery route the login page renders from.
    app.include_router(auth_routes.router, prefix="/auth", tags=["auth"])
    app.include_router(v1.router, prefix="/api/v1")
    return app


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


app = create_app()
