"""Declared organizations with their own roots: paths, markers, provision-orgs and verify-mounts.

The service answers as one in managed mode would: :class:`ManagedService` stands in at the HTTP
boundary and adds ``declared``, ``root``, ``path`` and ``export`` to organization views, answers
``POST /organizations`` with 409 ``ORGANIZATIONS_MANAGED`` and the deletion or an
organization-wide role change of a declared organization with 409 ``ORGANIZATION_DECLARED``.
"""

import json
import re
from collections import Counter
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import httpx
import pytest

from huron.applications.cli.errors import StorageFailure
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
from huron.pkg.fs.acl import Acl
from tests.support.api import INSTANCE_ID
from tests.support.cli import API, Cli
from tests.support.lake import PLATFORM_ADMIN
from tests.unit.cli.conftest import PREFIX
from tests.unit.cli.test_collections import BASE_ANSWERS

HELIO_ROOT = Path("/data1/huron")
GEO_ROOT = Path("/data2/huron")
HELIO = HELIO_ROOT / "helio"
GEO = GEO_ROOT / "geo"
DECLARED: dict[str, Path | None] = {"helio": HELIO_ROOT, "geo": GEO_ROOT}
_ORGANIZATION = re.compile(r"^/api/v1/organizations(?:/(?P<name>[^/]+))?(?P<rest>/.*)?$")


class ManagedService:
    """The in-process service as a service with declared organizations answers."""

    def __init__(
        self,
        forward: Callable[[httpx.Request], httpx.Response],
        declared: Mapping[str, Path | None],
        rooted: Mapping[str, Path] | None = None,
    ) -> None:
        self._forward = forward
        self._declared = dict(declared)
        self._roots = {**{k: v for k, v in declared.items() if v is not None}, **(rooted or {})}
        self.organization_reads: Counter[str] = Counter()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        matched = _ORGANIZATION.match(request.url.path)
        if matched is None:
            return self._forward(request)
        name, rest = matched["name"], matched["rest"]
        refusal = self._refusal(request.method, name, rest)
        if refusal is not None:
            return refusal
        response = self._forward(request)
        if request.method != "GET" or rest or not response.is_success:
            return response
        body = response.json()
        if name is None:
            body["items"] = [self._view(item) for item in body["items"]]
        else:
            self.organization_reads[name] += 1
            body = self._view(body)
        return httpx.Response(response.status_code, json=body)

    def _refusal(self, method: str, name: str | None, rest: str | None) -> httpx.Response | None:
        if method == "POST" and name is None:
            return _conflict("ORGANIZATIONS_MANAGED", "organizations are declared")
        declared = name in self._declared
        if declared and method == "DELETE" and not rest:
            return _conflict("ORGANIZATION_DECLARED", f"{name} is declared")
        if declared and method == "PUT" and (rest or "").startswith("/grants/"):
            return _conflict("ORGANIZATION_DECLARED", f"the groups of {name} are declared")
        return None

    def _view(self, view: dict[str, Any]) -> dict[str, Any]:
        root = self._roots.get(view["name"])
        return {
            **view,
            "declared": view["name"] in self._declared,
            "root": None if root is None else str(root),
            "path": None if root is None else f"{root}/{view['name']}",
            "export": None if root is None else f"nfs1:/export{root}",
        }


def org_marker(organization: str, instance: str = str(INSTANCE_ID)) -> bytes:
    return render_marker(Marker(1, API, instance, organization))


def named(share: MemoryStorage, path: Path) -> dict[str, str]:
    acl = share.nodes[path].acl
    return {e.qualifier: e.perms for e in acl.access if e.tag == "group" and e.qualifier}


def manage(
    cli: Cli,
    monkeypatch: pytest.MonkeyPatch,
    declared: Mapping[str, Path | None] = DECLARED,
    rooted: Mapping[str, Path] | None = None,
) -> ManagedService:
    service = ManagedService(cli.router.handle_request, declared, rooted)
    monkeypatch.setattr(cli.router, "handle_request", service)
    return service


@pytest.fixture
def managed(
    seeded_cli: Cli, share: MemoryStorage, monkeypatch: pytest.MonkeyPatch
) -> tuple[Cli, ManagedService]:
    """helio (heliophysics) and geo are declared under their roots, quiet is not; alice is in.

    Both roots exist and are owned by alice, the storage admin; nothing below them does.
    """
    cli = seeded_cli
    lake = cli.runtime.lake
    cli.loop.call(lake.organizations.create(PLATFORM_ADMIN, "geo", "Geoscience", ""))
    cli.loop.call(lake.organizations.create(PLATFORM_ADMIN, "quiet", "Quiet", ""))
    share.user = "alice"
    for root in (HELIO_ROOT, GEO_ROOT):
        share.add_root(root, owner="alice")
    platform = EffectiveGroups(platform_admin=("huron-platform-admins",))
    share.ensure_directory(PREFIX / "quiet", plan(DirectoryKind.ORGANIZATION, platform))
    share.calls.clear()
    cli.login_as("alice")
    return cli, manage(cli, monkeypatch)


@pytest.fixture
def provisioned(managed: tuple[Cli, ManagedService], share: MemoryStorage) -> Cli:
    """The declared organizations are provisioned; carol owns heliophysics.solar-wind."""
    cli, _ = managed
    cli.ok("adm", "provision-orgs")
    cli.login_as("bob")
    cli.ok("create", "catalog", "heliophysics", "--org", "helio")
    share.user = "carol"
    cli.login_as("carol")
    cli.ok("create", "namespace", "heliophysics.solar-wind", "--allow-collections")
    return cli


def test_provision_orgs_prepares_every_declared_organization(
    managed: tuple[Cli, ManagedService], share: MemoryStorage
) -> None:
    cli, _ = managed
    done = cli.ok("adm", "provision-orgs")
    assert done.stdout.splitlines() == [
        f"geo: created: {GEO}",
        f"geo: marker written: {GEO / MARKER_FILE}",
        f"helio: created: {HELIO}",
        f"helio: marker written: {HELIO / MARKER_FILE}",
    ]
    assert share.nodes[HELIO].mode == 0o2771
    assert named(share, HELIO) == {"huron-platform-admins": "rwx", "helio-org-admins": "rwx"}
    assert named(share, GEO) == {"huron-platform-admins": "rwx"}
    assert read_marker(share, HELIO) == Marker(1, API, str(INSTANCE_ID), "helio")
    assert read_marker(share, GEO).organization == "geo"
    assert share.nodes[GEO / MARKER_FILE].mode == 0o644
    assert not share.exists(PREFIX / "quiet" / MARKER_FILE)
    before = list(share.calls)
    again = cli.ok("adm", "provision-orgs").stdout
    assert f"helio: exists: {HELIO}" in again and f"geo: marker ok: {GEO / MARKER_FILE}" in again
    assert share.calls == before


def test_provision_orgs_dry_run_and_one_organization(
    managed: tuple[Cli, ManagedService], share: MemoryStorage
) -> None:
    cli, _ = managed
    planned = cli.ok("adm", "provision-orgs", "--dry-run").stdout
    assert f"helio: would create: {HELIO}" in planned
    assert f"geo: would write marker: {GEO / MARKER_FILE}" in planned
    assert share.calls == []
    only = cli.ok("adm", "provision-orgs", "--org", "geo").stdout
    assert "geo: created" in only and "helio" not in only
    assert share.exists(GEO) and not share.exists(HELIO)
    refused = cli.run("adm", "provision-orgs", "--org", "quiet")
    assert refused.exit_code == 2 and "does not declare organization quiet" in refused.stderr
    rows = json.loads(cli.ok("-o", "json", "adm", "provision-orgs", "--org", "geo").stdout)
    assert rows == [
        {"organization": "geo", "step": f"exists: {GEO}"},
        {"organization": "geo", "step": f"marker ok: {GEO / MARKER_FILE}"},
    ]


def test_provision_orgs_never_creates_a_root(
    seeded_cli: Cli, share: MemoryStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli = seeded_cli
    cli.loop.call(cli.runtime.lake.organizations.create(PLATFORM_ADMIN, "geo", "Geo", ""))
    share.user = "alice"
    share.add_root(HELIO_ROOT, owner="alice")
    manage(cli, monkeypatch)
    cli.login_as("alice")
    result = cli.run("adm", "provision-orgs")
    assert result.exit_code == 8
    assert f"error: geo: the root {GEO_ROOT} of organization geo does not exist" in result.stderr
    assert "the CLI could not prepare 1 of 2 organizations: geo" in result.stderr
    assert "--emit-script" in result.stderr
    assert share.exists(HELIO / MARKER_FILE) and not share.exists(GEO_ROOT)


def test_provision_orgs_refuses_a_marker_of_another_instance(
    managed: tuple[Cli, ManagedService], share: MemoryStorage
) -> None:
    cli, _ = managed
    share.ensure_directory(HELIO, plan(DirectoryKind.CATALOG, EffectiveGroups()))
    share.write_bytes(HELIO / MARKER_FILE, org_marker("helio", "other-instance"))
    acl = share.nodes[HELIO].acl
    result = cli.run("adm", "provision-orgs")
    assert result.exit_code == 8 and "Huron does not overwrite it" in result.stderr
    assert share.nodes[HELIO].acl == acl
    assert read_marker(share, HELIO).instance_id == "other-instance"
    assert read_marker(share, GEO).organization == "geo"


def test_provision_orgs_emits_a_script_without_touching_the_share(
    managed: tuple[Cli, ManagedService], share: MemoryStorage
) -> None:
    cli, _ = managed
    script = cli.ok("adm", "provision-orgs", "--emit-script").stdout
    assert script.startswith("#!/bin/sh\n")
    assert f"mkdir {HELIO}" in script and f"mkdir {GEO}" in script
    assert f"setfacl --set-file=- {HELIO}" in script
    assert f"chmod 644 {GEO / MARKER_FILE}" in script
    assert share.calls == []
    cli.configure(acl_backend="none")
    assert "setfacl" not in cli.ok("adm", "provision-orgs", "--emit-script").stdout
    plain = cli.ok("adm", "provision-orgs").stdout
    assert f"helio: created: {HELIO} (modes only, because `acl_backend` is `none`)" in plain


def test_provision_orgs_with_nothing_declared(cli: Cli) -> None:
    cli.login_as("alice")
    assert "nothing to do" in cli.ok("adm", "provision-orgs").stdout


def test_verify_mounts_reports_every_organization(
    managed: tuple[Cli, ManagedService], share: MemoryStorage
) -> None:
    cli, _ = managed

    def states() -> dict[str, tuple[str, str]]:
        rows = json.loads(cli.run("-o", "json", "adm", "verify-mounts").stdout)
        return {row["organization"]: (row["path"], row["state"]) for row in rows}

    assert states() == {
        "geo": (str(GEO), "missing"),
        "helio": (str(HELIO), "missing"),
        "quiet": (f"{PREFIX}/quiet (prefix)", "ok"),
    }
    failed = cli.run("adm", "verify-mounts")
    assert failed.exit_code == 1 and "huron adm provision-orgs" in failed.stdout
    cli.ok("adm", "provision-orgs")
    assert {state for _, state in states().values()} == {"ok"}
    assert cli.ok("adm", "verify-mounts").stdout.split()[:3] == ["ORG", "PATH", "STATE"]
    share.write_bytes(HELIO / MARKER_FILE, org_marker("geo"))
    share.write_bytes(GEO / MARKER_FILE, org_marker("geo", "other-instance"))
    share.write_bytes(PREFIX / MARKER_FILE, org_marker("quiet"))
    assert states() == {
        "geo": (str(GEO), "wrong instance"),
        "helio": (str(HELIO), "wrong org"),
        "quiet": (f"{PREFIX}/quiet (prefix)", "wrong org"),
    }
    share.remove_file(HELIO / MARKER_FILE)
    assert states()["helio"] == (str(HELIO), "no marker")


def test_disk_operations_need_the_organization_marker(
    managed: tuple[Cli, ManagedService], share: MemoryStorage
) -> None:
    cli, _ = managed
    cli.login_as("bob")
    refused = cli.run("create", "catalog", "spare", "--org", "helio")
    assert refused.exit_code == 8 and f"{HELIO} is not mounted" in refused.stderr
    assert "huron adm provision-orgs" in refused.stderr
    assert f"mounted on this machine (from nfs1:/export{HELIO_ROOT})" in refused.stderr
    assert cli.run("describe", "catalog", "spare").exit_code == 5
    share.ensure_directory(HELIO, plan(DirectoryKind.ORGANIZATION, EffectiveGroups()))
    share.write_bytes(HELIO / MARKER_FILE, org_marker("geo"))
    wrong = cli.run("create", "catalog", "spare", "--org", "helio")
    assert wrong.exit_code == 8 and "names organization geo, not organization helio" in wrong.stderr
    assert not share.exists(HELIO / "spare")


def test_directories_land_under_the_organization_root(
    provisioned: Cli, share: MemoryStorage, tmp_path: Path
) -> None:
    cli = provisioned
    assert share.is_directory(HELIO / "heliophysics" / "solar-wind")
    assert not share.exists(PREFIX / "helio" / "heliophysics" / "solar-wind")
    share.user = "dave"
    cli.login_as("dave")
    cli.ok("catalog", "heliophysics")
    cli.prompter.answers.extend(BASE_ANSWERS)
    created = cli.ok("create", "collection", "solar-wind.run7")
    assert "is active at helio/heliophysics/solar-wind/run7" in created.stdout
    run7 = HELIO / "heliophysics" / "solar-wind" / "run7"
    assert share.exists(run7 / "metadata.json")
    source = tmp_path / "a.txt"
    source.write_text("alpha")
    cli.ok("add", str(source))
    cli.ok("push")
    assert share.read_bytes(run7 / "a.txt") == b"alpha"
    assert json.loads(cli.ok("-o", "json", "status").stdout)["unrecorded"] == []
    share.write_bytes(run7 / "stray.txt", b"x")
    assert json.loads(cli.ok("-o", "json", "status").stdout)["unrecorded"] == ["stray.txt"]
    share.remove_file(run7 / "stray.txt")
    cli.ok("delete", "collection", "solar-wind.run7", "--yes")
    assert not share.exists(run7)


def test_the_organization_view_is_read_once_per_command(
    provisioned: Cli, managed: tuple[Cli, ManagedService], share: MemoryStorage, tmp_path: Path
) -> None:
    cli, service = managed
    share.user = "dave"
    cli.login_as("dave")
    cli.ok("catalog", "heliophysics")
    cli.prompter.answers.extend(BASE_ANSWERS)
    service.organization_reads.clear()
    cli.ok("create", "collection", "solar-wind.run8")
    assert service.organization_reads == Counter({"helio": 1})


def test_check_reports_organization_findings(
    provisioned: Cli, share: MemoryStorage, managed: tuple[Cli, ManagedService]
) -> None:
    cli = provisioned
    cli.login_as("alice")

    def codes(*argv: str) -> list[tuple[str, str]]:
        found = json.loads(cli.run("-o", "json", "adm", "check", *argv).stdout or "[]")
        return [(f["code"], f["identifier"]) for f in found]

    assert codes() == []
    share.nodes[HELIO].acl = Acl()
    assert codes("--catalog", "heliophysics") == [("org_acl_drift", "helio")]
    cli.configure(acl_backend="none")
    assert codes() == []
    cli.configure(acl_backend="posix")
    share.remove_file(HELIO / MARKER_FILE)
    share.remove_directory(HELIO / "heliophysics" / "solar-wind")
    assert codes() == [("org_marker_missing", "helio"), ("org_acl_drift", "helio")]
    share.write_bytes(GEO / MARKER_FILE, org_marker("helio"))
    mismatch = json.loads(cli.run("-o", "json", "adm", "check").stdout)
    assert {"code": "org_marker_mismatch", "detail": "wrong org"}.items() <= next(
        f for f in mismatch if f["identifier"] == "geo"
    ).items()
    share.remove_file(GEO / MARKER_FILE)
    share.remove_directory(GEO)
    assert ("org_dir_missing", "geo") in codes()


def test_check_skips_acl_drift_of_organizations_whose_admins_are_hidden(
    provisioned: Cli, share: MemoryStorage
) -> None:
    cli = provisioned
    share.nodes[HELIO].acl = Acl()
    cli.login_as("carol")
    found = json.loads(cli.run("-o", "json", "adm", "check", "--catalog", "heliophysics").stdout)
    assert [f["code"] for f in found] == []


def test_check_fails_when_the_organization_admins_cannot_be_read(
    provisioned: Cli, managed: tuple[Cli, ManagedService], monkeypatch: pytest.MonkeyPatch
) -> None:
    cli, service = managed
    cli.login_as("alice")

    def broken(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/organizations/helio/grants":
            raise httpx.ConnectError("connection refused", request=request)
        return service(request)

    monkeypatch.setattr(cli.router, "handle_request", broken)
    failed = cli.run("adm", "check", "--catalog", "heliophysics")
    assert failed.exit_code == 1 and "unreachable" in failed.stderr


def test_get_orgs_shows_where_each_directory_is(managed: tuple[Cli, ManagedService]) -> None:
    cli, _ = managed
    table = cli.ok("get", "orgs").stdout.splitlines()
    assert table[0].split()[-1] == "PATH"
    rows = {line.split()[0]: line.rstrip() for line in table[1:]}
    assert rows["helio"].endswith(str(HELIO))
    assert rows["quiet"].endswith(f"{PREFIX}/quiet (prefix)")
    listing = cli.ok("org").stdout
    assert str(GEO) in listing and f"{PREFIX}/quiet (prefix)" in listing


def test_create_org_is_refused_when_organizations_are_declared(
    managed: tuple[Cli, ManagedService], share: MemoryStorage
) -> None:
    cli, _ = managed
    refused = cli.run("create", "org", "astro")
    assert refused.exit_code == 6 and "[ORGANIZATIONS_MANAGED]" in refused.stderr
    assert "the service configuration declares the organizations" in refused.stderr
    assert "huron adm provision-orgs" in refused.stderr
    assert share.calls == []


def test_declared_organizations_cannot_be_deleted_or_regranted(
    managed: tuple[Cli, ManagedService], share: MemoryStorage
) -> None:
    cli, _ = managed
    cli.ok("adm", "provision-orgs")
    refused = cli.run("delete", "org", "geo")
    assert (
        refused.exit_code == 6
        and "First delete its entry from the service configuration" in refused.stderr
    )
    assert share.exists(GEO / MARKER_FILE)
    grant = cli.run("adm", "grant", "org_admin", "geo-admins", "--org", "geo")
    assert grant.exit_code == 6 and "Edit `groups.org_admin` there" in grant.stderr
    assert "huron adm provision-orgs" in grant.stderr
    reader = cli.run("adm", "grant", "reader", "geo-readers", "--org", "geo")
    assert reader.exit_code == 6 and "Edit `groups.reader` there" in reader.stderr
    assert "huron adm apply-acl <catalog> -R" in reader.stderr
    catalog = cli.run("adm", "grant", "reader", "x", "--catalog", "missing")
    assert catalog.exit_code == 5 and "groups." not in catalog.stderr


def test_deleting_an_organization_with_a_root_leaves_its_directory(
    seeded_cli: Cli, share: MemoryStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli = seeded_cli
    cli.loop.call(cli.runtime.lake.organizations.create(PLATFORM_ADMIN, "quiet", "Quiet", ""))
    manage(cli, monkeypatch, DECLARED, rooted={"quiet": GEO_ROOT})
    share.add_root(GEO_ROOT / "quiet", owner="alice")
    cli.login_as("alice")
    deleted = cli.ok("delete", "org", "quiet").stdout
    assert f"Organization quiet deleted. Its directory {GEO_ROOT / 'quiet'} stays" in deleted
    assert share.exists(GEO_ROOT / "quiet")


def test_undeclared_organizations_keep_the_share_root(
    managed: tuple[Cli, ManagedService], share: MemoryStorage
) -> None:
    cli, _ = managed
    assert "organization quiet deleted" in cli.ok("delete", "org", "quiet").stdout
    assert "quiet" not in cli.ok("get", "orgs").stdout
    assert not share.exists(PREFIX / "quiet")


def test_an_unusable_root_from_the_service_is_refused(
    seeded_cli: Cli, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli = seeded_cli
    manage(cli, monkeypatch, {"helio": Path("relative/root")})
    cli.login_as("bob")
    refused = cli.run("create", "catalog", "spare", "--org", "helio")
    assert refused.exit_code == 8 and "not an absolute, normalized path" in refused.stderr


def test_paths_escaping_the_share_are_refused_before_any_lookup(
    managed: tuple[Cli, ManagedService],
) -> None:
    cli, service = managed
    services, _, _ = cli.services()
    service.organization_reads.clear()
    for bad in ("/etc/passwd", "helio/../geo", ""):
        with pytest.raises(StorageFailure, match="outside the share"):
            services.mount().path(bad)
    assert service.organization_reads == Counter()


def _conflict(code: str, detail: str) -> httpx.Response:
    return httpx.Response(409, json={"status": 409, "code": code, "detail": detail})
