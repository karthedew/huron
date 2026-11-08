"""The CLI against the real in-process service in managed mode, not a stand-in.

The service's settings declare helio and geo under their own roots, so the organization views,
the 409s and the bootstrap reconcile are the service's own; the share is in memory.
"""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from huron.core.lake.organizations.models import Organization
from huron.core.storage import (
    MARKER_FILE,
    DirectoryKind,
    EffectiveGroups,
    Marker,
    plan,
    read_marker,
    render_marker,
)
from huron.core.storage.memory import MemoryStorage
from huron.pkg.identifiers import new_id
from tests.support.api import INSTANCE_ID
from tests.support.cli import API, Cli
from tests.unit.cli.conftest import PREFIX, make_collection, make_directory

HELIO_ROOT = Path("/data1/huron")
GEO_ROOT = Path("/data2/huron")
HELIO = HELIO_ROOT / "helio"
ORGANIZATIONS = [
    {
        "name": "helio",
        "display_name": "Heliophysics",
        "groups": {"org_admin": ["helio-org-admins"], "reader": ["helio-readers"]},
        "root": str(HELIO_ROOT),
        "export": "nfs1:/export/data1",
    },
    {
        "name": "geo",
        "display_name": "Geoscience",
        "groups": {"org_admin": ["geo-org-admins"]},
        "root": str(GEO_ROOT),
    },
]


@pytest.fixture
def roots() -> MemoryStorage:
    """Both roots exist and belong to alice, the storage admin; the mount prefix is unmarked."""
    storage = MemoryStorage(PREFIX, user="alice")
    for root in (HELIO_ROOT, GEO_ROOT):
        storage.add_root(root, owner="alice")
    return storage


@pytest.fixture
def managed(tmp_path: Path, roots: MemoryStorage) -> Iterator[Cli]:
    running = Cli(tmp_path, lambda config: roots, PREFIX, organizations=ORGANIZATIONS)
    running.login_as("alice")
    yield running
    running.close()


def test_the_declared_organizations_are_provisioned_and_used(
    managed: Cli, roots: MemoryStorage
) -> None:
    listed = json.loads(managed.ok("-o", "json", "get", "orgs").stdout)
    assert {(o["name"], o["declared"], o["path"]) for o in listed} == {
        ("helio", True, "/data1/huron/helio"),
        ("geo", True, "/data2/huron/geo"),
    }
    assert managed.run("adm", "verify-mounts").exit_code == 1

    managed.ok("adm", "provision-orgs")
    managed.ok("adm", "verify-mounts")
    for root, name in ((HELIO_ROOT, "helio"), (GEO_ROOT, "geo")):
        assert roots.exists(root / name / MARKER_FILE)
        marker = read_marker(roots, root / name)
        assert (marker.instance_id, marker.organization) == (str(INSTANCE_ID), name)

    managed.login_as("bob")
    managed.ok("create", "catalog", "heliophysics", "--org", "helio")
    described = json.loads(managed.ok("-o", "json", "describe", "catalog", "heliophysics").stdout)
    assert described["organization"] == "helio"


def test_the_service_refuses_changes_to_declared_organizations(managed: Cli) -> None:
    created = managed.run("create", "org", "astro")
    assert created.exit_code == 6 and "huron adm provision-orgs" in created.stderr
    deleted = managed.run("delete", "org", "helio")
    assert (
        deleted.exit_code == 6
        and "First delete its entry from the service configuration" in deleted.stderr
    )
    granted = managed.run("adm", "grant", "org_admin", "other-admins", "--org", "helio")
    assert granted.exit_code == 6 and "groups.org_admin" in granted.stderr
    reader = managed.run("adm", "revoke", "reader", "helio-readers", "--org", "helio")
    assert reader.exit_code == 6 and "Edit `groups.reader` there" in reader.stderr


def add_undeclared(cli: Cli, name: str) -> None:
    """An organization the configuration does not declare, as one left from unmanaged mode."""

    async def insert() -> None:
        async with cli.runtime.store.transaction() as tx:
            await tx.organizations.insert(
                Organization(new_id(), name, name, "", 1, cli.clock.now(), "alice")
            )

    cli.loop.call(insert())


def test_an_undeclared_organization_is_reported_without_failing_the_others(
    managed: Cli, roots: MemoryStorage
) -> None:
    add_undeclared(managed, "astro")
    managed.ok("adm", "provision-orgs")
    listing = managed.ok("get", "orgs").stdout
    assert f"{PREFIX}/astro (undeclared)" in listing

    rows = json.loads(managed.ok("-o", "json", "adm", "verify-mounts").stdout)
    assert {r["organization"]: r["state"] for r in rows} == {
        "astro": "undeclared",
        "geo": "ok",
        "helio": "ok",
    }
    assert "declare it again with its root" in managed.ok("adm", "verify-mounts").stdout

    checked = managed.run("-o", "json", "adm", "check")
    assert checked.exit_code == 1
    assert [(f["code"], f["severity"], f["identifier"]) for f in json.loads(checked.stdout)] == [
        ("org_undeclared", "warning", "astro")
    ]

    assert managed.ok("delete", "org", "astro").stdout == "organization astro deleted\n"


def test_an_undeclared_organization_stays_usable_under_a_marked_prefix(
    managed: Cli, roots: MemoryStorage
) -> None:
    roots.write_bytes(PREFIX / MARKER_FILE, render_marker(Marker(1, API, str(INSTANCE_ID))))
    add_undeclared(managed, "astro")
    groups = EffectiveGroups(platform_admin=("huron-platform-admins",))
    roots.ensure_directory(PREFIX / "astro", plan(DirectoryKind.ORGANIZATION, groups))
    managed.ok("adm", "provision-orgs")

    managed.ok("create", "catalog", "stars", "--org", "astro")
    rows = json.loads(managed.ok("-o", "json", "adm", "verify-mounts").stdout)
    assert {r["organization"]: r["state"] for r in rows}["astro"] == "undeclared"
    findings = json.loads(managed.run("-o", "json", "adm", "check").stdout or "[]")
    assert [f for f in findings if f["identifier"] == "astro"] == []

    managed.ok("delete", "catalog", "stars")
    assert managed.ok("delete", "org", "astro").stdout == "organization astro deleted\n"


INHERITING = [
    {
        "name": "helio",
        "display_name": "Heliophysics",
        "groups": {
            "org_admin": ["helio-org-admins"],
            "contributor": ["helio-contributors"],
            "reader": ["helio-readers"],
        },
        "root": str(HELIO_ROOT),
    },
]


@pytest.fixture
def inheriting(tmp_path: Path, roots: MemoryStorage) -> Iterator[Cli]:
    """helio declares org-wide contributor and reader groups; heliophysics has no grants.

    The service holds the helio root as its lake and takes uploads.
    """
    running = Cli(
        tmp_path,
        lambda config: roots,
        PREFIX,
        lake=roots,
        lake_path=HELIO_ROOT,
        organizations=INHERITING,
    )
    running.login_as("alice")
    running.ok("adm", "provision-orgs")
    running.login_as("bob")
    running.ok("create", "catalog", "heliophysics", "--org", "helio")
    running.ok("create", "namespace", "heliophysics.solar-wind", "--allow-collections")
    make_directory(running, "heliophysics", DirectoryKind.CATALOG, HELIO)
    make_directory(
        running, "heliophysics/solar-wind", DirectoryKind.NAMESPACE_WITH_COLLECTIONS, HELIO
    )
    yield running
    running.close()


def test_catalogs_inherit_the_organization_wide_groups(
    inheriting: Cli, roots: MemoryStorage, tmp_path: Path
) -> None:
    cli = inheriting
    sources = json.loads(cli.ok("-o", "json", "get", "grants", "--catalog", "heliophysics").stdout)
    assert [s for s in sources if s["scope"] == "catalog"] == []
    table = cli.ok("get", "grants", "--catalog", "heliophysics").stdout
    assert table.split()[:3] == ["ROLE", "GROUP", "SOURCE"]
    rows = {tuple(line.split(maxsplit=2)) for line in table.splitlines()[1:]}
    assert ("contributor", "helio-contributors", "organization helio") in rows
    assert ("reader", "helio-readers", "organization helio") in rows

    roots.user = "dave"
    cli.login_as("dave")
    cli.ok("catalog", "heliophysics")
    cli.prompter.answers.extend(["Run 7", "Solar wind run seven", *([False] * 7)])
    cli.ok("create", "collection", "solar-wind.run7")
    run7 = make_collection(cli, "run7", HELIO)
    source = tmp_path / "a.txt"
    source.write_text("alpha")
    cli.ok("add", str(source))
    assert "+1" in cli.ok("push").stdout
    assert roots.read_bytes(run7 / "a.txt") == b"alpha"

    roots.user = "erin"
    cli.login_as("erin")
    cli.ok("catalog", "heliophysics")
    assert "a.txt" in cli.ok("get", "files", "solar-wind.run7").stdout
    cli.ok("checkout", "solar-wind.run7")
    other = tmp_path / "b.txt"
    other.write_text("bravo")
    cli.ok("add", str(other))
    refused = cli.run("push")
    assert refused.exit_code == 4 and "FORBIDDEN" in refused.stderr
    assert not roots.exists(run7 / "b.txt")
