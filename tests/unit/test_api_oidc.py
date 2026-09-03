"""The browser half of the OIDC code flow through the HTTP surface.

``GET /auth/oidc/start`` redirects to the IdP with a signed flow cookie, and
``GET /auth/oidc/callback`` verifies state, exchanges the code, and starts a
session - the same discovery and JWKS seams ``test_api_app.py`` and
``test_auth_oidc.py`` exercise, driven here through the actual routes.

``app.state.oidc_client`` is only ever a real, discovered client when no
``oidc_verify`` is injected (see ``_configure_oidc`` in ``app.py``) - the
bearer-JWT test-injection seam leaves it ``None``. The code-flow routes need
the real client, so these tests run discovery for real against a
respx-mocked provider, exactly like ``test_api_app.py``'s discovery tests.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
import respx
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from httpx import Response
from jwt.algorithms import RSAAlgorithm

from huron.pkg.rawstore import PosixRawStore
from huron.service.api.app import create_app
from huron.service.api.repository import HierarchyRepository
from huron.service.api.settings import ApiSettings, ClassificationValue, OidcSettings

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

pytestmark = pytest.mark.unit

ISSUER = "https://idp.example"
CLIENT_ID = "huron-web"
KID = "test-signing-key"


@pytest.fixture(scope="session")
def private_key() -> RSAPrivateKey:
    """A session-scoped RSA private key used to sign every mock IdP token in this module."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def serve_jwks(monkeypatch: pytest.MonkeyPatch, private_key: RSAPrivateKey) -> None:
    """The mock IdP's JWKS endpoint is served from `private_key`, bypassing an actual fetch."""
    jwk = RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    jwk["kid"], jwk["alg"], jwk["use"] = KID, "RS256", "sig"
    document = {"keys": [jwk]}
    monkeypatch.setattr(jwt.PyJWKClient, "fetch_data", lambda self: document)


def _id_token(private_key: RSAPrivateKey, *, nonce: str, **overrides: object) -> str:
    """A signed ID token for user-123 with the given nonce and any claim overrides applied."""
    issued = datetime.now(UTC)
    claims: dict[str, object] = {
        "iss": ISSUER,
        "sub": "user-123",
        "aud": CLIENT_ID,
        "exp": int((issued + timedelta(minutes=5)).timestamp()),
        "iat": int(issued.timestamp()),
        "nonce": nonce,
        "name": "Ada Lovelace",
        "email": "ada@example.org",
        "groups": ["physics"],
    }
    claims.update(overrides)
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": KID})


def _mock_discovery() -> None:
    """Mocks the IdP's OpenID discovery document with the authorize, token and jwks endpoints."""
    respx.get(f"{ISSUER}/.well-known/openid-configuration").mock(
        return_value=Response(
            200,
            json={
                "issuer": ISSUER,
                "authorization_endpoint": f"{ISSUER}/authorize",
                "token_endpoint": f"{ISSUER}/token",
                "jwks_uri": f"{ISSUER}/jwks",
            },
        )
    )


def _oidc_settings(tmp_path: Path, *, env: str = "development") -> ApiSettings:
    """An ApiSettings for oidc auth against the mocked issuer, development by default."""
    return ApiSettings(
        # "development" (not "production") deliberately by default: TestClient's
        # base URL is plain http, and a Secure session cookie would silently be
        # withheld by the cookie jar on the very next request otherwise. Callers
        # that only need to inspect one Set-Cookie header - never a round trip -
        # can pass env="production" instead.
        env=env,
        auth_mode="oidc",
        data_root=str(tmp_path / "data"),
        database_url="postgresql://unused",
        classification_vocabulary=[ClassificationValue(code="open", order=0, discoverable=True)],
        login_flow_secret="flow-secret",
        web_app_url="https://app.example",
        oidc=OidcSettings(
            issuer=ISSUER,
            client_id=CLIENT_ID,
            client_secret="shh",
            redirect_url="https://api.example/auth/oidc/callback",
        ),
    )


@pytest.fixture
def client(tmp_path: Path, serve_jwks: None) -> Iterator[TestClient]:
    """A TestClient wired for the oidc auth mode, with discovery mocked against the fake issuer."""
    settings = _oidc_settings(tmp_path)
    repository = HierarchyRepository(
        PosixRawStore(settings.data_root),
        classification_vocabulary=tuple(value.code for value in settings.classification_vocabulary),
    )
    with respx.mock:
        _mock_discovery()
        with TestClient(create_app(settings=settings, repository=repository)) as client:
            yield client


def _start(client: TestClient, *, return_to: str = "/") -> Response:
    """Starts the OIDC code flow for `client` and returns the un-followed redirect response."""
    return client.get("/auth/oidc/start", params={"return_to": return_to}, follow_redirects=False)


# -- /auth/oidc/start ---------------------------------------------------------


def test_oidc_start_redirects_to_the_authorize_url_with_pkce_and_sets_the_flow_cookie(
    client: TestClient,
) -> None:
    """Starting the flow 302s to the IdP with PKCE params and sets a scoped flow cookie."""
    response = _start(client, return_to="/projects/9")
    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith(f"{ISSUER}/authorize?")
    query = parse_qs(urlsplit(location).query)
    assert query["client_id"] == [CLIENT_ID]
    assert query["response_type"] == ["code"]
    assert query["code_challenge_method"] == ["S256"]
    assert {"state", "nonce", "code_challenge"} <= query.keys()

    cookie = response.headers["set-cookie"]
    assert cookie.startswith("huron_login=")
    assert "HttpOnly" in cookie
    assert "Path=/auth" in cookie
    assert "SameSite=lax" in cookie
    # Bound to LoginFlow.decode's own max_age - a cookie the browser still
    # holds must never be rejected as stale, and vice versa.
    assert "Max-Age=600" in cookie


def test_oidc_start_flow_cookie_omits_secure_in_development(client: TestClient) -> None:
    """The flow cookie omits the Secure attribute in a development environment."""
    cookie = _start(client).headers["set-cookie"]
    assert "Secure" not in cookie


def test_oidc_start_flow_cookie_is_secure_outside_development(tmp_path: Path) -> None:
    """The flow cookie carries the Secure attribute outside a development environment."""
    settings = _oidc_settings(tmp_path, env="production")
    repository = HierarchyRepository(
        PosixRawStore(settings.data_root),
        classification_vocabulary=tuple(value.code for value in settings.classification_vocabulary),
    )
    with respx.mock:
        _mock_discovery()
        with TestClient(create_app(settings=settings, repository=repository)) as production_client:
            cookie = _start(production_client).headers["set-cookie"]
    assert "Secure" in cookie


def test_oidc_start_drops_a_return_to_that_is_not_a_local_path(
    client: TestClient, private_key: RSAPrivateKey
) -> None:
    """A protocol-relative ``return_to`` is dropped in favor of the app root.

    ``//evil.example`` looks like a path but is protocol-relative; it must
    land the callback at the app root, never at an attacker's host.
    """
    start = _start(client, return_to="//evil.example")
    query = parse_qs(urlsplit(start.headers["location"]).query)
    state, nonce = query["state"][0], query["nonce"][0]
    respx.post(f"{ISSUER}/token").mock(
        return_value=Response(200, json={"id_token": _id_token(private_key, nonce=nonce)})
    )
    callback = client.get(
        "/auth/oidc/callback",
        params={"code": "the-auth-code", "state": state},
        follow_redirects=False,
    )
    assert callback.headers["location"] == "https://app.example/"


def test_oidc_start_404s_when_oidc_is_not_configured(tmp_path: Path) -> None:
    """``/auth/oidc/start`` 404s when the deployment is not configured for OIDC auth."""
    settings = ApiSettings(
        env="development",
        auth_mode="dev-headers",
        data_root=str(tmp_path / "data"),
        database_url="postgresql://unused",
        classification_vocabulary=[ClassificationValue(code="open", order=0, discoverable=True)],
    )
    repository = HierarchyRepository(
        PosixRawStore(settings.data_root),
        classification_vocabulary=tuple(value.code for value in settings.classification_vocabulary),
    )
    with TestClient(create_app(settings=settings, repository=repository)) as unconfigured:
        response = unconfigured.get("/auth/oidc/start", follow_redirects=False)
    assert response.status_code == 404


# -- /auth/oidc/callback -------------------------------------------------------


def test_oidc_callback_exchanges_the_code_and_redirects_into_the_web_app(
    client: TestClient, private_key: RSAPrivateKey
) -> None:
    """A valid callback exchanges the code, starts a session, and redirects to the return_to."""
    start = _start(client, return_to="/projects/9")
    query = parse_qs(urlsplit(start.headers["location"]).query)
    state, nonce = query["state"][0], query["nonce"][0]
    respx.post(f"{ISSUER}/token").mock(
        return_value=Response(200, json={"id_token": _id_token(private_key, nonce=nonce)})
    )

    callback = client.get(
        "/auth/oidc/callback",
        params={"code": "the-auth-code", "state": state},
        follow_redirects=False,
    )
    assert callback.status_code == 302
    assert callback.headers["location"] == "https://app.example/projects/9"
    assert client.cookies.get("huron_session") is not None
    assert client.cookies.get("huron_login") is None

    session = client.get("/auth/session")
    assert session.status_code == 200
    info = session.json()
    assert info["subject"] == "user-123"
    assert info["authentication_method"] == "session"
    assert info["groups"] == ["physics"]


def test_oidc_callback_rejects_a_state_that_does_not_match_the_flow_cookie(
    client: TestClient,
) -> None:
    """A callback whose state does not match the flow cookie's state is refused with 401."""
    _start(client)
    response = client.get(
        "/auth/oidc/callback",
        params={"code": "the-auth-code", "state": "a-forged-state"},
        follow_redirects=False,
    )
    assert response.status_code == 401


def test_oidc_callback_rejects_a_request_with_no_flow_cookie_at_all(client: TestClient) -> None:
    """A callback with no flow cookie at all is refused with 401."""
    response = client.get(
        "/auth/oidc/callback",
        params={"code": "the-auth-code", "state": "does-not-matter"},
        follow_redirects=False,
    )
    assert response.status_code == 401
