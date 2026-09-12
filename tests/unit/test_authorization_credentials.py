"""Request credential resolution to a Principal or 401, proved against current_principal.

Covers bearer/session/dev-header precedence, CSRF enforcement in the
cookie branch, and the dev-header fallback outside OIDC deployments.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from starlette.requests import Request

from huron.applications.api.authorization import current_principal
from huron.applications.api.authorization.credentials import _enforce_csrf
from huron.applications.api.runtime import ApiRuntime
from huron.applications.api.settings import ApiSettings, ClassificationValue, OidcSettings
from huron.core._catalog import HierarchyRepository
from huron.core._ingest import IngestService
from huron.core._revision_reader import RevisionService
from huron.pkg.auth import AuthError, OidcResolver, SessionRecord, create_session
from huron.pkg.metastore import SystemClock
from huron.pkg.rawstore import PosixRawStore
from huron.pkg.rbac import RoleBindingAuthorizer
from tests.unit.support import memory_stores

if TYPE_CHECKING:
    from pathlib import Path

    from huron.applications.api.runtime import ApiStores

pytestmark = pytest.mark.unit


def _request(
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
) -> Request:
    """A request with the given method, headers and cookies, as a real Starlette Request."""
    raw_headers = [(key.lower().encode(), value.encode()) for key, value in (headers or {}).items()]
    if cookies:
        cookie_header = "; ".join(f"{key}={value}" for key, value in cookies.items())
        raw_headers.append((b"cookie", cookie_header.encode()))
    scope = {"type": "http", "method": method, "path": "/", "headers": raw_headers, "app": None}
    return Request(scope)


def _repository(tmp_path: Path, stores: ApiStores) -> HierarchyRepository:
    """A real, filesystem-backed HierarchyRepository over ``stores``' hierarchy and rbac stores."""
    return HierarchyRepository(
        PosixRawStore(str(tmp_path / "raw")),
        stores.hierarchy,
        rbac_store=stores.rbac,
    )


def _ingest(repository: HierarchyRepository, stores: ApiStores) -> IngestService:
    """An IngestService sharing ``repository``'s raw store and ``stores``' hierarchy store."""
    return IngestService(repository.raw_store, stores.hierarchy, clock=SystemClock())


def _revisions(repository: HierarchyRepository, stores: ApiStores) -> RevisionService:
    """A RevisionService sharing ``repository``'s raw store and ``stores``' hierarchy store."""
    return RevisionService(repository.raw_store, stores.hierarchy)


def _runtime(
    *, repository: HierarchyRepository, stores: ApiStores, settings: ApiSettings
) -> ApiRuntime:
    """An ApiRuntime wired to the given repository and stores, with no OIDC configured."""
    return ApiRuntime(
        settings=settings,
        repository=repository,
        hierarchy=stores.hierarchy,
        rbac=stores.rbac,
        ingest=_ingest(repository, stores),
        revisions=_revisions(repository, stores),
        authorizer=RoleBindingAuthorizer(),
        api_keys=stores.api_keys,
        credentials=stores.credentials,
        sessions=stores.sessions,
        principals=stores.principals,
        oidc_resolver=None,
        oidc_client=None,
        database_pool=None,
    )


def _settings(*, env: str) -> ApiSettings:
    """``ApiSettings`` for dev-headers in development, or a configured OIDC provider otherwise."""
    kwargs: dict[str, object] = {
        "env": env,
        "database_url": "postgresql://unused",
        "classification_vocabulary": [ClassificationValue(code="open", order=0, discoverable=True)],
    }
    if env == "development":
        kwargs["auth_mode"] = "dev-headers"
    else:
        kwargs["auth_mode"] = "oidc"
        kwargs["login_flow_secret"] = "flow-secret"
        kwargs["oidc"] = OidcSettings(
            issuer="https://idp.example",
            client_id="huron-web",
            client_secret="shh",
            redirect_url="https://app.example/auth/oidc/callback",
        )
    return ApiSettings(**kwargs)


def _session_record(csrf_token: str = "the-csrf-token") -> SessionRecord:
    """A live ``SessionRecord`` for ``alice`` with an overridable CSRF token."""
    now = datetime.now(UTC)
    return SessionRecord(
        id=uuid4(),
        secret_sha256="0" * 64,
        csrf_token=csrf_token,
        subject="alice",
        groups=frozenset(),
        authentication_method="password",
        created_at=now,
        last_seen_at=now,
        idle_expires_at=now + timedelta(hours=1),
        absolute_expires_at=now + timedelta(days=1),
    )


# -- _enforce_csrf --------------------------------------------------------------


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
def test_enforce_csrf_exempts_safe_methods(method: str) -> None:
    """GET, HEAD and OPTIONS pass ``_enforce_csrf`` without a CSRF header."""
    _enforce_csrf(_request(method=method), _session_record())


def test_enforce_csrf_rejects_a_state_change_with_no_header() -> None:
    """A POST with no CSRF header is rejected by ``_enforce_csrf``."""
    with pytest.raises(AuthError):
        _enforce_csrf(_request(method="POST"), _session_record())


def test_enforce_csrf_rejects_a_wrong_token() -> None:
    """A CSRF header that does not match the session's token is rejected."""
    request = _request(method="POST", headers={"X-Huron-CSRF": "wrong"})
    with pytest.raises(AuthError):
        _enforce_csrf(request, _session_record(csrf_token="right"))


def test_enforce_csrf_accepts_the_matching_token() -> None:
    """A CSRF header matching the session's token passes ``_enforce_csrf``."""
    request = _request(method="POST", headers={"X-Huron-CSRF": "right"})
    _enforce_csrf(request, _session_record(csrf_token="right"))


def test_enforce_csrf_rejects_a_non_ascii_header_without_raising_type_error() -> None:
    """A non-ASCII CSRF header fails the comparison as AuthError, not an unhandled TypeError."""
    # Starlette decodes header bytes as latin-1, so a header that was sent
    # as UTF-8 survives as a non-ASCII str; compare_digest refuses to
    # compare that against a str directly, and must not be allowed to
    # escape as a TypeError instead of failing the request closed.
    request = _request(method="POST", headers={"X-Huron-CSRF": "café"})
    with pytest.raises(AuthError):
        _enforce_csrf(request, _session_record(csrf_token="right"))


# -- current_principal: cookie branch and bearer priority --------------------


async def test_current_principal_resolves_a_valid_session_cookie(tmp_path: Path) -> None:
    """A valid session cookie resolves to its principal, with the session left on request.state."""
    stores = memory_stores()
    repository = _repository(tmp_path, stores)
    record, token = create_session("alice", authentication_method="password")
    await stores.sessions.add(record)
    runtime = _runtime(repository=repository, stores=stores, settings=_settings(env="development"))

    request = _request(method="GET", cookies={"huron_session": token})
    principal = await current_principal(request, runtime)

    assert principal.subject == "alice"
    assert principal.authentication_method == "session"
    assert request.state.session.id == record.id


async def test_current_principal_enforces_csrf_for_a_cookie_authed_write(tmp_path: Path) -> None:
    """A cookie-authenticated POST needs the matching X-Huron-CSRF header to succeed."""
    stores = memory_stores()
    repository = _repository(tmp_path, stores)
    record, token = create_session("alice", authentication_method="password")
    await stores.sessions.add(record)
    runtime = _runtime(repository=repository, stores=stores, settings=_settings(env="development"))

    denied = _request(method="POST", cookies={"huron_session": token})
    with pytest.raises(AuthError):
        await current_principal(denied, runtime)

    allowed = _request(
        method="POST",
        cookies={"huron_session": token},
        headers={"X-Huron-CSRF": record.csrf_token},
    )
    principal = await current_principal(allowed, runtime)
    assert principal.subject == "alice"


async def test_current_principal_never_downgrades_a_bearer_caller_to_its_cookie(
    tmp_path: Path,
) -> None:
    """A bearer token takes priority over a cookie even when the bearer path itself then fails.

    A programmatic caller with both a bearer token and a cookie jar must
    be resolved as the bearer credential, even when that bearer path then
    fails - it must never silently fall through to the session cookie.
    """
    stores = memory_stores()
    repository = _repository(tmp_path, stores)
    record, token = create_session("alice", authentication_method="password")
    await stores.sessions.add(record)
    runtime = _runtime(repository=repository, stores=stores, settings=_settings(env="development"))

    request = _request(
        method="GET",
        headers={"Authorization": "Bearer some.jwt.token"},
        cookies={"huron_session": token},
    )
    with pytest.raises(AuthError, match="no OIDC verifier configured"):
        await current_principal(request, runtime)


async def test_current_principal_resolves_a_bearer_jwt_through_the_configured_verifier(
    tmp_path: Path,
) -> None:
    """A bearer JWT resolves through the configured OIDC verifier to its principal."""
    stores = memory_stores()
    repository = _repository(tmp_path, stores)
    resolver = OidcResolver(lambda _token: {"sub": "carol", "groups": ["astro"]})
    runtime = ApiRuntime(
        settings=_settings(env="production"),
        repository=repository,
        hierarchy=stores.hierarchy,
        rbac=stores.rbac,
        ingest=_ingest(repository, stores),
        revisions=_revisions(repository, stores),
        authorizer=RoleBindingAuthorizer(),
        api_keys=stores.api_keys,
        credentials=stores.credentials,
        sessions=stores.sessions,
        principals=stores.principals,
        oidc_resolver=resolver,
        oidc_client=None,
        database_pool=None,
    )

    request = _request(method="GET", headers={"Authorization": "Bearer some.jwt.token"})
    principal = await current_principal(request, runtime)

    assert principal.subject == "carol"
    assert principal.groups == frozenset({"astro"})


async def test_current_principal_refuses_an_oidc_deployment_with_no_credential_at_all(
    tmp_path: Path,
) -> None:
    """A request with no bearer token or session cookie is refused, not given dev headers.

    Outside ``dev-headers``, a request with neither a bearer token nor a
    session cookie is refused rather than falling through to the
    development header resolver.
    """
    stores = memory_stores()
    repository = _repository(tmp_path, stores)
    runtime = _runtime(repository=repository, stores=stores, settings=_settings(env="production"))

    request = _request(method="GET")
    with pytest.raises(AuthError, match="a bearer credential is required"):
        await current_principal(request, runtime)
