"""Organization-wide role groups: ``get grants`` with sources and ``adm grant|revoke --org``.

:class:`GrantsService` stands in for the grant routes at the HTTP boundary, answering as the
service does once an organization grants catalog_admin, contributor and reader to every catalog
of it: ``GET /organizations/{o}/grants`` holds all four roles, ``GET /catalogs/{c}/grants`` merges
the organization's catalog-role groups in, and ``GET /catalogs/{c}/grants/sources`` says where
each group comes from. Everything else goes to the in-process service.
"""

import json
import re
from collections.abc import Callable, Iterable

import httpx
import pytest

from tests.support.cli import Cli
from tests.support.lake import ORG_ADMIN, PLATFORM_ADMIN

CATALOG_ROLES = ("catalog_admin", "contributor", "reader")
ROLES = ("org_admin", *CATALOG_ROLES)
_ORGANIZATION = re.compile(r"^/api/v1/organizations/(?P<name>[^/]+)/grants(?:/(?P<role>[^/]+))?$")
_CATALOG = re.compile(r"^/api/v1/catalogs/(?P<name>[^/]+)/grants(?:/(?P<role>sources|[a-z_]+))?$")


class GrantsService:
    """The grant routes of a service whose organizations grant catalog roles to their catalogs."""

    def __init__(
        self, forward: Callable[[httpx.Request], httpx.Response], declared: Iterable[str] = ()
    ) -> None:
        self._forward = forward
        self.declared = set(declared)
        self.platform = ["huron-platform-admins"]
        self.organizations: dict[str, dict[str, list[str]]] = {
            "helio": {
                "org_admin": ["helio-org-admins"],
                "catalog_admin": [],
                "contributor": ["helio-contributors"],
                "reader": ["helio-readers"],
            }
        }
        self.catalogs: dict[str, tuple[str, dict[str, list[str]]]] = {
            "heliophysics": (
                "helio",
                {
                    "catalog_admin": ["helio-catalog-admins"],
                    "contributor": [],
                    "reader": ["helio-readers", "solar-guests"],
                },
            ),
            "spare": ("helio", {"catalog_admin": [], "contributor": [], "reader": []}),
        }
        self.seen: list[tuple[str, str]] = []
        self.puts: list[tuple[str, list[str]]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen.append((request.method, request.url.path))
        organization = _ORGANIZATION.match(request.url.path)
        if organization is not None:
            return self._organization(request, organization["name"], organization["role"])
        catalog = _CATALOG.match(request.url.path)
        if catalog is not None and catalog["name"] in self.catalogs:
            return self._catalog(request, catalog["name"], catalog["role"])
        return self._forward(request)

    def _organization(self, request: httpx.Request, name: str, role: str | None) -> httpx.Response:
        groups = self.organizations[name]
        if request.method == "GET" and role is None:
            return httpx.Response(200, json=groups)
        if name in self.declared:
            return _problem(409, "ORGANIZATION_DECLARED", f"the groups of {name} are declared")
        return self._replace(request, groups, str(role))

    def _catalog(self, request: httpx.Request, name: str, role: str | None) -> httpx.Response:
        owner, granted = self.catalogs[name]
        inherited = self.organizations[owner]
        if request.method == "PUT":
            return self._replace(request, granted, str(role))
        if role == "sources":
            return httpx.Response(200, json={"items": self._sources(owner, granted)})
        effective = {
            "platform_admin": self.platform,
            "org_admin": inherited["org_admin"],
            **{r: sorted({*inherited[r], *granted[r]}) for r in CATALOG_ROLES},
        }
        return httpx.Response(200, json=effective)

    def _sources(self, owner: str, granted: dict[str, list[str]]) -> list[dict[str, str]]:
        rows = [{"role": "platform_admin", "group": g, "scope": "platform"} for g in self.platform]
        for role in ROLES:
            rows += [
                {"role": role, "group": g, "scope": "organization"}
                for g in self.organizations[owner][role]
            ]
            rows += [{"role": role, "group": g, "scope": "catalog"} for g in granted.get(role, [])]
        return sorted(rows, key=lambda r: (r["role"], r["group"], r["scope"]))

    def _replace(
        self, request: httpx.Request, groups: dict[str, list[str]], role: str
    ) -> httpx.Response:
        wanted = sorted(set(json.loads(request.content)["ldap_groups"]))
        before = groups[role]
        groups[role] = wanted
        self.puts.append((request.url.path, wanted))
        change = {
            "role": role,
            "ldap_groups": wanted,
            "added": [g for g in wanted if g not in before],
            "removed": [g for g in before if g not in wanted],
        }
        return httpx.Response(200, json=change)


def stand_in(
    cli: Cli, monkeypatch: pytest.MonkeyPatch, declared: Iterable[str] = ()
) -> GrantsService:
    service = GrantsService(cli.router.handle_request, declared)
    monkeypatch.setattr(cli.router, "handle_request", service)
    return service


@pytest.fixture
def grants(seeded_cli: Cli, monkeypatch: pytest.MonkeyPatch) -> tuple[Cli, GrantsService]:
    """helio has heliophysics and spare; alice, a platform admin, is logged in."""
    cli = seeded_cli
    cli.loop.call(cli.runtime.lake.catalogs.create(ORG_ADMIN, "helio", "spare"))
    cli.login_as("alice")
    return cli, stand_in(cli, monkeypatch)


def rows(output: str) -> list[list[str]]:
    return [line.split() for line in output.splitlines()]


def test_get_grants_of_an_organization_lists_all_four_roles(
    grants: tuple[Cli, GrantsService],
) -> None:
    cli, _ = grants
    table = rows(cli.ok("get", "grants", "--org", "helio").stdout)
    assert table == [
        ["ROLE", "GROUPS"],
        ["org_admin", "helio-org-admins"],
        ["catalog_admin", "-"],
        ["contributor", "helio-contributors"],
        ["reader", "helio-readers"],
    ]
    body = json.loads(cli.ok("-o", "json", "get", "grants", "--org", "helio").stdout)
    assert body["reader"] == ["helio-readers"] and body["catalog_admin"] == []


def test_get_grants_of_a_catalog_shows_where_each_group_comes_from(
    grants: tuple[Cli, GrantsService],
) -> None:
    cli, _ = grants
    table = rows(cli.ok("get", "grants", "--catalog", "heliophysics").stdout)
    assert table[0] == ["ROLE", "GROUP", "SOURCE"]
    assert ["platform_admin", "huron-platform-admins", "platform"] in table
    assert ["reader", "helio-readers", "organization", "helio"] in table
    assert ["reader", "helio-readers", "catalog"] in table
    assert ["reader", "solar-guests", "catalog"] in table
    assert ["contributor", "helio-contributors", "organization", "helio"] in table


def test_get_grants_as_json_prints_the_sources(grants: tuple[Cli, GrantsService]) -> None:
    cli, service = grants
    cli.ok("catalog", "heliophysics")
    service.seen.clear()
    items = json.loads(cli.ok("-o", "json", "get", "grants").stdout)
    assert {"role": "reader", "group": "solar-guests", "scope": "catalog"} in items
    assert {"role": "reader", "group": "helio-readers", "scope": "organization"} in items
    assert ("GET", "/api/v1/catalogs/heliophysics") not in service.seen
    assert "scope:" in cli.ok("-o", "yaml", "get", "grants").stdout


def test_a_catalog_without_inherited_groups_needs_no_organization_lookup(
    grants: tuple[Cli, GrantsService],
) -> None:
    cli, service = grants
    service.organizations["helio"] = {role: [] for role in ROLES}
    service.seen.clear()
    table = rows(cli.ok("get", "grants", "--catalog", "spare").stdout)
    assert table == [
        ["ROLE", "GROUP", "SOURCE"],
        ["platform_admin", "huron-platform-admins", "platform"],
    ]
    assert ("GET", "/api/v1/catalogs/spare") not in service.seen


@pytest.mark.parametrize("role", CATALOG_ROLES)
def test_a_catalog_role_is_granted_on_an_organization_with_a_reminder_per_catalog(
    grants: tuple[Cli, GrantsService], role: str
) -> None:
    cli, service = grants
    before = list(service.organizations["helio"][role])
    granted = cli.ok("adm", "grant", role, "helio-extra", "--org", "helio").stdout
    assert f"{role}: added helio-extra, revoked -" in granted
    assert "huron adm apply-acl heliophysics --recursive" in granted
    assert "huron adm apply-acl spare --recursive" in granted
    assert service.organizations["helio"][role] == sorted({*before, "helio-extra"})
    revoked = cli.ok("adm", "revoke", role, "helio-extra", "--org", "helio").stdout
    assert "revoked helio-extra" in revoked and "apply-acl spare" in revoked
    assert service.organizations["helio"][role] == before


def test_org_admin_on_an_organization_needs_no_acl_reminder(
    grants: tuple[Cli, GrantsService],
) -> None:
    cli, service = grants
    granted = cli.ok("adm", "grant", "org_admin", "more-admins", "--org", "helio").stdout
    assert "org_admin: added more-admins" in granted and "apply-acl" not in granted
    assert service.puts == [
        ("/api/v1/organizations/helio/grants/org_admin", ["helio-org-admins", "more-admins"])
    ]


def test_json_output_prints_nothing_and_lists_no_catalogs(
    grants: tuple[Cli, GrantsService],
) -> None:
    cli, service = grants
    service.seen.clear()
    assert cli.ok("-o", "json", "adm", "grant", "reader", "x", "--org", "helio").stdout == ""
    assert ("GET", "/api/v1/catalogs") not in service.seen


def test_an_organization_without_catalogs_gets_no_reminder(
    seeded_cli: Cli, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli = seeded_cli
    cli.loop.call(cli.runtime.lake.organizations.create(PLATFORM_ADMIN, "empty", "Empty", ""))
    cli.login_as("alice")
    service = stand_in(cli, monkeypatch)
    service.organizations["empty"] = {role: [] for role in ROLES}
    granted = cli.ok("adm", "grant", "reader", "x", "--org", "empty").stdout
    assert "reader: added x" in granted and "apply-acl" not in granted


def test_a_catalog_grant_sends_only_the_groups_granted_on_the_catalog(
    grants: tuple[Cli, GrantsService],
) -> None:
    cli, service = grants
    granted = cli.ok("adm", "grant", "contributor", "solar-team", "--catalog", "heliophysics")
    assert "contributor: added solar-team, revoked -" in granted.stdout
    assert "huron adm apply-acl heliophysics --recursive" in granted.stdout
    assert "apply-acl spare" not in granted.stdout
    assert service.puts == [("/api/v1/catalogs/heliophysics/grants/contributor", ["solar-team"])]
    assert service.organizations["helio"]["contributor"] == ["helio-contributors"]


def test_revoking_on_a_catalog_a_group_inherited_from_the_organization_is_refused(
    grants: tuple[Cli, GrantsService],
) -> None:
    cli, service = grants
    refused = cli.run("adm", "revoke", "contributor", "helio-contributors", "--catalog", "spare")
    assert refused.exit_code == 2
    assert "helio-contributors holds contributor on spare through organization helio" in (
        refused.stderr
    )
    assert "huron adm revoke contributor helio-contributors --org helio" in refused.stderr
    assert service.puts == []


def test_revoking_on_a_catalog_a_group_also_inherited_removes_the_catalog_grant(
    grants: tuple[Cli, GrantsService],
) -> None:
    cli, service = grants
    revoked = cli.ok("adm", "revoke", "reader", "helio-readers", "--catalog", "heliophysics")
    assert "reader: added -, revoked helio-readers" in revoked.stdout
    assert service.puts == [("/api/v1/catalogs/heliophysics/grants/reader", ["solar-guests"])]
    assert ["reader", "helio-readers", "organization", "helio"] in rows(
        cli.ok("get", "grants", "--catalog", "heliophysics").stdout
    )


def test_revoking_a_group_that_holds_nothing_changes_nothing(
    grants: tuple[Cli, GrantsService],
) -> None:
    cli, service = grants
    revoked = cli.ok("adm", "revoke", "reader", "nobody", "--catalog", "heliophysics").stdout
    assert "reader: added -, revoked -" in revoked
    assert service.puts == [
        ("/api/v1/catalogs/heliophysics/grants/reader", ["helio-readers", "solar-guests"])
    ]


@pytest.mark.parametrize(
    ("role", "after"),
    [
        ("org_admin", "huron adm provision-orgs"),
        ("catalog_admin", "huron adm apply-acl <catalog> -R"),
        ("contributor", "huron adm apply-acl <catalog> -R"),
        ("reader", "huron adm apply-acl <catalog> -R"),
    ],
)
def test_a_declared_organization_points_at_its_groups_in_the_configuration(
    seeded_cli: Cli, monkeypatch: pytest.MonkeyPatch, role: str, after: str
) -> None:
    cli = seeded_cli
    cli.login_as("alice")
    stand_in(cli, monkeypatch, declared={"helio"})
    for verb in ("grant", "revoke"):
        refused = cli.run("adm", verb, role, "helio-readers", "--org", "helio")
        assert refused.exit_code == 6 and "[ORGANIZATION_DECLARED]" in refused.stderr
        assert f"Edit `groups.{role}` there" in refused.stderr and after in refused.stderr


def test_a_catalog_conflict_keeps_its_own_hint(
    seeded_cli: Cli, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli = seeded_cli
    cli.login_as("alice")
    service = stand_in(cli, monkeypatch, declared={"helio"})

    def conflict(request: httpx.Request) -> httpx.Response:
        if request.method == "PUT":
            return _problem(409, "ORGANIZATION_DECLARED", "declared")
        return service(request)

    monkeypatch.setattr(cli.router, "handle_request", conflict)
    refused = cli.run("adm", "grant", "reader", "x", "--catalog", "heliophysics")
    assert refused.exit_code == 6 and "Edit `groups." not in refused.stderr


@pytest.mark.parametrize(
    ("argv", "hint"),
    [
        (("grant", "org_admin", "x"), "--org"),
        (("grant", "org_admin", "x", "--catalog", "heliophysics"), "--org"),
        (("grant", "reader", "x", "--org", "helio", "--catalog", "heliophysics"), "not both"),
        (("revoke", "contributor", "x", "--org", "helio", "--catalog", "spare"), "not both"),
        (("grant", "owner", "x", "--org", "helio"), "owner"),
    ],
)
def test_role_and_scope_mistakes_are_usage_errors(
    grants: tuple[Cli, GrantsService], argv: tuple[str, ...], hint: str
) -> None:
    cli, service = grants
    refused = cli.run("adm", *argv)
    assert refused.exit_code == 2 and hint in refused.stderr
    assert service.puts == []


def test_get_grants_refuses_an_organization_and_a_catalog_together(
    grants: tuple[Cli, GrantsService],
) -> None:
    cli, _ = grants
    both = cli.run("get", "grants", "--org", "helio", "--catalog", "heliophysics")
    assert both.exit_code == 2 and "not both" in both.stderr


def _problem(status: int, code: str, detail: str) -> httpx.Response:
    document = {"type": "about:blank", "title": code, "status": status, "code": code}
    return httpx.Response(status, json={**document, "detail": detail})
