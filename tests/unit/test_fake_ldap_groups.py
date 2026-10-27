"""Group-directory responses, fault controls and cross-client lifecycle."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import httpx
import pytest
from starlette.testclient import TestClient

from tests.fakes.ldap_groups import FakeGroupDirectory, app_from_environment

if TYPE_CHECKING:
    from pathlib import Path

    from tests.fakes.ldap_groups import GroupsFailure, Identities

pytestmark = pytest.mark.unit


async def test_membership_is_sorted_and_headers_have_no_authority(
    identities: Identities,
    fake_groups: FakeGroupDirectory,
    fake_groups_transport: httpx.ASGITransport,
) -> None:
    """Every fixture user gets sorted directory membership regardless of headers."""
    async with httpx.AsyncClient(
        transport=fake_groups_transport, base_url="https://groups.test"
    ) as client:
        for user in identities.users.values():
            response = await client.get(
                f"/users/{user.username}/groups",
                headers={"Authorization": "Bearer irrelevant", "X-User": "other"},
            )
            assert response.status_code == 200
            assert response.json() == {"groups": sorted(user.groups)}
    assert fake_groups.requests == tuple(identities.users)


async def test_unknown_user_and_route_surface(
    fake_groups: FakeGroupDirectory, fake_groups_transport: httpx.ASGITransport
) -> None:
    """Unknown people return the directory 404 and no HTTP control routes exist."""
    async with httpx.AsyncClient(
        transport=fake_groups_transport, base_url="https://groups.test"
    ) as client:
        response = await client.get("/users/absent/groups")
        assert response.status_code == 404
        assert response.json() == {"detail": "unknown user"}
        assert (await client.post("/users/karl/groups")).status_code == 405
        assert (await client.get("/inject")).status_code == 404
    assert fake_groups.requests == ("absent",)


def test_encoded_username_and_empty_membership(identities: Identities) -> None:
    """URL decoding reaches a UPN-named user whose empty groups remain a list."""
    user = replace(identities.user("karl"), username="karl@corp", groups=())
    directory = FakeGroupDirectory(
        identities.with_user(replace(user, id="00000000-0000-4000-8000-000000000000"))
    )
    with TestClient(directory.app) as client:
        response = client.get("/users/karl%40corp/groups")
    assert response.json() == {"groups": []}
    assert directory.requests == ("karl@corp",)


@pytest.mark.parametrize(
    "failure",
    [
        404,
        500,
        401,
        "timeout",
        "unreachable",
        "malformed",
        b"not json",
        b"\xff",
        b'{"groups":[null]}',
        b"",
    ],
)
@pytest.mark.parametrize("username", [None, "karl"])
async def test_faults_persist_until_cleared(
    fake_groups: FakeGroupDirectory,
    fake_groups_transport: httpx.ASGITransport,
    failure: GroupsFailure,
    username: str | None,
) -> None:
    """Global and per-user faults survive repeated requests and clear explicitly."""
    fake_groups.inject(failure, username=username)
    async with httpx.AsyncClient(
        transport=fake_groups_transport, base_url="https://groups.test"
    ) as client:
        for _ in range(2):
            if failure in ("timeout", "unreachable"):
                exception = httpx.ReadTimeout if failure == "timeout" else httpx.ConnectError
                with pytest.raises(exception, match="injected"):
                    await client.get("/users/karl/groups")
            else:
                response = await client.get("/users/karl/groups")
                assert response.status_code == (failure if isinstance(failure, int) else 200)
                if isinstance(failure, bytes):
                    assert response.content == failure
                    assert response.headers["content-type"] == "application/json"
                else:
                    assert response.json() == (
                        {"error": "injected"}
                        if isinstance(failure, int)
                        else {"groups": "not-a-list"}
                    )
        if username is not None:
            assert (await client.get("/users/sam/groups")).status_code == 200
        fake_groups.inject(None, username=username)
        fake_groups.inject(None, username=username)
        assert (await client.get("/users/karl/groups")).status_code == 200
    assert fake_groups.requests[:2] == ("karl", "karl")


async def test_per_user_precedence_and_independent_clearing(
    fake_groups: FakeGroupDirectory, fake_groups_transport: httpx.ASGITransport
) -> None:
    """Clearing one scope exposes its fallback without erasing other controls."""
    fake_groups.inject(500)
    fake_groups.inject(401, username="karl")
    fake_groups.inject("malformed", username="absent")
    async with httpx.AsyncClient(
        transport=fake_groups_transport, base_url="https://groups.test"
    ) as client:
        assert (await client.get("/users/karl/groups")).status_code == 401
        assert (await client.get("/users/sam/groups")).status_code == 500
        assert (await client.get("/users/absent/groups")).json() == {"groups": "not-a-list"}
        fake_groups.inject(None, username="karl")
        assert (await client.get("/users/karl/groups")).status_code == 500
        fake_groups.inject(404, username="karl")
        fake_groups.inject(None)
        assert (await client.get("/users/karl/groups")).status_code == 404
        assert (await client.get("/users/sam/groups")).status_code == 200
        fake_groups.inject(None, username="absent")
        assert (await client.get("/users/absent/groups")).json() == {"detail": "unknown user"}
    assert fake_groups.requests == ("karl", "sam", "absent", "karl", "karl", "sam", "absent")


async def test_sync_and_async_clients_share_one_directory(
    fake_groups: FakeGroupDirectory, fake_groups_transport: httpx.ASGITransport
) -> None:
    """A TestClient worker thread and the async transport observe the same controls."""
    app = fake_groups.app
    with TestClient(app) as sync:
        async with httpx.AsyncClient(
            transport=fake_groups_transport, base_url="https://groups.test"
        ) as client:
            assert sync.get("/users/karl/groups").status_code == 200
            snapshot = fake_groups.requests
            fake_groups.inject(401, username="sam")
            assert (await client.get("/users/sam/groups")).status_code == 401
            assert sync.get("/users/sam/groups").status_code == 401
            fake_groups.inject(None, username="sam")
            assert (await client.get("/users/sam/groups")).status_code == 200
    assert fake_groups.app is app
    assert snapshot == ("karl",)
    assert fake_groups.requests == ("karl", "sam", "sam", "sam")
    with TestClient(app) as reopened:
        assert reopened.get("/users/rita/groups").status_code == 200


@pytest.mark.parametrize("configured", [False, True])
def test_environment_selects_identity_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, configured: bool
) -> None:
    """The standalone factory honors an explicit fixture and otherwise uses its default."""
    monkeypatch.delenv("FAKE_IDENTITIES", raising=False)
    if configured:
        path = tmp_path / "empty.yaml"
        path.write_text("version: 1\norganization: Example\nusers: []\n")
        monkeypatch.setenv("FAKE_IDENTITIES", str(path))
    with TestClient(app_from_environment()) as client:
        assert client.get("/users/karl/groups").status_code == (404 if configured else 200)
