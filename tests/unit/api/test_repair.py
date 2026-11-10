"""Repairs of catalogs and organizations: the routes, and the steps on a temporary lake."""

import errno
import os
import shutil
import stat
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from huron.applications.api.disk import LakeRepair
from huron.core.storage import (
    DIRECTORY_MODE,
    MARKER_FILE,
    ORGANIZATION_MODE,
    DirectoryWriter,
    LakePath,
    Marker,
    OrganizationPlace,
    Repairer,
    render_marker,
)
from tests.support.api import INSTANCE_ID, Service, active_collection, service
from tests.support.clock import frozen
from tests.support.disk import (
    SERVICE_GID,
    WRITE_CLEANUP_FAILURES,
    Snapshot,
    fail_file_io,
    fail_write_cleanup,
    lake_disk,
    memory_lake,
    plant_symlink,
    snapshot,
)
from tests.support.lake import CATALOG_ADMIN, World, make_world, seed

CATALOG = "helio/heliophysics"
REPAIR = "/api/v1/catalogs/heliophysics/repair"
NOTHING: dict[str, list[Any]] = {"changed": [], "warnings": [], "failed": []}
LINK_DETAIL = "{} is a symbolic link. The lake must not contain symbolic links. Remove it."


def mode(path: Path) -> int:
    return stat.S_IMODE(os.lstat(path).st_mode)


async def repair(
    api: Service, target: str = "heliophysics", recursive: bool = False, user: str = "carol"
) -> httpx.Response:
    body = {"target": target, "recursive": recursive}
    return await api.client.post(REPAIR, json=body, headers=await api.headers(user))


async def repaired(api: Service, target: str = "heliophysics", recursive: bool = False) -> Any:
    response = await repair(api, target, recursive)
    assert response.status_code == 200, response.text
    return response.json()


async def post_organization_repair(api: Service, user: str, name: str = "helio") -> httpx.Response:
    url = f"/api/v1/organizations/{name}/repair"
    return await api.client.post(url, headers=await api.headers(user))


def link_failure(path: str) -> dict[str, str]:
    return {"path": path, "reason": "symbolic_link", "detail": LINK_DETAIL.format(path)}


def outside(lake: Path) -> Path:
    """The directory beside the lake that every planted link points to."""
    target = lake.parent / "outside"
    (target / "inner").mkdir(parents=True, exist_ok=True)
    (target / "file").write_bytes(b"keep")
    return target


def plant_link(lake: Path, path: str) -> Snapshot:
    """Make ``path`` a link to :func:`outside`; the snapshot of ``outside`` before the repair."""
    target = outside(lake)
    lake.joinpath(path).symlink_to(target)
    return snapshot(target)


async def test_a_catalog_repair_makes_a_missing_directory_and_sets_wrong_bits(
    seeded_lake_api: Service, lake: Path
) -> None:
    shutil.rmtree(lake / CATALOG / "solar-wind")
    os.chmod(lake / CATALOG, 0o2770)
    result = await repaired(seeded_lake_api, "heliophysics.solar-wind")
    assert result == {**NOTHING, "changed": [CATALOG, f"{CATALOG}/solar-wind"]}
    assert mode(lake / CATALOG) == mode(lake / CATALOG / "solar-wind") == DIRECTORY_MODE
    assert await repaired(seeded_lake_api, "heliophysics.solar-wind") == NOTHING


async def test_a_missing_setgid_bit_is_mode_drift(seeded_lake_api: Service, lake: Path) -> None:
    os.chmod(lake / CATALOG / "solar-wind", 0o750)
    result = await repaired(seeded_lake_api, "heliophysics.solar-wind")
    path = f"{CATALOG}/solar-wind"
    detail = (
        f"{path} does not have the setgid bit. The storage administrator must run huron adm"
        " provision-catalogs."
    )
    assert result == {
        **NOTHING,
        "failed": [{"path": path, "reason": "mode_drift", "detail": detail}],
    }
    assert mode(lake / path) == 0o750


async def test_a_share_group_that_this_machine_does_not_know_is_a_warning(
    seeded_lake_api: Service,
) -> None:
    changed = await seeded_lake_api.client.patch(
        "/api/v1/catalogs/heliophysics",
        json={"share_group": "no-such-group-xyz"},
        headers=await seeded_lake_api.headers("bob"),
    )
    assert changed.status_code == 200, changed.text
    warning = {
        "code": "SHARE_GROUP_PENDING",
        "group": "no-such-group-xyz",
        "detail": "this machine does not know the group no-such-group-xyz",
    }
    assert await repaired(seeded_lake_api) == {**NOTHING, "warnings": [warning]}


async def test_a_recursive_repair_acts_only_on_planned_directories(
    seeded_lake_api: Service, lake: Path
) -> None:
    run7 = (await active_collection(seeded_lake_api))["path"]
    created = await active_collection(seeded_lake_api, "run8")
    run8 = created["path"]
    shutil.rmtree(lake / run8)
    loose = lake / run7 / "a"
    loose.mkdir()
    os.chmod(loose, 0o2770)
    (loose / "c.bin").write_bytes(b"c")
    os.chmod(loose / "c.bin", 0o600)
    stray = lake / CATALOG / "stray"
    stray.mkdir()
    os.chmod(stray, 0o700)
    result = await repaired(seeded_lake_api, recursive=True)
    assert result == {**NOTHING, "changed": [run8, f"{run8}/metadata.json"]}
    sidecar = await seeded_lake_api.client.get(
        f"/api/v1/collections/{created['id']}/metadata.json",
        headers=await seeded_lake_api.headers("erin"),
    )
    assert (lake / run8 / "metadata.json").read_bytes() == sidecar.content
    assert (mode(loose), mode(loose / "c.bin"), mode(stray)) == (0o2770, 0o600, 0o700)
    assert await repaired(seeded_lake_api, recursive=True) == NOTHING


async def test_a_recursive_repair_of_a_namespace_leaves_its_siblings_alone(
    seeded_lake_api: Service, lake: Path
) -> None:
    created = await seeded_lake_api.client.post(
        "/api/v1/catalogs/heliophysics/namespaces",
        json={"name": "solar"},
        headers=await seeded_lake_api.headers("carol"),
    )
    assert created.status_code == 201, created.text
    os.chmod(lake / CATALOG / "solar", 0o2770)
    os.chmod(lake / CATALOG / "solar-wind", 0o2770)
    result = await repaired(seeded_lake_api, "heliophysics.solar-wind", recursive=True)
    assert result == {**NOTHING, "changed": [f"{CATALOG}/solar-wind"]}
    assert mode(lake / CATALOG / "solar") == 0o2770


async def test_the_organization_route_sets_the_mode_and_makes_a_missing_directory(
    seeded_lake_api: Service, lake: Path
) -> None:
    os.chmod(lake / "helio", 0o2750)
    response = await post_organization_repair(seeded_lake_api, "bob")
    assert response.status_code == 200, response.text
    assert response.json() == {**NOTHING, "changed": ["helio"]}
    assert mode(lake / "helio") == ORGANIZATION_MODE
    alice = await seeded_lake_api.headers("alice")
    made = await seeded_lake_api.client.post(
        "/api/v1/organizations", json={"name": "geo"}, headers=alice
    )
    assert made.status_code == 201, made.text
    (lake / "geo").rmdir()
    response = await post_organization_repair(seeded_lake_api, "alice", "geo")
    assert response.json() == {**NOTHING, "changed": ["geo"]}
    assert mode(lake / "geo") == ORGANIZATION_MODE


@pytest.mark.parametrize(
    ("url", "allowed", "refused"),
    [(REPAIR, "carol", "dave"), ("/api/v1/organizations/helio/repair", "bob", "carol")],
    ids=["catalog", "organization"],
)
async def test_the_routes_check_the_privilege_first_and_need_a_lake(
    seeded_api: Service, url: str, allowed: str, refused: str
) -> None:
    body = {"target": "heliophysics"}
    forbidden = await seeded_api.client.post(
        url, json=body, headers=await seeded_api.headers(refused)
    )
    assert (forbidden.status_code, forbidden.json()["code"]) == (403, "FORBIDDEN")
    response = await seeded_api.client.post(
        url, json=body, headers=await seeded_api.headers(allowed)
    )
    assert (response.status_code, response.json()["code"]) == (503, "LAKE_UNAVAILABLE")
    assert response.json()["detail"] == "lake_path is not set. The API cannot repair directories."
    assert response.json().get("context", {}) == {}


async def test_a_target_of_another_catalog_is_refused(seeded_lake_api: Service) -> None:
    response = await repair(seeded_lake_api, "geophysics.x")
    assert (response.status_code, response.json()["code"]) == (422, "REQUEST_INVALID")


async def test_an_unsearchable_namespace_is_repaired_and_a_link_below_it_is_refused(
    seeded_lake_api: Service, lake: Path, temporary_mode: Callable[[Path, int], None]
) -> None:
    run7 = (await active_collection(seeded_lake_api))["path"]
    shutil.rmtree(lake / run7)
    before = plant_link(lake, run7)
    temporary_mode(lake / CATALOG / "solar-wind", 0o2000)
    result = await repaired(seeded_lake_api, recursive=True)
    assert result == {
        **NOTHING,
        "changed": [f"{CATALOG}/solar-wind"],
        "failed": [link_failure(run7)],
    }
    assert mode(lake / CATALOG / "solar-wind") == DIRECTORY_MODE
    assert (lake / run7).is_symlink()
    assert snapshot(outside(lake)) == before


async def test_a_planned_directory_that_is_a_link_is_refused(
    seeded_lake_api: Service, lake: Path
) -> None:
    (lake / CATALOG / "solar-wind").rmdir()
    before = plant_link(lake, f"{CATALOG}/solar-wind")
    result = await repaired(seeded_lake_api, "heliophysics.solar-wind")
    assert result == {**NOTHING, "failed": [link_failure(f"{CATALOG}/solar-wind")]}
    assert snapshot(outside(lake)) == before


async def test_a_link_above_two_planned_collections_fails_once_and_the_other_steps_run(
    seeded_lake_api: Service, lake: Path
) -> None:
    await active_collection(seeded_lake_api)
    await active_collection(seeded_lake_api, "run8")
    created = await seeded_lake_api.client.post(
        "/api/v1/catalogs/heliophysics/namespaces",
        json={"name": "solar"},
        headers=await seeded_lake_api.headers("carol"),
    )
    assert created.status_code == 201, created.text
    (lake / CATALOG / "solar").rmdir()
    shutil.rmtree(lake / CATALOG / "solar-wind")
    before = plant_link(lake, f"{CATALOG}/solar-wind")
    result = await repaired(seeded_lake_api, recursive=True)
    assert result == {
        **NOTHING,
        "changed": [f"{CATALOG}/solar"],
        "failed": [link_failure(f"{CATALOG}/solar-wind")],
    }
    assert snapshot(outside(lake)) == before


@pytest.mark.parametrize("name", ["metadata.json", "metadata.json.huron-part"])
async def test_a_link_at_metadata_json_or_its_part_file_is_refused_and_changes_nothing(
    seeded_lake_api: Service, lake: Path, name: str
) -> None:
    run7 = (await active_collection(seeded_lake_api))["path"]
    (lake / run7 / "metadata.json").unlink()
    before = plant_link(lake, f"{run7}/{name}")
    lake_before = snapshot(lake)
    result = await repaired(seeded_lake_api, "heliophysics.solar-wind.run7")
    assert result == {**NOTHING, "failed": [link_failure(f"{run7}/{name}")]}
    assert snapshot(lake) == lake_before
    assert snapshot(outside(lake)) == before


async def test_a_directory_at_metadata_json_fails_at_that_file(
    seeded_lake_api: Service, lake: Path
) -> None:
    run7 = (await active_collection(seeded_lake_api))["path"]
    (lake / run7 / "metadata.json").unlink()
    (lake / run7 / "metadata.json").mkdir()
    result = await repaired(seeded_lake_api, "heliophysics.solar-wind.run7")
    path = f"{run7}/metadata.json"
    failure = {"path": path, "reason": "storage_failed", "detail": f"{path}: Is a directory"}
    assert result == {**NOTHING, "failed": [failure]}
    assert (lake / path).is_dir()


@pytest.fixture
async def world() -> World:
    """The seeded lake of the domain tests."""
    seeded = await make_world()
    await seed(seeded)
    return seeded


async def test_a_directory_whose_row_is_gone_before_its_step_is_not_made(world: World) -> None:
    storage = memory_lake()
    storage.make_directory(LakePath.of("helio"), ORGANIZATION_MODE)
    disk = lake_disk(storage, frozen())
    repairs = world.lake.repairs
    plan = await repairs.plan(CATALOG_ADMIN, "heliophysics", "heliophysics", True)
    await world.lake.namespaces.delete(CATALOG_ADMIN, "heliophysics", "solar-wind")
    try:
        writer = DirectoryWriter(storage, SERVICE_GID)
        result = await LakeRepair(disk, Repairer(storage, writer)).repair(repairs, plan)
    finally:
        disk.close()
    assert result.changed == (CATALOG,)
    assert storage.stat(LakePath.of("helio", "heliophysics", "solar-wind")) is None


@pytest.fixture
async def rooted_api(lake: Path) -> AsyncIterator[Service]:
    """A service that declares helio with its root ``roots`` in the lake, its catalog
    ``heliophysics`` and the namespace ``solar-wind``.
    """
    helio = lake / "roots" / "helio"
    helio.mkdir(parents=True)
    os.chmod(helio, ORGANIZATION_MODE)
    marker = Marker(1, "http://huron.test", str(INSTANCE_ID), "helio")
    (helio / MARKER_FILE).write_bytes(render_marker(marker))
    declared = {
        "name": "helio",
        "groups": {"org_admin": ["helio-org-admins"]},
        "root": str(lake / "roots"),
    }
    async with service(lake_path=lake, organizations=[declared]) as api:
        created = await api.client.post(
            "/api/v1/organizations/helio/catalogs",
            json={"name": "heliophysics"},
            headers=await api.headers("bob"),
        )
        assert created.status_code == 201, created.text
        granted = await api.client.put(
            "/api/v1/catalogs/heliophysics/grants/catalog_admin",
            json={"ldap_groups": ["helio-catalog-admins"]},
            headers=await api.headers("bob"),
        )
        assert granted.status_code == 200, granted.text
        namespace = await api.client.post(
            "/api/v1/catalogs/heliophysics/namespaces",
            json={"name": "solar-wind"},
            headers=await api.headers("carol"),
        )
        assert namespace.status_code == 201, namespace.text
        yield api


@pytest.fixture(params=[("seeded_lake_api", ""), ("rooted_api", "roots")])
def part_error_api(request: pytest.FixtureRequest) -> tuple[Service, str]:
    """A service with either the default or a separately rooted organization."""
    name, base = request.param
    return request.getfixturevalue(name), base


@pytest.fixture
async def metadata_error_api(
    part_error_api: tuple[Service, str], lake: Path
) -> tuple[Service, Path, str, bytes]:
    """An active collection with old disk metadata and its current, expected bytes."""
    api, base = part_error_api
    if base:
        granted = await api.client.put(
            "/api/v1/catalogs/heliophysics/grants/contributor",
            json={"ldap_groups": ["helio-contributors"]},
            headers=await api.headers("carol"),
        )
        assert granted.status_code == 200, granted.text
        configured = await api.client.patch(
            "/api/v1/catalogs/heliophysics/namespaces/solar-wind",
            json={"collections_allowed": True},
            headers=await api.headers("carol"),
        )
        assert configured.status_code == 200, configured.text
    run7 = (await active_collection(api))["path"]
    metadata = lake / base / run7 / "metadata.json"
    expected = metadata.read_bytes()
    metadata.write_bytes(b"old")
    return api, metadata, run7, expected


@pytest.mark.parametrize("number", [errno.EIO, errno.EACCES])
@pytest.mark.parametrize(
    ("operation", "name"), [("read", "metadata.json"), ("stat", "metadata.json.huron-part")]
)
async def test_an_error_on_metadata_json_or_its_part_file_reports_that_file_and_keeps_it(
    metadata_error_api: tuple[Service, Path, str, bytes],
    lake: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    name: str,
    number: int,
) -> None:
    api, metadata, run7, expected = metadata_error_api
    before = snapshot(lake)
    fail_file_io(monkeypatch, operation, name, number)
    path = f"{run7}/{name}"
    detail = (
        f"permission denied on {path}" if number == errno.EACCES else f"{path}: Input/output error"
    )
    assert await repaired(api, "heliophysics.solar-wind.run7") == {
        **NOTHING,
        "failed": [{"path": path, "reason": "storage_failed", "detail": detail}],
    }
    assert snapshot(lake) == before
    assert await repaired(api, "heliophysics.solar-wind.run7") == {
        **NOTHING,
        "changed": [f"{run7}/metadata.json"],
    }
    assert metadata.read_bytes() == expected


async def test_a_metadata_json_of_mode_000_is_reported_at_that_file_and_kept(
    metadata_error_api: tuple[Service, Path, str, bytes],
    lake: Path,
    temporary_mode: Callable[[Path, int], None],
) -> None:
    api, metadata, run7, _ = metadata_error_api
    before = snapshot(lake)
    temporary_mode(metadata, 0o000)
    path = f"{run7}/metadata.json"
    failure = {"path": path, "reason": "storage_failed", "detail": f"permission denied on {path}"}
    assert await repaired(api, "heliophysics.solar-wind.run7") == {**NOTHING, "failed": [failure]}
    metadata.chmod(0o644)
    assert snapshot(lake) == before


@pytest.mark.parametrize("operation,cleanup", WRITE_CLEANUP_FAILURES)
@pytest.mark.parametrize("number", [errno.ENOSPC, errno.EACCES, errno.ENOENT])
async def test_repair_reports_the_primary_failure_when_cleanup_also_fails(
    metadata_error_api: tuple[Service, Path, str, bytes],
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    cleanup: tuple[str, ...],
    number: int,
) -> None:
    api, metadata, run7, expected = metadata_error_api
    old_inode = metadata.stat().st_ino
    with monkeypatch.context() as patch:
        primary, *secondary = fail_write_cleanup(
            patch, "metadata.json.huron-part", operation, cleanup, number
        )
        result = await repaired(api, "heliophysics.solar-wind.run7")
    named = (
        "metadata.json"
        if operation == "rename" or (operation == "open" and number == errno.EACCES)
        else "metadata.json.huron-part"
    )
    path = f"{run7}/{named}"
    if number == errno.EACCES:
        detail = f"permission denied on {path}"
    elif number == errno.ENOENT:
        detail = f"{path} does not exist"
    else:
        detail = f"{path}: {os.strerror(number)}"
    assert result == {
        **NOTHING,
        "failed": [{"path": path, "reason": "storage_failed", "detail": detail}],
    }
    assert primary.__traceback__ is not None
    assert all(fault.__traceback__ is not None for fault in secondary)
    assert (metadata.read_bytes(), metadata.stat().st_ino) == (b"old", old_inode)
    assert await repaired(api, "heliophysics.solar-wind.run7") == {
        **NOTHING,
        "changed": [f"{run7}/metadata.json"],
    }
    assert metadata.read_bytes() == expected
    assert not metadata.with_name("metadata.json.huron-part").exists()
    assert await repaired(api, "heliophysics.solar-wind.run7") == NOTHING


@pytest.mark.parametrize("link", ["helio", f"helio/{MARKER_FILE}"], ids=["directory", "marker"])
async def test_a_link_at_a_declared_organizations_directory_or_marker_fails_each_step(
    rooted_api: Service, lake: Path, link: str
) -> None:
    roots = lake / "roots"
    if link == "helio":
        (roots / "helio").rename(roots / "helio.moved")
    else:
        (roots / link).unlink()
    (roots / link).symlink_to(outside(lake))
    before = snapshot(outside(lake))
    response = await repair(rooted_api, recursive=True)
    assert response.status_code == 200, response.text
    assert response.json() == {**NOTHING, "failed": [link_failure(link)]}
    organization = await post_organization_repair(rooted_api, "bob")
    assert organization.status_code == 200, organization.text
    assert organization.json() == {**NOTHING, "failed": [link_failure(link)]}
    assert snapshot(outside(lake)) == before


async def test_a_link_at_a_declared_organizations_base_keeps_its_lake_path(
    world: World,
) -> None:
    storage = memory_lake()
    plant_symlink(storage, LakePath.of("roots"))
    places = {"helio": OrganizationPlace("helio", LakePath.of("roots"), own_marker=True)}
    disk = lake_disk(storage, frozen(), places=places)
    plan = await world.lake.repairs.plan(CATALOG_ADMIN, "heliophysics", "heliophysics", True)
    try:
        writer = DirectoryWriter(storage, SERVICE_GID)
        result = await LakeRepair(disk, Repairer(storage, writer)).repair(world.lake.repairs, plan)
    finally:
        disk.close()
    assert [(f.path, f.reason, f.detail) for f in result.failed] == [
        ("roots", "symbolic_link", LINK_DETAIL.format("roots"))
    ]
    assert result.changed == ()
