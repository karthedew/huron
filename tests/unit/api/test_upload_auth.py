"""The upload proxy's authorization subrequest: which tus requests may reach tusd."""

import uuid
from datetime import timedelta
from typing import Any

import httpx
import pytest

from tests.support.api import Service
from tests.support.clock import START
from tests.support.lake import CONTRIBUTOR
from tests.support.tusd import UploadTarget

AUTH = "/api/v1/uploads/auth"


async def authorize(
    api: Service, method: str, uri: str, user: str | None = None, token: str | None = None
) -> httpx.Response:
    headers = {"X-Original-Method": method, "X-Original-URI": uri}
    if user is not None:
        headers |= await api.headers(user)
    if token is not None:
        headers["Authorization"] = token
    return await api.client.get(AUTH, headers=headers)


ATTEMPT = "0190d5a4-0000-7000-8000-0000000000b1"


async def create(target: UploadTarget) -> str:
    """dave's creation of the attempt :data:`ATTEMPT`; the upload ID it names."""
    created = await target.tusd.create("dave", target.collection_id, "c.bin", 5, attempt_id=ATTEMPT)
    return str(created.json()["ChangeFileInfo"]["ID"])


async def attempt(api: Service) -> dict[str, Any]:
    stored = await api.runtime.attempts.get(CONTRIBUTOR, uuid.UUID(ATTEMPT))
    return {"state": str(stored.state), "active_at": stored.active_at}


@pytest.fixture
async def upload_id(target: UploadTarget) -> str:
    """An upload dave started: the current upload ID of his receiving attempt."""
    return await create(target)


@pytest.mark.parametrize("uri", ["/files/", "/files/?resume=1"])
@pytest.mark.parametrize("token", ["Bearer anything", "bearer x"])
async def test_a_creation_with_a_bearer_token_passes(
    seeded_lake_api: Service, uri: str, token: str
) -> None:
    allowed = await authorize(seeded_lake_api, "POST", uri, token=token)
    assert (allowed.status_code, allowed.content) == (204, b"")


@pytest.mark.parametrize("token", [None, "Basic a2FybDpwdw==", "Bearer "])
async def test_a_creation_without_a_bearer_token_is_unauthenticated(
    seeded_lake_api: Service, token: str | None
) -> None:
    refused = await authorize(seeded_lake_api, "POST", "/files/", token=token)
    assert (refused.status_code, refused.json()["code"]) == (401, "UNAUTHENTICATED")
    assert refused.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize("method", ["HEAD", "PATCH", "DELETE", "OPTIONS", "GET"])
@pytest.mark.parametrize("query", ["", "?offset=0"])
async def test_the_owner_may_use_the_current_upload_with_any_method(
    seeded_lake_api: Service, upload_id: str, method: str, query: str
) -> None:
    uri = f"/files/{upload_id}{query}"
    allowed = await authorize(seeded_lake_api, method, uri, user="dave")
    assert allowed.status_code == 204


@pytest.mark.parametrize("token", [None, "Bearer not-a-token"])
async def test_an_upload_request_without_a_valid_token_is_unauthenticated(
    seeded_lake_api: Service, upload_id: str, token: str | None
) -> None:
    refused = await authorize(seeded_lake_api, "PATCH", f"/files/{upload_id}", token=token)
    assert refused.status_code == 401
    assert refused.json()["code"] == ("UNAUTHENTICATED" if token is None else "TOKEN_INVALID")
    assert refused.headers["WWW-Authenticate"] == "Bearer"


async def test_another_users_or_an_unknown_upload_is_forbidden(
    seeded_lake_api: Service, upload_id: str
) -> None:
    for user, named in (("frank", upload_id), ("dave", str(uuid.uuid4()))):
        refused = await authorize(seeded_lake_api, "HEAD", f"/files/{named}", user=user)
        assert (refused.status_code, refused.json()["code"]) == (403, "FORBIDDEN")
        assert refused.json()["context"] == {"upload": named}
        assert "WWW-Authenticate" not in refused.headers


async def test_an_upload_id_that_is_no_longer_current_is_forbidden(
    seeded_lake_api: Service, target: UploadTarget
) -> None:
    first = await create(target)
    current = await create(target)
    for method in ("HEAD", "PATCH"):
        refused = await authorize(seeded_lake_api, method, f"/files/{first}", user="dave")
        assert (refused.status_code, refused.json()["context"]) == (403, {"upload": first})
    allowed = await authorize(seeded_lake_api, "HEAD", f"/files/{current}", user="dave")
    assert allowed.status_code == 204


async def test_an_upload_that_no_longer_receives_bytes_is_forbidden(
    seeded_lake_api: Service, target: UploadTarget, upload_id: str
) -> None:
    target.tusd.receive(upload_id, b"12345")
    assert (await target.tusd.finish("dave", upload_id, 5)).status_code == 200
    refused = await authorize(seeded_lake_api, "PATCH", f"/files/{upload_id}", user="dave")
    assert refused.status_code == 403
    assert (await attempt(seeded_lake_api))["state"] == "ready"


async def test_an_allowed_patch_records_activity_and_a_head_does_not(
    seeded_lake_api: Service, upload_id: str
) -> None:
    clock = seeded_lake_api.clock
    clock.advance(timedelta(hours=1))
    assert (
        await authorize(seeded_lake_api, "HEAD", f"/files/{upload_id}", user="dave")
    ).status_code == 204
    assert (await attempt(seeded_lake_api))["active_at"] == START
    clock.advance(timedelta(hours=1))
    assert (
        await authorize(seeded_lake_api, "PATCH", f"/files/{upload_id}", user="dave")
    ).status_code == 204
    assert (await attempt(seeded_lake_api))["active_at"] == START + timedelta(hours=2)


async def test_an_upload_past_its_lifetime_is_forbidden(
    seeded_lake_api: Service, upload_id: str
) -> None:
    seeded_lake_api.clock.advance(timedelta(days=7, microseconds=1))
    for method in ("HEAD", "PATCH"):
        refused = await authorize(seeded_lake_api, method, f"/files/{upload_id}", user="dave")
        assert refused.status_code == 403


@pytest.mark.parametrize(
    ("method", "uri"),
    [
        ("PATCH", "/files/not-a-uuid"),
        ("PATCH", "/files/0192B6A0-0000-7000-8000-0000000000AA"),
        ("PATCH", "/files/0192b6a0000070008000000000000aa0"),
        ("PATCH", "/files/0192b6a0-0000-7000-8000-0000000000aa/info"),
        ("GET", "/files/"),
        ("OPTIONS", "/files/"),
        ("POST", "/files"),
        ("POST", "/api/v1/organizations"),
        ("GET", ""),
    ],
)
async def test_a_path_that_names_no_upload_is_forbidden_before_the_token_is_read(
    seeded_lake_api: Service, method: str, uri: str
) -> None:
    refused = await authorize(seeded_lake_api, method, uri)
    assert (refused.status_code, refused.json()["code"]) == (403, "FORBIDDEN")


async def test_the_route_needs_a_lake(seeded_api: Service) -> None:
    refused = await authorize(seeded_api, "POST", "/files/", user="dave")
    assert (refused.status_code, refused.json()["code"]) == (404, "UPLOADS_DISABLED")
