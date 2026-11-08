"""The directory verbs: their disk work after the commit, over a temporary lake."""

import os
import shutil
import stat
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
import pytest

from huron.core.metastore.store import MemoryStore
from huron.core.storage import DIRECTORY_MODE, FILE_MODE, MARKER_FILE, ORGANIZATION_MODE, LakePath
from tests.support.api import (
    COLLECTION_METADATA,
    Service,
    active_collection,
    seed_service,
    service,
)
from tests.support.disk import LAKE, Snapshot, memory_lake, snapshot

CATALOG = "/api/v1/catalogs/heliophysics"
NAMESPACES = f"{CATALOG}/namespaces"
RUN7 = ("helio", "heliophysics", "solar-wind", "run7")


def mode(path: Path) -> int:
    return stat.S_IMODE(os.lstat(path).st_mode)


async def send(
    api: Service, method: str, url: str, user: str, version: int | None = None, **body: Any
) -> httpx.Response:
    headers = await api.headers(user, **({} if version is None else {"If-Match": f'"{version}"'}))
    return await api.client.request(method, url, headers=headers, json=body or None)


async def draft(api: Service, name: str = "run7", namespace: str = "solar-wind") -> dict[str, Any]:
    created = await send(
        api,
        "POST",
        f"{NAMESPACES}/{namespace}/collections",
        "dave",
        name=name,
        metadata=COLLECTION_METADATA,
    )
    assert created.status_code == 201, created.text
    return dict(created.json())


async def activate(api: Service, created: dict[str, Any]) -> httpx.Response:
    return await send(api, "POST", f"/api/v1/collections/{created['id']}/activate", "dave", 1)


async def sidecar(api: Service, collection_id: str) -> bytes:
    response = await send(api, "GET", f"/api/v1/collections/{collection_id}/metadata.json", "erin")
    assert response.status_code == 200, response.text
    return response.content


async def helio_schema(api: Service) -> str:
    """A helio schema that extends the base schema; its id."""
    base = (await send(api, "GET", "/api/v1/platform/schemas", "erin")).json()["items"][0]
    entry = await send(
        api,
        "POST",
        "/api/v1/organizations/helio/schemas",
        "bob",
        name="helio",
        extends_id=base["id"],
        document={"type": "object", "properties": {"mission": {"type": "string"}}},
    )
    assert entry.status_code == 201, entry.text
    return str(entry.json()["id"])


def problem(response: httpx.Response) -> tuple[int, str]:
    return response.status_code, response.json()["code"]


async def test_creates_make_each_directory_with_its_mode(
    seeded_lake_api: Service, lake: Path
) -> None:
    organization, catalog = lake / "helio", lake / "helio" / "heliophysics"
    assert (mode(organization), mode(catalog)) == (ORGANIZATION_MODE, DIRECTORY_MODE)
    assert os.lstat(catalog).st_gid == os.lstat(organization).st_gid
    nested = await send(
        seeded_lake_api, "POST", NAMESPACES, "carol", parent="solar-wind", name="inner"
    )
    assert nested.status_code == 201, nested.text
    assert mode(catalog / "solar-wind") == mode(catalog / "solar-wind" / "inner") == DIRECTORY_MODE


async def test_activation_makes_the_directory_and_writes_metadata(
    seeded_lake_api: Service, lake: Path
) -> None:
    collection = await active_collection(seeded_lake_api)
    directory = lake.joinpath(*RUN7)
    assert mode(directory) == DIRECTORY_MODE
    assert mode(directory / "metadata.json") == FILE_MODE
    metadata = (directory / "metadata.json").read_bytes()
    assert metadata == await sidecar(seeded_lake_api, collection["id"])


async def test_deletes_remove_each_directory(seeded_lake_api: Service, lake: Path) -> None:
    api = seeded_lake_api
    collection = await active_collection(api)
    deleted = await send(api, "DELETE", f"/api/v1/collections/{collection['id']}", "dave", 2)
    assert deleted.status_code == 204, deleted.text
    assert not lake.joinpath(*RUN7).exists()
    for url, user in (
        (f"{NAMESPACES}/solar-wind", "carol"),
        (CATALOG, "bob"),
        ("/api/v1/organizations/helio", "alice"),
    ):
        assert (await send(api, "DELETE", url, user)).status_code == 204
    assert sorted(p.name for p in lake.iterdir()) == [MARKER_FILE, ".tus-uploads"]


async def test_a_draft_delete_and_a_dry_run_leave_the_lake_alone(
    seeded_lake_api: Service, lake: Path
) -> None:
    created = await draft(seeded_lake_api)
    url = f"/api/v1/collections/{created['id']}"
    directory = lake.joinpath(*RUN7)
    directory.mkdir()
    dry = await seeded_lake_api.client.delete(
        url,
        params={"dry_run": "true"},
        headers=await seeded_lake_api.headers("dave", **{"If-Match": '"1"'}),
    )
    assert dry.status_code == 204
    assert (await send(seeded_lake_api, "DELETE", url, "dave", 1)).status_code == 204
    assert directory.is_dir()


async def test_a_dry_run_delete_of_a_settled_collection_does_not_need_the_lake(
    seeded_lake_api: Service, lake: Path
) -> None:
    collection = await active_collection(seeded_lake_api)
    (lake / MARKER_FILE).unlink()
    dry = await seeded_lake_api.client.delete(
        f"/api/v1/collections/{collection['id']}",
        params={"dry_run": "true"},
        headers=await seeded_lake_api.headers("dave", **{"If-Match": '"2"'}),
    )
    assert dry.status_code == 204, dry.text
    assert lake.joinpath(*RUN7, "metadata.json").is_file()


async def test_an_existing_empty_directory_is_adopted(seeded_lake_api: Service, lake: Path) -> None:
    (lake / "helio" / "aurora").mkdir(mode=0o700)
    before = os.lstat(lake / "helio" / "aurora")
    created = await send(
        seeded_lake_api, "POST", "/api/v1/organizations/helio/catalogs", "bob", name="aurora"
    )
    assert created.status_code == 201, created.text
    after = os.lstat(lake / "helio" / "aurora")
    assert (after.st_ino, after.st_mode) == (before.st_ino, before.st_mode)


async def test_an_existing_entry_answers_storage_failed_and_keeps_the_rows(
    seeded_lake_api: Service, lake: Path
) -> None:
    (lake / "helio" / "aurora").mkdir()
    (lake / "helio" / "aurora" / "x.bin").write_bytes(b"x")
    created = await send(
        seeded_lake_api, "POST", "/api/v1/organizations/helio/catalogs", "bob", name="aurora"
    )
    assert problem(created) == (500, "STORAGE_FAILED")
    assert created.json()["detail"] == "helio/aurora exists and is not an empty directory"
    assert (await send(seeded_lake_api, "GET", "/api/v1/catalogs/aurora", "bob")).status_code == 200


async def test_a_metadata_file_the_lake_cannot_write_answers_storage_failed_and_keeps_the_rows(
    seeded_lake_api: Service, lake: Path
) -> None:
    api = seeded_lake_api
    collection = await active_collection(api)
    metadata = lake.joinpath(*RUN7, "metadata.json")
    metadata.unlink()
    metadata.mkdir()
    url = f"/api/v1/collections/{collection['id']}"
    published = await send(api, "PATCH", url, "dave", 2, metadata={"note": "published"})
    assert problem(published) == (500, "STORAGE_FAILED")
    assert (await send(api, "GET", url, "dave")).json()["version"] == 3


@pytest.mark.parametrize(
    ("method", "url", "user", "body", "read"),
    [
        ("POST", NAMESPACES, "carol", {"name": "aurora"}, f"{NAMESPACES}/aurora"),
        ("PATCH", CATALOG, "bob", {"share_group": "helio-readers"}, CATALOG),
    ],
    ids=["create", "set"],
)
async def test_an_unmarked_lake_answers_unavailable_and_keeps_the_rows(
    seeded_lake_api: Service,
    lake: Path,
    method: str,
    url: str,
    user: str,
    body: dict[str, Any],
    read: str,
) -> None:
    (lake / MARKER_FILE).unlink()
    response = await send(seeded_lake_api, method, url, user, **body)
    assert problem(response) == (503, "LAKE_UNAVAILABLE")
    assert (await send(seeded_lake_api, "GET", read, user)).status_code == 200


async def test_an_unmarked_lake_keeps_an_activation(seeded_lake_api: Service, lake: Path) -> None:
    created = await draft(seeded_lake_api)
    (lake / MARKER_FILE).unlink()
    assert problem(await activate(seeded_lake_api, created)) == (503, "LAKE_UNAVAILABLE")
    url = f"/api/v1/collections/{created['id']}"
    assert (await send(seeded_lake_api, "GET", url, "dave")).json()["state"] == "active"


async def test_a_directory_that_does_not_inherit_answers_storage_failed() -> None:
    storage = memory_lake()
    async with service(storage=storage, lake_path=LAKE) as api:
        await seed_service(api)
        storage.inherits = False
        created = await send(api, "POST", NAMESPACES, "carol", name="aurora")
        assert problem(created) == (500, "STORAGE_FAILED")
        assert "did not inherit the setgid bit" in created.json()["detail"]
        assert (await send(api, "GET", f"{NAMESPACES}/aurora", "carol")).status_code == 200
    assert storage.stat(LakePath.of("helio", "heliophysics", "aurora")) is None


async def test_a_path_from_a_corrupted_row_answers_name_invalid_and_keeps_the_rows() -> None:
    store = MemoryStore()
    async with service(store=store, storage=memory_lake(), lake_path=LAKE) as api:
        await seed_service(api)
        state = store.state
        helio = next(o for o in state.organizations.values() if o.name == "helio")
        state.organizations[helio.id] = replace(helio, name="..")
        response = await send(api, "PATCH", CATALOG, "bob", share_group="helio-readers")
        assert problem(response) == (422, "NAME_INVALID")
        state.organizations[helio.id] = helio
        assert (await send(api, "GET", CATALOG, "bob")).json()["share_group"] == "helio-readers"


async def test_metadata_follows_publish_override_and_assignment(
    seeded_lake_api: Service, lake: Path
) -> None:
    api = seeded_lake_api
    collection = await active_collection(api)
    url = f"/api/v1/collections/{collection['id']}"
    metadata = lake.joinpath(*RUN7, "metadata.json")
    published = await send(api, "PATCH", url, "dave", 2, metadata={"note": "published"})
    assert published.status_code == 200, published.text
    assert metadata.read_bytes() == await sidecar(api, collection["id"])
    assert b'"note":"published"' in metadata.read_bytes()
    override = {"type": "object", "properties": {"note": {"type": "string"}}}
    overridden = await send(api, "PATCH", url, "dave", 3, schema_override=override)
    assert overridden.status_code == 200, overridden.text
    assert metadata.read_bytes() == await sidecar(api, collection["id"])
    assert b'"schema_override":{' in metadata.read_bytes()
    unchanged = os.lstat(metadata).st_ino
    again = await send(api, "PATCH", url, "dave", 4, metadata={"note": "published"})
    assert again.status_code == 200
    assert os.lstat(metadata).st_ino == unchanged


async def test_an_assignment_rewrites_the_metadata_of_each_settled_collection(
    seeded_lake_api: Service, lake: Path
) -> None:
    api = seeded_lake_api
    aurora = await send(api, "POST", NAMESPACES, "carol", name="aurora", collections_allowed=True)
    assert aurora.status_code == 201, aurora.text
    first = await active_collection(api)
    created = await draft(api, "run1", "aurora")
    assert (await activate(api, created)).status_code == 200
    await draft(api, "pending", "aurora")
    schema_id = await helio_schema(api)
    assigned = await send(api, "PUT", f"{CATALOG}/schema", "carol", schema_id=schema_id)
    assert assigned.status_code == 200, assigned.text
    catalog = lake / "helio" / "heliophysics"
    for collection_id, directory in (
        (first["id"], catalog / "solar-wind" / "run7"),
        (created["id"], catalog / "aurora" / "run1"),
    ):
        written = (directory / "metadata.json").read_bytes()
        assert b'"name":"helio"' in written
        assert written == await sidecar(api, collection_id)
    assert not (catalog / "aurora" / "pending").exists()


async def test_a_draft_update_writes_no_metadata(seeded_lake_api: Service, lake: Path) -> None:
    created = await draft(seeded_lake_api)
    url = f"/api/v1/collections/{created['id']}"
    patched = await send(seeded_lake_api, "PATCH", url, "dave", 1, metadata={"note": "x"})
    assert patched.status_code == 200
    assert not lake.joinpath(*RUN7).exists()


async def test_a_directory_that_is_not_empty_is_kept_on_delete(
    seeded_lake_api: Service, lake: Path
) -> None:
    api = seeded_lake_api
    collection = await active_collection(api)
    directory = lake.joinpath(*RUN7)
    (directory / "stray.bin").write_bytes(b"stray")
    (directory / ".c.bin.1.huron-part").write_bytes(b"part")
    deleted = await send(api, "DELETE", f"/api/v1/collections/{collection['id']}", "dave", 2)
    assert deleted.status_code == 204, deleted.text
    assert sorted(p.name for p in directory.iterdir()) == ["stray.bin"]
    deleted = await send(api, "DELETE", f"{NAMESPACES}/solar-wind", "carol")
    assert deleted.status_code == 204
    assert directory.parent.is_dir()


async def test_the_verbs_without_a_lake_change_only_rows(seeded_api: Service) -> None:
    api = seeded_api
    created = await send(
        api, "POST", "/api/v1/organizations/helio/catalogs", "bob", name="aurora", share_group="g"
    )
    assert (created.status_code, created.json()["warnings"]) == (201, [])
    changed = await send(api, "PATCH", CATALOG, "bob", share_group="helio-readers")
    assert (changed.status_code, changed.json()["warnings"]) == (200, [])
    collection = await active_collection(api)
    url = f"/api/v1/collections/{collection['id']}"
    assert (await send(api, "PATCH", url, "dave", 2, metadata={"n": 1})).status_code == 200
    schema_id = await helio_schema(api)
    assigned = await send(api, "PUT", f"{CATALOG}/schema", "carol", schema_id=schema_id)
    assert assigned.status_code == 200
    assert (await send(api, "DELETE", url, "dave", 3)).status_code == 204
    for url, user in (
        (f"{NAMESPACES}/solar-wind", "carol"),
        (CATALOG, "bob"),
        ("/api/v1/catalogs/aurora", "bob"),
        ("/api/v1/organizations/helio", "alice"),
    ):
        assert (await send(api, "DELETE", url, user)).status_code == 204
    made = await send(api, "POST", "/api/v1/organizations", "alice", name="geo")
    assert made.status_code == 201


@pytest.fixture
def outside(lake: Path) -> Iterator[Path]:
    """A directory beside the lake with a ``run7`` directory; it must stay as it is."""
    directory = lake.parent / "outside"
    (directory / "run7").mkdir(parents=True)
    (directory / "keep.bin").write_bytes(b"keep")
    before: Snapshot = snapshot(directory)
    yield directory
    assert snapshot(directory) == before


def link(lake: Path, outside: Path, *names: str) -> None:
    """Replace the lake directory ``names`` by a symbolic link to ``outside``."""
    place = lake.joinpath(*names)
    if place.exists():
        shutil.rmtree(place)
    place.symlink_to(outside)


def refused_link(response: httpx.Response) -> str:
    assert problem(response) == (409, "SYMLINK_IN_LAKE"), response.text
    return str(response.json()["context"]["path"])


@pytest.mark.parametrize(
    ("names", "linked"),
    [
        (RUN7, "helio/heliophysics/solar-wind/run7"),
        (RUN7[:-1], "helio/heliophysics/solar-wind"),
    ],
    ids=["collection", "namespace"],
)
async def test_an_assignment_through_a_link_answers_409_and_keeps_the_rows(
    seeded_lake_api: Service, lake: Path, outside: Path, names: tuple[str, ...], linked: str
) -> None:
    api = seeded_lake_api
    await active_collection(api)
    link(lake, outside, *names)
    schema_id = await helio_schema(api)
    assigned = await send(api, "PUT", f"{CATALOG}/schema", "carol", schema_id=schema_id)
    assert refused_link(assigned) == linked
    assert (await send(api, "GET", CATALOG, "carol")).json()["schema"]["id"] == schema_id
    assert not any(outside.rglob("metadata.json"))


async def test_a_namespace_below_a_link_answers_409_and_keeps_the_row(
    seeded_lake_api: Service, lake: Path, outside: Path
) -> None:
    api = seeded_lake_api
    link(lake, outside, *RUN7[:-1])
    created = await send(api, "POST", NAMESPACES, "carol", parent="solar-wind", name="inner")
    assert refused_link(created) == "helio/heliophysics/solar-wind"
    assert (await send(api, "GET", f"{NAMESPACES}/solar-wind.inner", "carol")).status_code == 200


async def test_an_activation_at_a_link_answers_409_and_keeps_the_row(
    seeded_lake_api: Service, lake: Path, outside: Path
) -> None:
    api = seeded_lake_api
    created = await draft(api)
    link(lake, outside, *RUN7)
    assert refused_link(await activate(api, created)) == "helio/heliophysics/solar-wind/run7"
    url = f"/api/v1/collections/{created['id']}"
    assert (await send(api, "GET", url, "dave")).json()["state"] == "active"


async def test_a_link_inside_a_deleted_collection_keeps_its_directory(
    seeded_lake_api: Service, lake: Path, outside: Path
) -> None:
    api = seeded_lake_api
    collection = await active_collection(api)
    (lake.joinpath(*RUN7) / "elsewhere").symlink_to(outside)
    deleted = await send(api, "DELETE", f"/api/v1/collections/{collection['id']}", "dave", 2)
    assert deleted.status_code == 204, deleted.text
    assert [p.name for p in lake.joinpath(*RUN7).iterdir()] == ["elsewhere"]


async def test_the_first_failure_of_an_assignment_ends_the_request(
    seeded_lake_api: Service, lake: Path, outside: Path
) -> None:
    api = seeded_lake_api
    aurora = await send(api, "POST", NAMESPACES, "carol", name="aurora", collections_allowed=True)
    assert aurora.status_code == 201, aurora.text
    await active_collection(api)
    assert (await activate(api, await draft(api, "run1", "aurora"))).status_code == 200
    later = lake.joinpath(*RUN7, "metadata.json")
    before = later.read_bytes()
    link(lake, outside, "helio", "heliophysics", "aurora", "run1")
    schema_id = await helio_schema(api)
    assigned = await send(api, "PUT", f"{CATALOG}/schema", "carol", schema_id=schema_id)
    assert refused_link(assigned) == "helio/heliophysics/aurora/run1"
    assert (await send(api, "GET", CATALOG, "carol")).json()["schema"]["id"] == schema_id
    assert later.read_bytes() == before
