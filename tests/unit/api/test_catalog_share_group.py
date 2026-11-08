"""A catalog's share group through the routes, and the attempt to set it on the lake."""

import grp
import os
from pathlib import Path

import pytest

from huron.core.storage import DIRECTORY_MODE, MARKER_FILE, ORGANIZATION_MODE, LakePath
from huron.core.storage.memory import MemoryStorage
from tests.support.api import Service, seed_service, service
from tests.support.clock import frozen
from tests.support.disk import LAKE, memory_lake

CATALOG = "/api/v1/catalogs/heliophysics"


@pytest.fixture
def own_group(lake: Path) -> str:
    """The group the temporary lake's directories get, which the test process may give."""
    return grp.getgrgid(os.lstat(lake).st_gid).gr_name


@pytest.fixture
def catalog_dir(lake: Path) -> Path:
    """The directory of the seeded heliophysics catalog in the temporary lake."""
    directory = lake / "helio" / "heliophysics"
    directory.mkdir(parents=True)
    return directory


async def create(api: Service, body: dict[str, object]) -> dict[str, object]:
    response = await api.client.post(
        "/api/v1/organizations/helio/catalogs", json=body, headers=await api.headers("bob")
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


async def patch(api: Service, share_group: object, user: str = "bob") -> dict[str, object]:
    response = await api.client.patch(
        CATALOG, json={"share_group": share_group}, headers=await api.headers(user)
    )
    assert response.status_code == 200, response.text
    return dict(response.json())


async def test_a_catalog_is_created_with_a_share_group(seeded_api: Service) -> None:
    created = await create(seeded_api, {"name": "aurora", "share_group": "helio-readers"})
    assert (created["share_group"], created["warnings"]) == ("helio-readers", [])
    plain = await create(seeded_api, {"name": "corona"})
    assert (plain["share_group"], plain["warnings"]) == (None, [])
    read = await seeded_api.client.get(
        "/api/v1/catalogs/aurora", headers=await seeded_api.headers("bob")
    )
    assert read.json()["share_group"] == "helio-readers" and "warnings" not in read.json()


async def test_the_share_group_is_set_and_cleared(seeded_api: Service) -> None:
    changed = await patch(seeded_api, "helio-readers")
    assert (changed["share_group"], changed["version"], changed["warnings"]) == (
        "helio-readers",
        2,
        [],
    )
    cleared = await patch(seeded_api, None)
    assert (cleared["share_group"], cleared["version"], cleared["warnings"]) == (None, 3, [])
    listed = await seeded_api.client.get(
        "/api/v1/catalogs", headers=await seeded_api.headers("erin")
    )
    assert listed.json()["items"][0]["share_group"] is None


@pytest.mark.parametrize(
    ("path", "body", "user", "status", "code"),
    [
        (CATALOG, {"share_group": "1bad"}, "bob", 422, "REQUEST_INVALID"),
        (CATALOG, {}, "bob", 422, "REQUEST_INVALID"),
        (CATALOG, {"share_group": "helio-readers"}, "dave", 403, "FORBIDDEN"),
        ("/api/v1/catalogs/nowhere", {"share_group": None}, "bob", 404, "NOT_FOUND"),
    ],
)
async def test_a_share_group_change_is_refused(
    seeded_api: Service, path: str, body: dict[str, object], user: str, status: int, code: str
) -> None:
    headers = await seeded_api.headers(user)
    response = await seeded_api.client.patch(path, json=body, headers=headers)
    assert (response.status_code, response.json()["code"]) == (status, code)


async def test_a_group_the_directory_has_gives_no_warning(
    seeded_lake_api: Service, catalog_dir: Path, own_group: str
) -> None:
    changed = await patch(seeded_lake_api, own_group)
    assert (changed["share_group"], changed["warnings"]) == (own_group, [])


async def test_a_group_the_lake_cannot_set_is_pending(
    seeded_lake_api: Service, catalog_dir: Path
) -> None:
    changed = await patch(seeded_lake_api, "no-such-group-xyz")
    assert changed["warnings"] == [
        {
            "code": "SHARE_GROUP_PENDING",
            "group": "no-such-group-xyz",
            "detail": "this machine does not know the group no-such-group-xyz",
        }
    ]


async def test_a_new_catalog_without_its_directory_is_pending(
    seeded_lake_api: Service, lake: Path, own_group: str
) -> None:
    created = await create(seeded_lake_api, {"name": "aurora", "share_group": own_group})
    assert created["warnings"] == [
        {
            "code": "SHARE_GROUP_PENDING",
            "group": own_group,
            "detail": "helio/aurora does not exist",
        }
    ]


async def test_a_new_catalog_without_a_share_group_does_not_touch_the_lake(
    seeded_lake_api: Service, lake: Path
) -> None:
    (lake / MARKER_FILE).unlink()
    created = await create(seeded_lake_api, {"name": "aurora"})
    assert created["warnings"] == []


async def test_a_cleared_share_group_gives_the_directory_the_service_group() -> None:
    clock = frozen()
    storage = memory_lake()
    storage.groups["helio-readers"] = 2001
    storage.member_of |= {2001, os.getgid()}
    directory = LakePath.of("helio", "heliophysics")
    async with service(storage=storage, clock=clock, lake_path=LAKE) as api:
        await seed_service(api)
        storage.make_directory(directory.parent, ORGANIZATION_MODE)
        storage.make_directory(directory, DIRECTORY_MODE)
        changed = await patch(api, "helio-readers")
        assert (changed["warnings"], gid(storage, directory)) == ([], 2001)
        cleared = await patch(api, None)
    assert (cleared["share_group"], cleared["warnings"]) == (None, [])
    assert gid(storage, directory) == os.getgid()


async def test_a_service_group_the_lake_cannot_set_is_pending(
    seeded_lake_api: Service, lake: Path
) -> None:
    cleared = await patch(seeded_lake_api, None)
    assert cleared["warnings"] == [
        {
            "code": "SHARE_GROUP_PENDING",
            "group": str(os.getgid()),
            "detail": "helio/heliophysics does not exist",
        }
    ]


@pytest.mark.parametrize("share_group", ["helio-readers", None])
async def test_an_unmarked_lake_keeps_the_rows_and_answers_unavailable(
    seeded_lake_api: Service, lake: Path, share_group: str | None
) -> None:
    await patch(seeded_lake_api, "geo-readers")
    (lake / MARKER_FILE).unlink()
    headers = await seeded_lake_api.headers("bob")
    response = await seeded_lake_api.client.patch(
        CATALOG, json={"share_group": share_group}, headers=headers
    )
    assert (response.status_code, response.json()["code"]) == (503, "LAKE_UNAVAILABLE")
    read = await seeded_lake_api.client.get(CATALOG, headers=headers)
    assert read.json()["share_group"] == share_group


def gid(storage: MemoryStorage, location: LakePath) -> int:
    found = storage.stat(location)
    assert found is not None
    return found.gid
