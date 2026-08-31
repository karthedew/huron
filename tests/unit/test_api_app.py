"""``create_app``'s lifespan wiring: the memory-store default when no
repository is injected, and real OIDC discovery against a respx-mocked
provider - the same seam ``test_auth_oidc.py`` uses, exercised here through
the composition root rather than ``OidcClient`` directly."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
import respx
from fastapi.testclient import TestClient
from httpx import Response

from huron.pkg.auth import AuthError
from huron.service.api.app import create_app
from huron.service.api.settings import ApiSettings, ClassificationValue, OidcSettings

if TYPE_CHECKING:
    from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ISSUER = "https://idp.example"


def _oidc_settings(tmp_path: Path) -> ApiSettings:
    return ApiSettings(
        env="production",
        auth_mode="oidc",
        data_root=str(tmp_path / "data"),
        database_url="postgresql://unused",
        classification_vocabulary=[ClassificationValue(code="open", order=0, discoverable=True)],
        login_flow_secret="flow-secret",
        oidc=OidcSettings(
            issuer=ISSUER,
            client_id="huron-web",
            client_secret="shh",
            redirect_url="https://app.example/auth/oidc/callback",
        ),
    )


def test_lifespan_discovers_the_configured_oidc_provider_and_closes_its_client(
    tmp_path: Path,
) -> None:
    with respx.mock:
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
        app = create_app(settings=_oidc_settings(tmp_path))
        with TestClient(app) as client:
            assert app.state.oidc_client is not None
            assert app.state.oidc_resolver is not None
            assert app.state.http_client is not None
            assert client.get("/healthz").status_code == 200
        assert app.state.http_client.is_closed


def test_lifespan_closes_the_http_client_when_oidc_discovery_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A discovery failure during startup must not leak the ``AsyncClient``
    opened to make the discovery request in the first place."""
    created: list[httpx.AsyncClient] = []

    class _TrackingAsyncClient(httpx.AsyncClient):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            created.append(self)

    monkeypatch.setattr(httpx, "AsyncClient", _TrackingAsyncClient)
    with respx.mock:
        respx.get(f"{ISSUER}/.well-known/openid-configuration").mock(return_value=Response(500))
        app = create_app(settings=_oidc_settings(tmp_path))
        with pytest.raises(AuthError), TestClient(app):
            pass
    assert len(created) == 1
    assert created[0].is_closed


def test_lifespan_prefers_an_injected_oidc_verifier_over_discovery(tmp_path: Path) -> None:
    """The bearer-JWT test-injection seam stays: when a verifier is passed
    directly, no discovery call happens at all."""
    settings = _oidc_settings(tmp_path)
    app = create_app(settings=settings, oidc_verify=lambda _token: {"sub": "svc"})
    with TestClient(app) as client:
        assert app.state.oidc_client is None
        assert app.state.oidc_resolver is not None
        assert app.state.http_client is None
        assert client.get("/healthz").status_code == 200


def test_lifespan_defaults_to_the_memory_repository_when_none_is_injected(
    tmp_path: Path,
) -> None:
    settings = ApiSettings(
        env="development",
        auth_mode="dev-headers",
        data_root=str(tmp_path / "data"),
        database_url="postgresql://unused",
        classification_vocabulary=[ClassificationValue(code="open", order=0, discoverable=True)],
    )
    app = create_app(settings=settings)
    with TestClient(app) as client:
        assert app.state.repository is not None
        assert app.state.database_pool is None
        assert app.state.oidc_resolver is None
        assert app.state.http_client is None
        assert client.get("/healthz").status_code == 200
