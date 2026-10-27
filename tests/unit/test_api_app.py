"""Application resource lifetimes, lazy company discovery and readiness probes."""

from __future__ import annotations

import asyncio
import dataclasses
import shutil
import time
from pathlib import Path
from typing import Any, cast

import asyncpg
import httpx
from fastapi.testclient import TestClient

import huron.applications.api.app as app_module
from huron.applications.api.app import create_app
from huron.applications.api.settings import ApiSettings, ClassificationValue, OidcSettings
from huron.core.metastore import (
    PostgresApiKeyStore,
    PostgresPrincipalStore,
    PostgresRbacStore,
)
from tests.unit.support import memory_stores

import pytest

pytestmark = pytest.mark.unit

ISSUER = "https://idp.example"


class _FakePool:
    """A fake ``asyncpg.Pool`` whose ``fetchval`` can answer, raise, or hang on command.

    Standing in for a wedged connection when it hangs, it makes every
    failure branch of ``/readyz`` reachable without a real Postgres
    instance.
    """

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
    """Settings for an app wired for OIDC auth against the fake ``ISSUER``."""
    return ApiSettings(
        env="production",
        auth_mode="oidc",
        data_root=str(tmp_path / "data"),
        database_url="postgresql://unused",
        classification_vocabulary=[ClassificationValue(code="open", order=0, discoverable=True)],
        oidc=OidcSettings(
            issuer=ISSUER,
            client_id="huron-web",
        ),
    )


@pytest.mark.parametrize("startup_failure", [None, "storage", "issuer"])
def test_company_client_closes_without_discovering_at_startup(
    tmp_path: Path, fake_issuer, clock, startup_failure: str | None
) -> None:
    """Both normal shutdown and failed startup close the lazy issuer transport."""

    class ClosingTransport(httpx.ASGITransport):
        closed = False

        async def aclose(self) -> None:
            self.closed = True
            await super().aclose()

    transport = ClosingTransport(app=fake_issuer.app)
    settings = _oidc_settings(tmp_path).model_copy(
        update={"oidc": OidcSettings(issuer=fake_issuer.issuer, client_id=fake_issuer.client_id)}
    )
    if startup_failure == "issuer":
        settings.oidc = OidcSettings(issuer="invalid", client_id=fake_issuer.client_id)
    if startup_failure == "storage":
        (tmp_path / "data").write_text("blocks generation directory")
    app = create_app(
        settings=settings, stores=memory_stores(), company_idp_transport=transport, clock=clock
    )
    if startup_failure:
        error = ValueError if startup_failure == "issuer" else NotADirectoryError
        with pytest.raises(error), TestClient(app):
            pass
    else:
        with TestClient(app) as client:
            assert app.state.runtime.oidc_resolver is not None
            assert app.state.runtime.clock is clock
            assert client.get("/healthz").status_code == 200
            assert not transport.closed
    assert transport.closed
    assert all(count == 0 for count in fake_issuer.hits.values())


def test_lifespan_closes_the_pool_when_generations_initialization_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A raw-store initialization failure after the pool opens still closes that pool.

    Application startup initializes the generation store's directory layout,
    which fails when ``data_root`` already exists as a regular file
    rather than a directory; the pool opened just before it must not
    leak on every restart of a crash loop.
    """
    closed = 0

    class _ClosingPool:
        async def close(self) -> None:
            nonlocal closed
            closed += 1

    async def _fake_create_pool(*args: object, **kwargs: object) -> _ClosingPool:
        return _ClosingPool()

    monkeypatch.setattr(asyncpg, "create_pool", _fake_create_pool)
    data_root = tmp_path / "data"
    data_root.write_text("occupies the path a directory needs")
    settings = ApiSettings(
        env="development",
        auth_mode="dev-headers",
        data_root=str(data_root),
        database_url="postgresql://unused",
        classification_vocabulary=[ClassificationValue(code="open", order=0, discoverable=True)],
    )
    app = create_app(settings=settings)
    with pytest.raises(NotADirectoryError), TestClient(app):
        pass
    assert closed == 1


def test_lifespan_leaves_the_oidc_resolver_unset_when_no_provider_is_configured(
    tmp_path: Path,
) -> None:
    """A dev-headers app with no OIDC provider wires and serves with the resolver unset."""
    settings = ApiSettings(
        env="development",
        auth_mode="dev-headers",
        data_root=str(tmp_path / "data"),
        database_url="postgresql://unused",
        classification_vocabulary=[ClassificationValue(code="open", order=0, discoverable=True)],
    )
    app = create_app(settings=settings, stores=memory_stores())
    with TestClient(app) as client:
        assert app.state.runtime.generations is not None
        assert app.state.runtime.oidc_resolver is None
        assert client.get("/healthz").status_code == 200


def test_create_app_without_injected_stores_opens_one_pool_and_wires_every_postgres_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no ``stores`` injected, the app opens exactly one pool and wires it to Postgres."""
    calls: list[tuple[object, ...]] = []

    class _RecordingPool:
        async def close(self) -> None:
            pass

    async def _fake_create_pool(*args: object, **kwargs: object) -> _RecordingPool:
        calls.append(args)
        assert kwargs == {}
        return _RecordingPool()

    monkeypatch.setattr(asyncpg, "create_pool", _fake_create_pool)
    settings = ApiSettings(
        env="development",
        auth_mode="dev-headers",
        data_root=str(tmp_path / "data"),
        database_url="postgresql://example/huron",
        classification_vocabulary=[ClassificationValue(code="open", order=0, discoverable=True)],
    )
    app = create_app(settings=settings)
    with TestClient(app) as client:
        runtime = client.app.state.runtime
        assert calls == [("postgresql://example/huron",)]
        assert isinstance(runtime.rbac, PostgresRbacStore)
        assert isinstance(runtime.api_keys, PostgresApiKeyStore)
        assert isinstance(runtime.principals, PostgresPrincipalStore)


def test_create_app_with_injected_stores_never_opens_a_pool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With ``stores`` injected, no pool is opened and ``database_pool`` stays ``None``."""
    calls: list[tuple[object, ...]] = []

    async def _fake_create_pool(*args: object, **kwargs: object) -> object:
        calls.append(args)
        raise AssertionError("asyncpg.create_pool must not run when stores are injected")

    monkeypatch.setattr(asyncpg, "create_pool", _fake_create_pool)
    settings = ApiSettings(
        env="development",
        auth_mode="dev-headers",
        data_root=str(tmp_path / "data"),
        database_url="postgresql://unused",
        classification_vocabulary=[ClassificationValue(code="open", order=0, discoverable=True)],
    )
    app = create_app(settings=settings, stores=memory_stores())
    with TestClient(app) as client:
        assert calls == []
        assert client.app.state.runtime.database_pool is None


def test_injected_stores_are_the_ones_the_runtime_exposes(tmp_path: Path) -> None:
    """Injected ``ApiStores`` are exactly what ``app.state.runtime`` publishes.

    Every field is checked by identity, not equality: the runtime must hand
    back the very objects a caller injected, never copies or fresh defaults
    built alongside them.
    """
    settings = ApiSettings(
        env="development",
        auth_mode="dev-headers",
        data_root=str(tmp_path / "data"),
        database_url="postgresql://unused",
        classification_vocabulary=[
            ClassificationValue(code="open", order=0, discoverable=True),
            ClassificationValue(code="restricted", order=1, discoverable=False),
        ],
    )
    stores = memory_stores()
    with TestClient(create_app(settings=settings, stores=stores)) as client:
        runtime = client.app.state.runtime
        assert runtime.rbac is stores.rbac
        assert runtime.api_keys is stores.api_keys
        assert runtime.principals is stores.principals
        actual = [
            (item.code, item.order, item.discoverable)
            for item in runtime.authorizer.classifications
        ]
        expected = [
            (value.code, value.order, value.discoverable)
            for value in settings.classification_vocabulary
        ]
        assert actual == expected


async def test_credential_authentication_uses_the_wired_key_store(tmp_path: Path) -> None:
    """Credential resolution verifies and touches keys in the injected store."""
    from huron.applications.api.runtime import credential_authentication
    from huron.core.security.apikeys import create_api_key

    settings = ApiSettings(
        env="development",
        auth_mode="dev-headers",
        data_root=str(tmp_path / "data"),
        database_url="postgresql://unused",
        classification_vocabulary=[ClassificationValue(code="open", order=0, discoverable=True)],
    )
    stores = memory_stores()
    record, token = create_api_key("alice", name="laptop")
    await stores.api_keys.add(record)
    with TestClient(create_app(settings=settings, stores=stores)) as client:
        runtime = client.app.state.runtime
        resolved = await credential_authentication(runtime).resolve(bearer_token=token)
        assert resolved.actor.subject == "alice"
        assert stores.api_keys.touched == [record.key_id]


def test_a_request_before_the_lifespan_starts_answers_500_and_never_resolves_a_principal(
    tmp_path: Path,
) -> None:
    """A request before the lifespan runs answers 500 instead of resolving a principal.

    An application whose lifespan never ran has no ``ApiRuntime`` to read,
    so every injected route must refuse rather than fall through to a
    default - the security defect this design closes was exactly a
    missing-state read treated as "no objection".
    """
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
    """``/readyz`` reports ready while the raw storage root exists."""
    settings = ApiSettings(
        env="development",
        auth_mode="dev-headers",
        data_root=str(tmp_path / "data"),
        database_url="postgresql://unused",
        classification_vocabulary=[ClassificationValue(code="open", order=0, discoverable=True)],
    )
    with TestClient(create_app(settings=settings, stores=memory_stores())) as client:
        response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_readyz_refuses_once_the_raw_root_is_gone(tmp_path: Path) -> None:
    """``/readyz`` answers 503 with a raw-store check once the raw root is removed."""
    settings = ApiSettings(
        env="development",
        auth_mode="dev-headers",
        data_root=str(tmp_path / "data"),
        database_url="postgresql://unused",
        classification_vocabulary=[ClassificationValue(code="open", order=0, discoverable=True)],
    )
    with TestClient(create_app(settings=settings, stores=memory_stores())) as client:
        shutil.rmtree(tmp_path / "data")
        response = client.get("/readyz")
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "30"
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["code"] == "DEPENDENCY_UNAVAILABLE"
    assert body["context"]["checks"] == {"generations": "root is unavailable"}


def test_readyz_reports_ready_when_the_raw_root_and_database_pool_both_answer(
    tmp_path: Path,
) -> None:
    """``/readyz`` reports ready when both the raw root and the database pool answer."""
    settings = ApiSettings(
        env="development",
        auth_mode="dev-headers",
        data_root=str(tmp_path / "data"),
        database_url="postgresql://unused",
        classification_vocabulary=[ClassificationValue(code="open", order=0, discoverable=True)],
    )
    app = create_app(settings=settings, stores=memory_stores())
    with TestClient(app) as client:
        _with_database_pool(app, _FakePool())
        response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_readyz_reports_the_database_check_when_the_pool_does_not_answer(tmp_path: Path) -> None:
    """``/readyz`` reports the database check by name when the pool raises ``OSError``."""
    settings = ApiSettings(
        env="development",
        auth_mode="dev-headers",
        data_root=str(tmp_path / "data"),
        database_url="postgresql://unused",
        classification_vocabulary=[ClassificationValue(code="open", order=0, discoverable=True)],
    )
    app = create_app(settings=settings, stores=memory_stores())
    with TestClient(app) as client:
        _with_database_pool(app, _FakePool(fails_with=OSError("connection refused")))
        response = client.get("/readyz")
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "30"
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["code"] == "DEPENDENCY_UNAVAILABLE"
    checks = body["context"]["checks"]
    assert checks.keys() == {"database"}
    assert checks["database"] == "OSError: connection refused"


def test_readyz_reports_the_database_check_when_the_pool_raises_a_postgres_error(
    tmp_path: Path,
) -> None:
    """``/readyz`` reports the database check by name when the pool raises ``PostgresError``."""
    settings = ApiSettings(
        env="development",
        auth_mode="dev-headers",
        data_root=str(tmp_path / "data"),
        database_url="postgresql://unused",
        classification_vocabulary=[ClassificationValue(code="open", order=0, discoverable=True)],
    )
    app = create_app(settings=settings, stores=memory_stores())
    with TestClient(app) as client:
        _with_database_pool(app, _FakePool(fails_with=asyncpg.PostgresError("connection lost")))
        response = client.get("/readyz")
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "30"
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["code"] == "DEPENDENCY_UNAVAILABLE"
    checks = body["context"]["checks"]
    assert checks.keys() == {"database"}
    assert checks["database"] == "PostgresError: connection lost"


def test_readyz_refuses_promptly_instead_of_hanging_on_a_wedged_pool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A wedged database pool times out instead of hanging the ``/readyz`` probe forever.

    A connection that never answers must not hang the probe forever - the
    orchestrator's own probe timeout would otherwise expire first, so the
    timeout inside ``/readyz`` has to fire and turn the stall into a 503.
    """
    monkeypatch.setattr(app_module, "READINESS_TIMEOUT_SECONDS", 0.01)
    settings = ApiSettings(
        env="development",
        auth_mode="dev-headers",
        data_root=str(tmp_path / "data"),
        database_url="postgresql://unused",
        classification_vocabulary=[ClassificationValue(code="open", order=0, discoverable=True)],
    )
    app = create_app(settings=settings, stores=memory_stores())
    with TestClient(app) as client:
        _with_database_pool(app, _FakePool(hangs=True))
        response = client.get("/readyz")
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "30"
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["code"] == "DEPENDENCY_UNAVAILABLE"
    checks = body["context"]["checks"]
    assert checks.keys() == {"database"}
    assert checks["database"] == "TimeoutError: "


def test_readyz_refuses_promptly_instead_of_hanging_on_a_wedged_generations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A wedged generation-store mount times out instead of hanging the ``/readyz`` probe forever.

    A ``stat`` that never answers must not hang the probe forever - the
    orchestrator's own probe timeout would otherwise expire first, so the
    timeout inside ``/readyz`` has to fire and turn the stall into a 503
    without waiting out the hang, leaving the worker thread that ran the
    blocked ``stat`` to finish on its own in the background.
    """
    monkeypatch.setattr(app_module, "READINESS_TIMEOUT_SECONDS", 0.05)
    settings = ApiSettings(
        env="development",
        auth_mode="dev-headers",
        data_root=str(tmp_path / "data"),
        database_url="postgresql://unused",
        classification_vocabulary=[ClassificationValue(code="open", order=0, discoverable=True)],
    )
    app = create_app(settings=settings, stores=memory_stores())
    with TestClient(app) as client:
        root = app.state.runtime.generations.root
        original_exists = Path.exists

        def exists(path: Path) -> bool:
            if path == root:
                time.sleep(2.0)
            return original_exists(path)

        monkeypatch.setattr(Path, "exists", exists)
        started = time.monotonic()
        response = client.get("/readyz")
        elapsed = time.monotonic() - started
    assert elapsed < 1.0
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "30"
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["code"] == "DEPENDENCY_UNAVAILABLE"
    checks = body["context"]["checks"]
    assert checks.keys() == {"generations"}
    assert checks["generations"] == "did not answer within 0.05s"
