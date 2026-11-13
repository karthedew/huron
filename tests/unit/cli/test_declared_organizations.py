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
    OBJECT_DIR,
    OBJECT_DIR_MODE,
    ORGANIZATION_MODE,
    UPLOAD_DIR,
    LakePath,
    Marker,
    OrganizationPlace,
    read_marker,
    render_marker,
)
from huron.core.storage.memory import MemoryStorage
from huron.core.storage.provision import OrganizationTarget, Owner, provision_script
from tests.support.api import INSTANCE_ID
from tests.support.cli import API, Cli
from tests.support.lake import PLATFORM_ADMIN
from tests.unit.cli.conftest import PREFIX, make_collection, make_directory
from tests.unit.cli.test_collections import BASE_ANSWERS

HELIO_ROOT = PREFIX / "data1"
GEO_ROOT = PREFIX / "data2"
HELIO = HELIO_ROOT / "helio"
GEO = GEO_ROOT / "geo"
#: The roots and organization directories as lake paths of the share.
HELIO_BASE = LakePath.of("data1")
GEO_BASE = LakePath.of("data2")
HELIO_DIR = HELIO_BASE.joinpath("helio")
GEO_DIR = GEO_BASE.joinpath("geo")
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
    for root in (HELIO_BASE, GEO_BASE):
        share.add_directory(root, uid=share.uid)
    share.make_directory(LakePath.of("quiet"), ORGANIZATION_MODE)
    share.calls.clear()
    cli.login_as("alice")
    cli.report_service_user(share.uid, share.gid)
    return cli, manage(cli, monkeypatch)


@pytest.fixture
def provisioned(managed: tuple[Cli, ManagedService], share: MemoryStorage) -> Cli:
    """The declared organizations are provisioned; heliophysics.solar-wind is below the root."""
    cli, _ = managed
    cli.ok("adm", "provision-orgs")
    make_directory(cli, "heliophysics", HELIO_DIR)
    make_directory(cli, "heliophysics/solar-wind", HELIO_DIR)
    return cli


#: The steps of the lake path in the share, whose mode the fixtures leave at 2771.
LAKE_STEPS = [
    f"lake path: mode set to 2751: {PREFIX}",
    f"lake path: exists: {PREFIX / UPLOAD_DIR}",
    f"lake path: marker ok: {PREFIX / MARKER_FILE}",
]


def test_provision_orgs_prepares_every_declared_organization(
    managed: tuple[Cli, ManagedService], share: MemoryStorage
) -> None:
    cli, _ = managed
    done = cli.ok("adm", "provision-orgs")
    assert done.stdout.splitlines() == [
        *LAKE_STEPS,
        f"geo: created: {GEO}",
        f"geo: created: {GEO / OBJECT_DIR}",
        f"geo: marker written: {GEO / MARKER_FILE}",
        f"helio: created: {HELIO}",
        f"helio: created: {HELIO / OBJECT_DIR}",
        f"helio: marker written: {HELIO / MARKER_FILE}",
    ]
    assert share.nodes[HELIO_DIR].mode == share.nodes[GEO_DIR].mode == ORGANIZATION_MODE
    assert share.nodes[HELIO_DIR.joinpath(OBJECT_DIR)].mode == OBJECT_DIR_MODE
    assert share.nodes[LakePath()].mode == ORGANIZATION_MODE
    assert read_marker(share, HELIO_DIR) == Marker(1, API, str(INSTANCE_ID), "helio")
    assert read_marker(share, GEO_DIR).organization == "geo"
    assert share.nodes[GEO_DIR.joinpath(MARKER_FILE)].mode == 0o644
    assert share.stat(LakePath.of("quiet", MARKER_FILE)) is None
    before = list(share.calls)
    again = cli.ok("adm", "provision-orgs").stdout
    assert again.splitlines() == [
        f"lake path: exists: {PREFIX / UPLOAD_DIR}",
        f"lake path: marker ok: {PREFIX / MARKER_FILE}",
        f"geo: exists: {GEO}",
        f"geo: exists: {GEO / OBJECT_DIR}",
        f"geo: marker ok: {GEO / MARKER_FILE}",
        f"helio: exists: {HELIO}",
        f"helio: exists: {HELIO / OBJECT_DIR}",
        f"helio: marker ok: {HELIO / MARKER_FILE}",
    ]
    assert share.calls == before


def test_provision_orgs_dry_run_and_one_organization(
    managed: tuple[Cli, ManagedService], share: MemoryStorage
) -> None:
    cli, _ = managed
    planned = cli.ok("adm", "provision-orgs", "--dry-run").stdout
    owner = f"{share.uid}:{share.gid}"
    assert planned.splitlines() == [
        f"lake path: would set mode 2751: {PREFIX}",
        f"lake path: exists: {PREFIX / UPLOAD_DIR}",
        f"lake path: marker ok: {PREFIX / MARKER_FILE}",
        f"geo: would create with owner {owner} and mode 2751: {GEO}",
        f"geo: would create with owner {owner} and mode 700: {GEO / OBJECT_DIR}",
        f"geo: would write marker: {GEO / MARKER_FILE}",
        f"helio: would create with owner {owner} and mode 2751: {HELIO}",
        f"helio: would create with owner {owner} and mode 700: {HELIO / OBJECT_DIR}",
        f"helio: would write marker: {HELIO / MARKER_FILE}",
    ]
    assert share.calls == []
    only = cli.ok("adm", "provision-orgs", "--org", "geo").stdout
    assert only.splitlines() == [
        *LAKE_STEPS,
        f"geo: created: {GEO}",
        f"geo: created: {GEO / OBJECT_DIR}",
        f"geo: marker written: {GEO / MARKER_FILE}",
    ]
    assert share.stat(GEO_DIR) is not None and share.stat(HELIO_DIR) is None
    refused = cli.run("adm", "provision-orgs", "--org", "quiet")
    assert refused.exit_code == 2
    assert refused.stderr.splitlines() == [
        "error: the service configuration does not declare organization quiet",
        "hint: to see the organizations and their paths, run `huron get orgs`",
    ]
    rows = json.loads(cli.ok("-o", "json", "adm", "provision-orgs", "--org", "geo").stdout)
    assert rows == [
        {"organization": "lake path", "step": f"exists: {PREFIX / UPLOAD_DIR}"},
        {"organization": "lake path", "step": f"marker ok: {PREFIX / MARKER_FILE}"},
        {"organization": "geo", "step": f"exists: {GEO}"},
        {"organization": "geo", "step": f"exists: {GEO / OBJECT_DIR}"},
        {"organization": "geo", "step": f"marker ok: {GEO / MARKER_FILE}"},
    ]


def test_provision_orgs_needs_the_service_user(
    managed: tuple[Cli, ManagedService], share: MemoryStorage
) -> None:
    cli, _ = managed
    cli.router.health.clear()
    refused = cli.run("adm", "provision-orgs")
    assert refused.exit_code == 2
    assert refused.stderr.splitlines() == [
        "error: the CLI does not know the service user and group",
        "hint: use `--uid <uid>` and `--gid <gid>`",
    ]
    assert cli.run("adm", "provision-orgs", "--uid", "1000").exit_code == 2
    assert share.calls == []


def test_provision_orgs_takes_the_owner_from_its_options(
    managed: tuple[Cli, ManagedService], share: MemoryStorage
) -> None:
    cli, _ = managed
    share.member_of.add(2001)
    done = cli.ok("adm", "provision-orgs", "--org", "geo", "--gid", "2001").stdout
    owner = f"{share.uid}:2001"
    assert done.splitlines() == [
        f"lake path: owner set to {owner}: {PREFIX}",
        f"lake path: mode set to 2751: {PREFIX}",
        f"lake path: exists: {PREFIX / UPLOAD_DIR}",
        f"lake path: owner set to {owner}: {PREFIX / UPLOAD_DIR}",
        f"lake path: marker ok: {PREFIX / MARKER_FILE}",
        f"geo: created: {GEO}",
        f"geo: owner set to {owner}: {GEO}",
        f"geo: created: {GEO / OBJECT_DIR}",
        f"geo: marker written: {GEO / MARKER_FILE}",
    ]
    assert share.nodes[GEO_DIR].gid == share.nodes[GEO_DIR.joinpath(OBJECT_DIR)].gid == 2001
    refused = cli.run("adm", "provision-orgs", "--uid", "7")
    assert refused.exit_code == 8
    assert refused.stderr.splitlines() == [
        f"error: lake path: permission denied on {PREFIX}",
        f"error: geo: permission denied on {GEO}",
        f"error: helio: permission denied on {HELIO}",
        "error: the CLI could not prepare 3 of 3 directories: lake path, geo, helio",
        "hint: when only `root` may write to a root, run `huron adm provision-orgs --emit-script`",
    ]


def test_provision_orgs_never_creates_a_root(
    seeded_cli: Cli, share: MemoryStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli = seeded_cli
    cli.loop.call(cli.runtime.lake.organizations.create(PLATFORM_ADMIN, "geo", "Geo", ""))
    share.add_directory(HELIO_BASE, uid=share.uid)
    manage(cli, monkeypatch)
    cli.login_as("alice")
    cli.report_service_user(share.uid, share.gid)
    result = cli.run("adm", "provision-orgs")
    assert result.exit_code == 8
    assert result.stderr.splitlines() == [
        f"error: geo: the root {GEO_ROOT} of organization geo does not exist."
        " The storage admin creates it",
        "error: the CLI could not prepare 1 of 3 directories: geo",
        "hint: when only `root` may write to a root, run `huron adm provision-orgs --emit-script`",
    ]
    assert share.stat(HELIO_DIR.joinpath(MARKER_FILE)) is not None and share.stat(GEO_BASE) is None


def test_provision_orgs_refuses_a_marker_of_another_instance(
    managed: tuple[Cli, ManagedService], share: MemoryStorage
) -> None:
    cli, _ = managed
    share.make_directory(HELIO_DIR, 0o2750)
    share.write_bytes(HELIO_DIR.joinpath(MARKER_FILE), org_marker("helio", "other-instance"), 0o644)
    result = cli.run("adm", "provision-orgs")
    assert result.exit_code == 8
    assert result.stderr.splitlines() == [
        f"error: helio: {HELIO / MARKER_FILE} names service other-instance and organization"
        " helio. Huron does not overwrite it",
        "error: the CLI could not prepare 1 of 3 directories: helio",
        "hint: when only `root` may write to a root, run `huron adm provision-orgs --emit-script`",
    ]
    assert share.nodes[HELIO_DIR].mode == 0o2750
    assert share.stat(HELIO_DIR.joinpath(OBJECT_DIR)) is None
    assert read_marker(share, HELIO_DIR).instance_id == "other-instance"
    assert read_marker(share, GEO_DIR).organization == "geo"


def test_provision_orgs_emits_a_script_without_touching_the_share(
    managed: tuple[Cli, ManagedService], share: MemoryStorage
) -> None:
    cli, _ = managed
    script = cli.ok("adm", "provision-orgs", "--emit-script", "--uid", "7", "--gid", "8").stdout
    owner = Owner(7, 8)
    targets = [
        OrganizationTarget(
            OrganizationPlace(name, base, own_marker=True),
            Marker(1, API, str(INSTANCE_ID), name),
            owner,
        )
        for name, base in (("geo", GEO_BASE), ("helio", HELIO_BASE))
    ]
    lake = Marker(1, API, str(INSTANCE_ID))
    assert script == provision_script(str(PREFIX), lake, owner, targets)
    assert share.calls == []


def test_provision_orgs_refuses_a_root_outside_the_lake_path(
    seeded_cli: Cli, share: MemoryStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli = seeded_cli
    manage(cli, monkeypatch, {"helio": Path("/elsewhere/huron")})
    cli.login_as("alice")
    refused = cli.run("adm", "provision-orgs", "--uid", "1000", "--gid", "1000")
    assert refused.exit_code == 2
    assert refused.stderr.splitlines() == [
        f"error: the root /elsewhere/huron of organization helio is not below the lake path"
        f" {PREFIX}",
        "hint: set `mount_prefix` to the directory where this machine mounts `lake_path`",
    ]
    assert share.stat(LakePath.of("helio", MARKER_FILE)) is None


def test_provision_orgs_with_nothing_declared_prepares_the_lake_path(
    cli: Cli, share: MemoryStorage
) -> None:
    cli.login_as("alice")
    share.remove_file(LakePath.of(MARKER_FILE))
    done = cli.ok("adm", "provision-orgs", "--uid", "1000", "--gid", "1000").stdout
    assert done.splitlines() == [
        f"lake path: mode set to 2751: {PREFIX}",
        f"lake path: exists: {PREFIX / UPLOAD_DIR}",
        f"lake path: marker written: {PREFIX / MARKER_FILE}",
    ]
    assert read_marker(share, LakePath()) == Marker(1, API, str(INSTANCE_ID))
    again = cli.ok("adm", "provision-orgs", "--uid", "1000", "--gid", "1000").stdout
    assert again.splitlines()[-1] == f"lake path: marker ok: {PREFIX / MARKER_FILE}"


def test_provision_orgs_refuses_a_lake_path_marker_of_an_organization(
    cli: Cli, share: MemoryStorage
) -> None:
    cli.login_as("alice")
    cli.report_service_user(share.uid, share.gid)
    share.write_bytes(LakePath.of(MARKER_FILE), org_marker("helio"), 0o644)
    result = cli.run("adm", "provision-orgs")
    assert result.exit_code == 8
    assert result.stderr.splitlines() == [
        f"error: lake path: {PREFIX / MARKER_FILE} names service {INSTANCE_ID} and organization"
        " helio. Huron does not overwrite it",
        "error: the CLI could not prepare 1 of 1 directories: lake path",
        "hint: when only `root` may write to a root, run `huron adm provision-orgs --emit-script`",
    ]
    assert share.nodes[LakePath()].mode == 0o2771


def service_file(tmp_path: Path, share: MemoryStorage) -> Path:
    """The service configuration file of helio and geo below their roots, with the owner."""
    path = tmp_path / "huron.yaml"
    path.write_text(
        f"instance_id: {INSTANCE_ID}\n"
        f"lake_path: {PREFIX}\n"
        f"service_uid: {share.uid}\n"
        "service_group: huron\n"
        "organizations:\n"
        f"  - {{name: helio, root: {HELIO_ROOT}, groups: {{org_admin: [helio-org-admins]}}}}\n"
        f"  - {{name: geo, root: {GEO_ROOT}}}\n"
    )
    return path


def test_provision_orgs_reads_a_service_configuration_file_and_sends_no_request(
    cli: Cli, share: MemoryStorage, tmp_path: Path
) -> None:
    for root in (HELIO_BASE, GEO_BASE):
        share.add_directory(root, uid=share.uid)
    cli.gids["huron"] = share.gid
    requests: list[str] = []
    cli.router.observe = lambda request: requests.append(str(request.url))
    config = str(service_file(tmp_path, share))
    planned = cli.ok("adm", "provision-orgs", "--config", config, "--dry-run").stdout
    owner = f"{share.uid}:{share.gid}"
    assert planned.splitlines() == [
        f"lake path: would set mode 2751: {PREFIX}",
        f"lake path: exists: {PREFIX / UPLOAD_DIR}",
        f"lake path: marker ok: {PREFIX / MARKER_FILE}",
        f"helio: would create with owner {owner} and mode 2751: {HELIO}",
        f"helio: would create with owner {owner} and mode 700: {HELIO / OBJECT_DIR}",
        f"helio: would write marker: {HELIO / MARKER_FILE}",
        f"geo: would create with owner {owner} and mode 2751: {GEO}",
        f"geo: would create with owner {owner} and mode 700: {GEO / OBJECT_DIR}",
        f"geo: would write marker: {GEO / MARKER_FILE}",
    ]
    assert share.stat(HELIO_DIR) is None
    done = cli.ok("adm", "provision-orgs", "--config", config).stdout
    assert done.splitlines() == [
        *LAKE_STEPS,
        f"helio: created: {HELIO}",
        f"helio: created: {HELIO / OBJECT_DIR}",
        f"helio: marker written: {HELIO / MARKER_FILE}",
        f"geo: created: {GEO}",
        f"geo: created: {GEO / OBJECT_DIR}",
        f"geo: marker written: {GEO / MARKER_FILE}",
    ]
    assert read_marker(share, HELIO_DIR) == Marker(1, API, str(INSTANCE_ID), "helio")
    script = cli.ok("adm", "provision-orgs", "--config", config, "--emit-script").stdout
    assert f"chown {owner} {GEO / OBJECT_DIR}\nchmod 00700 {GEO / OBJECT_DIR}\n" in script
    assert requests == []


def test_provision_orgs_from_a_file_refuses_an_organization_that_it_does_not_declare(
    cli: Cli, share: MemoryStorage, tmp_path: Path
) -> None:
    config = str(service_file(tmp_path, share))
    before = list(share.calls)
    unknown = cli.run("adm", "provision-orgs", "--config", config)
    assert unknown.exit_code == 2
    assert unknown.stderr.splitlines() == [
        "error: the CLI does not know the service user and group",
        "hint: use `--uid <uid>` and `--gid <gid>`",
    ]
    cli.gids["huron"] = share.gid
    refused = cli.run("adm", "provision-orgs", "--config", config, "--org", "quiet")
    assert refused.exit_code == 2
    assert refused.stderr == (
        "error: the service configuration does not declare organization quiet\n"
    )
    assert share.calls == before


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
    share.write_bytes(HELIO_DIR.joinpath(MARKER_FILE), org_marker("geo"), 0o644)
    share.write_bytes(GEO_DIR.joinpath(MARKER_FILE), org_marker("geo", "other-instance"), 0o644)
    share.write_bytes(LakePath.of(MARKER_FILE), org_marker("quiet"), 0o644)
    assert states() == {
        "geo": (str(GEO), "wrong instance"),
        "helio": (str(HELIO), "wrong org"),
        "quiet": (f"{PREFIX}/quiet (prefix)", "wrong org"),
    }
    share.remove_file(HELIO_DIR.joinpath(MARKER_FILE))
    assert states()["helio"] == (str(HELIO), "no marker")


def test_disk_reads_need_the_organization_marker(
    managed: tuple[Cli, ManagedService], share: MemoryStorage
) -> None:
    cli, _ = managed
    services, _, _ = cli.services()
    with pytest.raises(StorageFailure) as missing:
        services.mount().locate("helio/heliophysics")
    assert missing.value.exit_code == 8 and "helio is not mounted" in missing.value.message
    assert f"mounted on this machine (from nfs1:/export{HELIO_ROOT})" in str(missing.value.hint)
    assert "huron adm provision-orgs" in str(missing.value.hint)
    share.make_directory(HELIO_DIR, ORGANIZATION_MODE)
    share.write_bytes(HELIO_DIR.joinpath(MARKER_FILE), org_marker("geo"), 0o644)
    services, _, _ = cli.services()
    with pytest.raises(StorageFailure, match="names organization geo, not organization helio"):
        services.mount().locate("helio/heliophysics")


def test_status_reads_the_collection_below_the_organization_root(
    provisioned: Cli, share: MemoryStorage
) -> None:
    cli = provisioned
    cli.login_as("dave")
    cli.ok("catalog", "heliophysics")
    cli.prompter.answers.extend(BASE_ANSWERS)
    created = cli.ok("create", "collection", "solar-wind.run7")
    assert "is active at helio/heliophysics/solar-wind/run7" in created.stdout
    run7 = make_collection(cli, "run7", HELIO_DIR)
    assert json.loads(cli.ok("-o", "json", "status").stdout)["unrecorded"] == []
    share.write_bytes(run7.joinpath("stray.txt"), b"x", 0o644)
    assert json.loads(cli.ok("-o", "json", "status").stdout)["unrecorded"] == ["stray.txt"]


def test_the_organization_view_is_read_once_per_command(
    provisioned: Cli, managed: tuple[Cli, ManagedService], share: MemoryStorage, tmp_path: Path
) -> None:
    cli, service = managed
    cli.login_as("dave")
    cli.ok("catalog", "heliophysics")
    cli.prompter.answers.extend(BASE_ANSWERS)
    cli.ok("create", "collection", "solar-wind.run8")
    make_collection(cli, "run8", HELIO_DIR)
    service.organization_reads.clear()
    cli.ok("status")
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
    share.remove_file(HELIO_DIR.joinpath(MARKER_FILE))
    share.remove_directory(HELIO_DIR.joinpath("heliophysics", "solar-wind"))
    assert codes() == [("org_marker_missing", "helio")]
    share.write_bytes(GEO_DIR.joinpath(MARKER_FILE), org_marker("helio"), 0o644)
    mismatch = json.loads(cli.run("-o", "json", "adm", "check").stdout)
    assert {"code": "org_marker_mismatch", "detail": "wrong org"}.items() <= next(
        f for f in mismatch if f["identifier"] == "geo"
    ).items()
    share.remove_file(GEO_DIR.joinpath(MARKER_FILE))
    share.remove_directory(GEO_DIR.joinpath(OBJECT_DIR))
    share.remove_directory(GEO_DIR)
    assert ("org_dir_missing", "geo") in codes()


def test_check_still_checks_the_catalogs_of_an_organization_with_links_in_its_directory(
    provisioned: Cli, share: MemoryStorage
) -> None:
    cli = provisioned
    share.write_bytes(HELIO_DIR.joinpath("heliophysics", "stray.txt"), b"x", 0o644)
    share.symlink(HELIO_DIR.joinpath("stray-link"), "/etc")
    share.symlink(HELIO_DIR.joinpath(OBJECT_DIR, "lnk"), "/etc")
    result = cli.run("-o", "json", "adm", "check")
    assert result.exit_code == 1
    assert [(f["code"], f["identifier"], f["path"]) for f in json.loads(result.stdout)] == [
        ("symbolic_link", "helio", str(HELIO / "stray-link")),
        ("symbolic_link", "helio", str(HELIO / OBJECT_DIR / "lnk")),
        ("file_unrecorded", "heliophysics", str(HELIO / "heliophysics" / "stray.txt")),
    ]


def test_check_skips_the_catalogs_of_an_organization_whose_marker_is_a_link(
    provisioned: Cli, share: MemoryStorage
) -> None:
    cli = provisioned
    share.write_bytes(HELIO_DIR.joinpath("heliophysics", "stray.txt"), b"x", 0o644)
    share.remove_file(HELIO_DIR.joinpath(MARKER_FILE))
    share.symlink(HELIO_DIR.joinpath(MARKER_FILE), "/etc/hostname")
    result = cli.run("-o", "json", "adm", "check")
    assert result.exit_code == 1, result.stderr
    assert [(f["code"], f["identifier"], f["path"]) for f in json.loads(result.stdout)] == [
        ("symbolic_link", "helio", str(HELIO / MARKER_FILE)),
        ("symbolic_link", "helio", str(HELIO / MARKER_FILE)),
    ]


def test_check_stops_with_exit_code_2_when_the_root_of_an_organization_is_not_mounted(
    provisioned: Cli, monkeypatch: pytest.MonkeyPatch
) -> None:
    manage(provisioned, monkeypatch, {"helio": Path("/elsewhere/data1"), "geo": GEO_ROOT})
    result = provisioned.run("adm", "check")
    assert (result.exit_code, result.stdout) == (2, "")
    assert result.stderr.splitlines() == [
        "error: the lake does not open as a directory [LAKE_UNAVAILABLE]"
    ]


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
    assert share.stat(GEO_DIR.joinpath(MARKER_FILE)) is not None
    grant = cli.run("adm", "grant", "org_admin", "geo-admins", "--org", "geo")
    assert grant.exit_code == 6
    assert "Edit `groups.org_admin` there. Then restart the service" in grant.stderr
    reader = cli.run("adm", "grant", "reader", "geo-readers", "--org", "geo")
    assert reader.exit_code == 6
    assert "Edit `groups.reader` there. Then restart the service" in reader.stderr
    catalog = cli.run("adm", "grant", "reader", "x", "--catalog", "missing")
    assert catalog.exit_code == 5 and "groups." not in catalog.stderr


def test_deleting_an_organization_with_a_root_leaves_its_directory(
    seeded_cli: Cli, share: MemoryStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli = seeded_cli
    cli.loop.call(cli.runtime.lake.organizations.create(PLATFORM_ADMIN, "quiet", "Quiet", ""))
    manage(cli, monkeypatch, DECLARED, rooted={"quiet": GEO_ROOT})
    share.add_directory(GEO_BASE.joinpath("quiet"), uid=share.uid)
    cli.login_as("alice")
    deleted = cli.ok("delete", "org", "quiet").stdout
    assert deleted.splitlines() == [
        "organization quiet deleted",
        f"Its directory {GEO_ROOT / 'quiet'} stays. Its storage admin deletes the directory",
    ]
    assert share.stat(GEO_BASE.joinpath("quiet")) is not None


def test_an_undeclared_organization_is_deleted_through_the_api_only(
    managed: tuple[Cli, ManagedService], share: MemoryStorage
) -> None:
    cli, _ = managed
    assert cli.ok("delete", "org", "quiet").stdout == "organization quiet deleted\n"
    assert "quiet" not in cli.ok("get", "orgs").stdout
    assert share.calls == [("rmdir", LakePath.of("quiet"))]


def test_an_unusable_root_from_the_service_is_refused(
    seeded_cli: Cli, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli = seeded_cli
    manage(cli, monkeypatch, {"helio": Path("relative/root")})
    cli.login_as("bob")
    services, _, _ = cli.services()
    with pytest.raises(StorageFailure, match="not an absolute, normalized path"):
        services.mount().site("helio")


def test_paths_escaping_the_share_are_refused_before_any_lookup(
    managed: tuple[Cli, ManagedService],
) -> None:
    cli, service = managed
    services, _, _ = cli.services()
    service.organization_reads.clear()
    for bad in ("/etc/passwd", "helio/../geo", ""):
        with pytest.raises(StorageFailure, match="lake_name"):
            services.mount().locate(bad)
    assert service.organization_reads == Counter()


def _conflict(code: str, detail: str) -> httpx.Response:
    return httpx.Response(409, json={"status": 409, "code": code, "detail": detail})
