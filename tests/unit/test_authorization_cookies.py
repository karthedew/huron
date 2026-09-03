"""The service's two cookies, proved against CookieSpec's issue, revoke and read methods.

Covers exact issue/revoke ``Set-Cookie`` header shape, the ``secure``
flag rule across environments, and reading a cookie's value back from a
request.
"""

from __future__ import annotations

import pytest
from starlette.requests import Request
from starlette.responses import Response

from huron.pkg.auth import ABSOLUTE_TTL
from huron.service.api.authorization import login_flow_cookie, session_cookie
from huron.service.api.settings import ApiSettings, ClassificationValue, OidcSettings

pytestmark = pytest.mark.unit


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


# -- session_cookie / login_flow_cookie: the four Set-Cookie headers --------
#
# ``issue`` carries no ``expires`` attribute (only ``max-age``), so its
# header is fully deterministic and pinned byte for byte. ``revoke`` sets
# ``max-age=0`` *and* an ``expires`` attribute the stdlib cookie jar derives
# from the wall clock at call time - every other attribute is still pinned
# exactly, and ``expires``'s mere presence stands in for it.


def _cookie_attributes_excluding_expiry(header: str) -> set[str]:
    """The Set-Cookie header's attributes, with the wall-clock-dependent expires excluded."""
    parts = (part.strip() for part in header.split(";"))
    return {part for part in parts if not part.lower().startswith("expires=")}


def test_session_cookie_issue_header_is_byte_identical_in_development() -> None:
    """The session cookie's issued header omits Secure and matches byte for byte."""
    response = Response()
    session_cookie(_settings(env="development")).issue(response, "hs_abc_def")
    assert response.headers["set-cookie"] == (
        f"huron_session=hs_abc_def; HttpOnly; Max-Age={int(ABSOLUTE_TTL.total_seconds())}; "
        "Path=/; SameSite=lax"
    )


def test_session_cookie_issue_header_is_byte_identical_in_production() -> None:
    """The session cookie's issued header adds Secure and matches byte for byte."""
    response = Response()
    session_cookie(_settings(env="production")).issue(response, "hs_abc_def")
    assert response.headers["set-cookie"] == (
        f"huron_session=hs_abc_def; HttpOnly; Max-Age={int(ABSOLUTE_TTL.total_seconds())}; "
        "Path=/; SameSite=lax; Secure"
    )


def test_session_cookie_revoke_header_is_byte_identical_apart_from_wall_clock_expiry() -> None:
    """The session cookie's revoke header sets Max-Age=0 and expires in both environments."""
    for env in ("development", "production"):
        response = Response()
        session_cookie(_settings(env=env)).revoke(response)
        header = response.headers["set-cookie"]
        assert "expires=" in header.lower()
        expected = {'huron_session=""', "HttpOnly", "Max-Age=0", "Path=/", "SameSite=lax"}
        if env == "production":
            expected.add("Secure")
        assert _cookie_attributes_excluding_expiry(header) == expected


def test_login_flow_cookie_issue_header_is_byte_identical_in_development() -> None:
    """The login-flow cookie's issued header omits Secure and matches byte for byte."""
    response = Response()
    login_flow_cookie(_settings(env="development")).issue(response, "flow-value")
    assert response.headers["set-cookie"] == (
        "huron_login=flow-value; HttpOnly; Max-Age=600; Path=/auth; SameSite=lax"
    )


def test_login_flow_cookie_issue_header_is_byte_identical_in_production() -> None:
    """The login-flow cookie's issued header adds Secure and matches byte for byte."""
    response = Response()
    login_flow_cookie(_settings(env="production")).issue(response, "flow-value")
    assert response.headers["set-cookie"] == (
        "huron_login=flow-value; HttpOnly; Max-Age=600; Path=/auth; SameSite=lax; Secure"
    )


def test_login_flow_cookie_revoke_header_is_byte_identical_apart_from_wall_clock_expiry() -> None:
    """The login-flow cookie's revoke header sets Max-Age=0 and expires in both environments."""
    for env in ("development", "production"):
        response = Response()
        login_flow_cookie(_settings(env=env)).revoke(response)
        header = response.headers["set-cookie"]
        assert "expires=" in header.lower()
        expected = {'huron_login=""', "HttpOnly", "Max-Age=0", "Path=/auth", "SameSite=lax"}
        if env == "production":
            expected.add("Secure")
        assert _cookie_attributes_excluding_expiry(header) == expected


# -- CookieSpec.read ----------------------------------------------------------


def _request_with_cookie(cookie_header: bytes | None) -> Request:
    """A bare GET request carrying the given raw Cookie header, or none at all."""
    headers = [(b"cookie", cookie_header)] if cookie_header else []
    scope = {"type": "http", "method": "GET", "path": "/", "headers": headers, "app": None}
    return Request(scope)


def test_session_cookie_read_returns_the_value_under_its_configured_name() -> None:
    """``CookieSpec.read`` returns the value stored under its configured cookie name."""
    request = _request_with_cookie(b"huron_session=hs_abc")
    assert session_cookie(_settings(env="development")).read(request) == "hs_abc"


def test_session_cookie_read_is_none_with_no_cookie_at_all() -> None:
    """``CookieSpec.read`` returns None when the request carries no cookies."""
    request = _request_with_cookie(None)
    assert session_cookie(_settings(env="development")).read(request) is None
