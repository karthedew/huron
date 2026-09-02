"""``create_app``'s lifespan wiring: the memory-store default when no
repository is injected, and real OIDC discovery against a respx-mocked
provider - the same seam ``test_auth_oidc.py`` uses, exercised here through
the composition root rather than ``OidcClient`` directly. Also ``/readyz``,
the one app-level route that isn't a lifespan concern."""

from __future__ import annotations

import asyncio
import dataclasses
import shutil
from typing import TYPE_CHECKING, Any, cast

import asyncpg
import httpx
import respx
from fastapi.testclient import TestClient
from httpx import Response

import huron.service.api.app as app_module
from huron.pkg.auth import AuthError
from huron.service.api.app import create_app
from huron.service.api.settings import ApiSettings, ClassificationValue, OidcSettings

if TYPE_CHECKING:
    from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ISSUER = "https://idp.example"


class _FakePool:
    """Stands in for ``asyncpg.Pool``: ``fetchval`` answers, raises the given
    exception, or - standing in for a wedged connection - never returns at
    all, so every failure branch of ``/readyz`` is reachable without a real
    Postgres instance."""

    def __init__(self, *, fails_with: Exception | None = None, hangs: bool = False) -> None:
        self._fails_with = fails_with
        self._hangs = hangs

    async def fetchval(self, *args: object, **kwargs: object) -> object:
        if self._hangs:
            await asyncio.sleep(30)
        if self._fails_with is not None:
            raise self._fails_with
        return 1


def _with_database_pool(app: Any, pool: _FakePool) -> None:
    """Splice a probed pool into the runtime the lifespan already built.

    ``ApiRuntime`` is frozen, so the running app's own instance is replaced
    with one that differs only in ``database_pool`` - the lifespan itself is
    never touched, and every other wiring decision it made survives.
    """
    app.state.runtime = dataclasses.replace(
        app.state.runtime, database_pool=cast("asyncpg.Pool", pool)
    )


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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    created: list[httpx.AsyncClient] = []

    class _TrackingAsyncClient(httpx.AsyncClient):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            created.append(self)

    monkeypatch.setattr(httpx, "AsyncClient", _TrackingAsyncClient)
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
            assert app.state.runtime.oidc_client is not None
            assert app.state.runtime.oidc_resolver is not None
            assert client.get("/healthz").status_code == 200
    assert len(created) == 1
    assert created[0].is_closed


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
        assert app.state.runtime.oidc_client is None
        assert app.state.runtime.oidc_resolver is not None
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
        assert app.state.runtime.repository is not None
        assert app.state.runtime.oidc_resolver is None
        assert client.get("/healthz").status_code == 200


def test_a_request_before_the_lifespan_starts_answers_500_and_never_resolves_a_principal(
    tmp_path: Path,
) -> None:
    """An application whose lifespan never ran has no ``ApiRuntime`` to
    read, so every injected route must refuse rather than fall through to
    a default - the security defect this design closes was exactly a
    missing-state read treated as "no objection"."""
    settings = ApiSettings(
        env="development",
        auth_mode="dev-headers",
        data_root=str(tmp_path / "data"),
        database_url="postgresql://unused",
        classification_vocabulary=[ClassificationValue(code="open", order=0, discoverable=True)],
    )
    app = create_app(settings=settings)
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/api/v1/organizations", headers={"X-Huron-Subject": "alice"})
    assert response.status_code == 500


def test_readyz_reports_ready_while_the_raw_root_exists(tmp_path: Path) -> None:
    settings = ApiSettings(
        env="development",
        auth_mode="dev-headers",
        data_root=str(tmp_path / "data"),
        database_url="postgresql://unused",
        classification_vocabulary=[ClassificationValue(code="open", order=0, discoverable=True)],
    )
    with TestClient(create_app(settings=settings)) as client:
        response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_readyz_refuses_once_the_raw_root_is_gone(tmp_path: Path) -> None:
    settings = ApiSettings(
        env="development",
        auth_mode="dev-headers",
        data_root=str(tmp_path / "data"),
        database_url="postgresql://unused",
        classification_vocabulary=[ClassificationValue(code="open", order=0, discoverable=True)],
    )
    with TestClient(create_app(settings=settings)) as client:
        shutil.rmtree(tmp_path / "data")
        response = client.get("/readyz")
    assert response.status_code == 503
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["code"] == "DEPENDENCY_UNAVAILABLE"
    assert body["context"]["checks"] == {"raw_store": "root is unavailable"}


def test_readyz_reports_ready_when_the_raw_root_and_database_pool_both_answer(
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
        _with_database_pool(app, _FakePool())
        response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_readyz_reports_the_database_check_when_the_pool_does_not_answer(tmp_path: Path) -> None:
    settings = ApiSettings(
        env="development",
        auth_mode="dev-headers",
        data_root=str(tmp_path / "data"),
        database_url="postgresql://unused",
        classification_vocabulary=[ClassificationValue(code="open", order=0, discoverable=True)],
    )
    app = create_app(settings=settings)
    with TestClient(app) as client:
        _with_database_pool(app, _FakePool(fails_with=OSError("connection refused")))
        response = client.get("/readyz")
    assert response.status_code == 503
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["code"] == "DEPENDENCY_UNAVAILABLE"
    checks = body["context"]["checks"]
    assert checks.keys() == {"database"}
    assert checks["database"] == "OSError: connection refused"


def test_readyz_reports_the_database_check_when_the_pool_raises_a_postgres_error(
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
        _with_database_pool(app, _FakePool(fails_with=asyncpg.PostgresError("connection lost")))
        response = client.get("/readyz")
    assert response.status_code == 503
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["code"] == "DEPENDENCY_UNAVAILABLE"
    checks = body["context"]["checks"]
    assert checks.keys() == {"database"}
    assert checks["database"] == "PostgresError: connection lost"


def test_readyz_refuses_promptly_instead_of_hanging_on_a_wedged_pool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A connection that never answers must not hang the probe forever - the
    orchestrator's own probe timeout would otherwise expire first, so the
    timeout inside ``/readyz`` has to fire and turn the stall into a 503."""
    monkeypatch.setattr(app_module, "READINESS_TIMEOUT_SECONDS", 0.01)
    settings = ApiSettings(
        env="development",
        auth_mode="dev-headers",
        data_root=str(tmp_path / "data"),
        database_url="postgresql://unused",
        classification_vocabulary=[ClassificationValue(code="open", order=0, discoverable=True)],
    )
    app = create_app(settings=settings)
    with TestClient(app) as client:
        _with_database_pool(app, _FakePool(hangs=True))
        response = client.get("/readyz")
    assert response.status_code == 503
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["code"] == "DEPENDENCY_UNAVAILABLE"
    checks = body["context"]["checks"]
    assert checks.keys() == {"database"}
    assert checks["database"] == "TimeoutError: "
