"""The cookie half of ``current_principal``: CSRF enforcement, the cookie
attribute helpers, and the priority rule that a bearer credential is never
downgraded to a session even when a valid session cookie also rides along."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from starlette.requests import Request
from starlette.responses import Response

from huron.pkg.auth import ABSOLUTE_TTL, AuthError, SessionRecord, create_session
from huron.pkg.rawstore import PosixRawStore
from huron.service.api.authorization import (
    DEFAULT_SESSION_COOKIE_NAME,
    _cookie_name,
    _enforce_csrf,
    clear_session_cookie,
    current_principal,
    set_session_cookie,
)
from huron.service.api.repository import HierarchyRepository
from huron.service.api.settings import ApiSettings, ClassificationValue, OidcSettings

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


class _State:
    def __init__(self, **kwargs: object) -> None:
        self.__dict__.update(kwargs)


class _App:
    def __init__(self, **kwargs: object) -> None:
        self.state = _State(**kwargs)


def _request(
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    cookies: dict[str, str] | None = None,
    app: object | None = None,
) -> Request:
    raw_headers = [(key.lower().encode(), value.encode()) for key, value in (headers or {}).items()]
    if cookies:
        cookie_header = "; ".join(f"{key}={value}" for key, value in cookies.items())
        raw_headers.append((b"cookie", cookie_header.encode()))
    scope = {"type": "http", "method": method, "path": "/", "headers": raw_headers, "app": app}
    return Request(scope)


def _settings(*, env: str) -> ApiSettings:
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


# -- _cookie_name -------------------------------------------------------------


def test_cookie_name_uses_the_configured_name() -> None:
    request = _request(app=_App(settings=_settings(env="development")))
    assert _cookie_name(request) == "huron_session"


def test_cookie_name_falls_back_to_the_default_without_settings() -> None:
    request = _request(app=_App())
    assert _cookie_name(request) == DEFAULT_SESSION_COOKIE_NAME


# -- _enforce_csrf --------------------------------------------------------------


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
def test_enforce_csrf_exempts_safe_methods(method: str) -> None:
    _enforce_csrf(_request(method=method), _session_record())


def test_enforce_csrf_rejects_a_state_change_with_no_header() -> None:
    with pytest.raises(AuthError):
        _enforce_csrf(_request(method="POST"), _session_record())


def test_enforce_csrf_rejects_a_wrong_token() -> None:
    request = _request(method="POST", headers={"X-Huron-CSRF": "wrong"})
    with pytest.raises(AuthError):
        _enforce_csrf(request, _session_record(csrf_token="right"))


def test_enforce_csrf_accepts_the_matching_token() -> None:
    request = _request(method="POST", headers={"X-Huron-CSRF": "right"})
    _enforce_csrf(request, _session_record(csrf_token="right"))


def test_enforce_csrf_rejects_a_non_ascii_header_without_raising_type_error() -> None:
    # Starlette decodes header bytes as latin-1, so a header that was sent
    # as UTF-8 survives as a non-ASCII str; compare_digest refuses to
    # compare that against a str directly, and must not be allowed to
    # escape as a TypeError instead of failing the request closed.
    request = _request(method="POST", headers={"X-Huron-CSRF": "café"})
    with pytest.raises(AuthError):
        _enforce_csrf(request, _session_record(csrf_token="right"))


# -- set_session_cookie / clear_session_cookie -----------------------------


def test_set_session_cookie_is_httponly_lax_and_secure_outside_development() -> None:
    response = Response()
    set_session_cookie(response, _settings(env="production"), "hs_abc_def")
    cookie = response.headers.get("set-cookie")
    assert cookie is not None
    assert cookie.startswith("huron_session=hs_abc_def")
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Path=/" in cookie
    assert "Secure" in cookie
    assert f"Max-Age={int(ABSOLUTE_TTL.total_seconds())}" in cookie


def test_set_session_cookie_omits_secure_in_development() -> None:
    response = Response()
    set_session_cookie(response, _settings(env="development"), "hs_abc_def")
    cookie = response.headers.get("set-cookie")
    assert cookie is not None
    assert "Secure" not in cookie


def test_clear_session_cookie_expires_the_cookie_immediately() -> None:
    response = Response()
    clear_session_cookie(response, _settings(env="production"))
    cookie = response.headers.get("set-cookie")
    assert cookie is not None
    assert cookie.startswith("huron_session=")
    assert "Max-Age=0" in cookie


# -- current_principal: cookie branch and bearer priority --------------------


async def test_current_principal_resolves_a_valid_session_cookie(tmp_path: Path) -> None:
    repository = HierarchyRepository(PosixRawStore(str(tmp_path / "raw")))
    record, token = create_session("alice", authentication_method="password")
    await repository.sessions.add(record)
    app = _App(repository=repository, settings=_settings(env="development"))

    request = _request(method="GET", cookies={"huron_session": token}, app=app)
    principal = await current_principal(request)

    assert principal.subject == "alice"
    assert principal.authentication_method == "session"
    assert request.state.session.id == record.id


async def test_current_principal_enforces_csrf_for_a_cookie_authed_write(tmp_path: Path) -> None:
    repository = HierarchyRepository(PosixRawStore(str(tmp_path / "raw")))
    record, token = create_session("alice", authentication_method="password")
    await repository.sessions.add(record)
    app = _App(repository=repository, settings=_settings(env="development"))

    denied = _request(method="POST", cookies={"huron_session": token}, app=app)
    with pytest.raises(AuthError):
        await current_principal(denied)

    allowed = _request(
        method="POST",
        cookies={"huron_session": token},
        headers={"X-Huron-CSRF": record.csrf_token},
        app=app,
    )
    principal = await current_principal(allowed)
    assert principal.subject == "alice"


async def test_current_principal_never_downgrades_a_bearer_caller_to_its_cookie(
    tmp_path: Path,
) -> None:
    """A programmatic caller with both a bearer token and a cookie jar must
    be resolved as the bearer credential, even when that bearer path then
    fails - it must never silently fall through to the session cookie."""
    repository = HierarchyRepository(PosixRawStore(str(tmp_path / "raw")))
    record, token = create_session("alice", authentication_method="password")
    await repository.sessions.add(record)
    app = _App(repository=repository, settings=_settings(env="development"))

    request = _request(
        method="GET",
        headers={"Authorization": "Bearer some.jwt.token"},
        cookies={"huron_session": token},
        app=app,
    )
    with pytest.raises(AuthError, match="no OIDC verifier configured"):
        await current_principal(request)
