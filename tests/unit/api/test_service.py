"""Health, discovery, authentication, problems and the token exchange."""

import httpx
import pytest

from huron.applications.api.app import create_app
from huron.applications.api.openapi import document, main
from tests.support.api import INSTANCE_ID, Service, service
from tests.support.clock import START


async def test_health_reports_the_instance(api: Service) -> None:
    body = (await api.client.get("/healthz")).json()
    assert body["status"] == "ok" and body["instance_id"] == str(INSTANCE_ID)
    ready = await api.client.get("/readyz")
    assert ready.status_code == 200 and ready.json()["checks"] == {
        "database": True,
        "signing_keys": True,
    }


async def test_discovery_and_jwks(api: Service) -> None:
    discovery = (await api.client.get("/.well-known/openid-configuration")).json()
    assert discovery["issuer"] == "https://huron.test"
    keys = (await api.client.get("/jwks.json")).json()["keys"]
    assert keys[0]["alg"] == "ES256"


async def test_requests_without_a_token_are_unauthenticated(api: Service) -> None:
    response = await api.client.get("/api/v1/organizations")
    assert response.status_code == 401
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "UNAUTHENTICATED"
    bad = await api.client.get("/api/v1/organizations", headers={"Authorization": "Bearer x"})
    assert bad.json()["code"] == "TOKEN_INVALID"
    basic = await api.client.get("/api/v1/organizations", headers={"Authorization": "Basic x"})
    assert basic.status_code == 401


async def test_exchange_and_whoami(api: Service) -> None:
    company = api.issuer.sign("dave", now=START.timestamp())
    exchanged = await api.client.post("/api/v1/auth/exchange", json={"company_token": company})
    assert exchanged.status_code == 200, exchanged.text
    body = exchanged.json()
    assert body["groups"] == ["helio-contributors"] and body["subject"] == "dave"
    me = await api.client.get(
        "/api/v1/auth/whoami", headers={"Authorization": f"Bearer {body['huron_token']}"}
    )
    assert me.json()["roles"] == []
    admin = await api.client.get("/api/v1/auth/whoami", headers=await api.headers("alice"))
    assert admin.json()["roles"] == [
        {"scope": "platform", "scope_id": None, "role": "platform_admin"}
    ]
    refused = await api.client.post("/api/v1/auth/exchange", json={"company_token": "nope"})
    assert refused.status_code == 401


async def test_validation_errors_are_problems(api: Service) -> None:
    response = await api.client.post(
        "/api/v1/organizations", json={"name": ""}, headers=await api.headers("alice")
    )
    assert response.status_code == 422
    assert response.json()["code"] == "REQUEST_INVALID"
    assert response.json()["context"]["problems"][0]["path"] == "/body/name"
    missing = await api.client.get("/nowhere")
    assert missing.status_code == 404 and missing.json()["code"] == "NOT_FOUND"
    method = await api.client.put("/healthz")
    assert method.status_code == 405 and method.json()["code"] == "HTTP"


async def test_unexpected_errors_become_internal_problems() -> None:
    async with service() as running:
        app = create_app(runtime=running.runtime)

        @app.get("/boom")
        async def boom() -> None:
            raise RuntimeError("boom")

        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            response = await client.get("/boom")
        assert response.status_code == 500
        assert response.json()["code"] == "INTERNAL"
        assert "request_id" in response.json()["context"]


async def test_readiness_fails_without_signing_keys(api: Service) -> None:
    async with api.runtime.store.transaction() as tx:
        for key in await tx.keys.list_keys():
            await tx.keys.retire_key(key.kid, START)
    await api.runtime.ring(refresh=True)
    response = await api.client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["checks"]["signing_keys"] is False


def test_openapi_document_lists_the_routes(tmp_path) -> None:  # type: ignore[no-untyped-def]
    paths = document()["paths"]
    assert "/api/v1/collections/{collection_id}/commits" in paths
    target = tmp_path / "openapi.json"
    assert main([str(target)]) == 0
    assert target.read_text().startswith("{")


def test_openapi_main_writes_to_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert '"openapi"' in capsys.readouterr().out
