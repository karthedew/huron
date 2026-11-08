"""Health, discovery, authentication, problems and the token exchange."""

import os
import stat
from pathlib import Path

import httpx
import pytest

from huron.applications.api.app import create_app
from huron.applications.api.openapi import document, main
from huron.core.storage import UPLOAD_DIR, UPLOADS, LakePath, LakeUnavailable, StorageError
from huron.core.storage.memory import MemoryStorage
from tests.support.api import INSTANCE_ID, Service, service
from tests.support.clock import START, frozen
from tests.support.disk import LAKE, StalledStorage, memory_lake


async def test_health_reports_the_instance(api: Service) -> None:
    body = (await api.client.get("/healthz")).json()
    assert body["status"] == "ok" and body["instance_id"] == str(INSTANCE_ID)
    assert body["organizations_managed"] is False
    assert (body["uploads_url"], body["service_user"]) == (None, None)
    assert body["upload_hook_timeout"] == 900
    ready = await api.client.get("/readyz")
    assert ready.status_code == 200 and ready.json()["checks"] == {
        "database": True,
        "signing_keys": True,
    }


async def test_health_reports_the_uploads_and_the_service_user(lake: Path) -> None:
    async with service(
        lake_path=lake,
        uploads_url="https://huron.example.org/files/",
        upload_hook_timeout="PT55M",
        service_uid=1000700000,
        service_group="huron-svc",
    ) as running:
        body = (await running.client.get("/healthz")).json()
    assert body["uploads_url"] == "https://huron.example.org/files/"
    assert body["service_user"] == {"uid": 1000700000, "gid": os.getgid(), "group": "huron-svc"}
    assert body["upload_hook_timeout"] == 3300


async def test_readiness_checks_a_temporary_lake(lake_api: Service, lake: Path) -> None:
    ready = await lake_api.client.get("/readyz")
    assert ready.status_code == 200
    assert ready.json()["checks"] == {"database": True, "signing_keys": True, "lake": True}
    assert stat.S_IMODE(os.lstat(lake / UPLOAD_DIR).st_mode) == 0o700
    assert sorted(p.name for p in lake.iterdir()) == [".huron", UPLOAD_DIR]
    assert list((lake / UPLOAD_DIR).iterdir()) == []


async def test_readiness_fails_when_the_lake_is_not_writable() -> None:
    clock = frozen()
    storage = memory_lake()
    storage.denied.add(UPLOADS)
    async with service(storage=storage, clock=clock, lake_path=LAKE) as running:
        ready = await running.client.get("/readyz")
    assert ready.status_code == 503
    assert ready.json() == {
        "status": "not ready",
        "checks": {"database": True, "signing_keys": True, "lake": False},
    }


async def test_readiness_fails_when_the_lake_probe_does_not_answer_in_time() -> None:
    clock = frozen()
    stalled = StalledStorage()
    try:
        async with service(
            storage=stalled, probe_timeout=0.01, clock=clock, lake_path=LAKE
        ) as running:
            ready = await running.client.get("/readyz")
    finally:
        stalled.release.set()
    assert ready.status_code == 503 and ready.json()["checks"]["lake"] is False


async def test_a_lake_path_that_is_not_a_directory_stops_startup(tmp_path: Path) -> None:
    with pytest.raises(LakeUnavailable, match="does not open as a directory") as raised:
        async with service(lake_path=tmp_path / "unmounted"):
            pass
    assert raised.value.message.startswith(f"the lake at {tmp_path / 'unmounted'} is not available")
    assert raised.value.context["lake_path"] == str(tmp_path / "unmounted")


async def test_a_lake_the_api_cannot_write_stops_startup() -> None:
    clock = frozen()
    storage = memory_lake()
    storage.denied.add(LakePath())
    with pytest.raises(LakeUnavailable, match="cannot write the lake"):
        async with service(storage=storage, clock=clock, lake_path=LAKE):
            pass


async def test_a_link_at_the_upload_directory_stops_startup_as_a_link(lake: Path) -> None:
    (lake.parent / "outside").mkdir()
    (lake / UPLOAD_DIR).symlink_to(lake.parent / "outside")
    with pytest.raises(StorageError) as raised:
        async with service(lake_path=lake):
            pass
    assert raised.value.code == "SYMLINK_IN_LAKE"


class BrokenStorage(MemoryStorage):
    """An in-memory lake whose directories cannot be made, with an error that is no refusal."""

    def make_directory(self, location: LakePath, mode: int) -> bool:
        raise RuntimeError("the disk driver crashed")


async def test_a_lake_that_fails_to_open_stops_startup_with_its_error() -> None:
    storage = BrokenStorage(LAKE)
    with pytest.raises(RuntimeError, match="the disk driver crashed"):
        async with service(storage=storage, lake_path=LAKE):
            pass


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
