"""The current organization and catalog: ``huron org``, ``huron catalog`` and their listings."""

import json
import re
from pathlib import Path

import httpx
import pytest

from huron.applications.cli.config import Config
from huron.core.storage.memory import MemoryStorage
from tests.support.cli import API, Cli
from tests.support.lake import ORG_ADMIN, PLATFORM_ADMIN
from tests.unit.cli.conftest import PREFIX

COPY = "0192b6a0-0000-7000-8000-00000000c0de"


@pytest.fixture
def orgs(seeded_cli: Cli) -> Cli:
    """helio holds heliophysics and spare, geo holds terra, quiet holds nothing; alice is in."""
    cli = seeded_cli
    lake = cli.runtime.lake
    cli.loop.call(lake.catalogs.create(ORG_ADMIN, "helio", "spare"))
    cli.loop.call(lake.organizations.create(PLATFORM_ADMIN, "geo", "Geology", "Rocks"))
    cli.loop.call(lake.catalogs.create(PLATFORM_ADMIN, "geo", "terra"))
    cli.loop.call(lake.organizations.create(PLATFORM_ADMIN, "quiet", "Quiet", "Nothing yet"))
    cli.login_as("alice")
    return cli


def saved(cli: Cli) -> Config:
    return Config.load(cli.config_path, {})


def names(stdout: str) -> list[str]:
    """The NAME column of a table whose first column is CURRENT (rows start with * or blank)."""
    header, *lines = stdout.splitlines()
    start = header.index("NAME")
    return [line[start:].split()[0] for line in lines if line[:1] in ("*", " ")]


def marked(stdout: str) -> list[str]:
    return [line.split()[1] for line in stdout.splitlines() if line.startswith("*")]


def test_org_without_a_selection_lists_every_organization(orgs: Cli) -> None:
    shown = orgs.ok("org").stdout
    lines = shown.splitlines()
    assert lines[0].split()[:4] == ["CURRENT", "NAME", "DISPLAY", "NAME"]
    assert "CATALOGS" in lines[0] and "CREATED BY" in lines[0]
    assert names(shown) == ["geo", "helio", "quiet"]
    assert marked(shown) == []
    assert lines[-2:] == [f"No organization is selected on {API}.", "switch with: huron org <name>"]


def test_org_switches_and_marks_the_current_one(orgs: Cli) -> None:
    switched = orgs.ok("org", "geo").stdout
    assert switched == f"Now using organization geo on {API}\n"
    assert saved(orgs).current_organization == "geo"
    shown = orgs.ok("org").stdout
    assert marked(shown) == ["geo"]
    assert shown.splitlines()[-1] == f"Using organization geo on {API}"
    assert "switch with" not in shown


def test_org_in_json_and_yaml(orgs: Cli) -> None:
    listed = json.loads(orgs.ok("-o", "json", "org").stdout)
    assert set(listed) == {"organization", "api_url", "organizations"}
    assert listed["organization"] is None and listed["api_url"] == API
    assert [row["name"] for row in listed["organizations"]] == ["geo", "helio", "quiet"]
    assert "current" not in listed["organizations"][0]
    switched = json.loads(orgs.ok("-o", "json", "org", "helio").stdout)
    assert switched["organization"] == "helio"
    assert switched["organizations"] == listed["organizations"]
    assert "organization: helio" in orgs.ok("-o", "yaml", "org").stdout


def test_org_that_does_not_exist_is_not_found_and_changes_nothing(orgs: Cli) -> None:
    orgs.ok("catalog", "heliophysics")
    missing = orgs.run("org", "missing")
    assert missing.exit_code == 5 and "NOT_FOUND" in missing.stderr
    assert (saved(orgs).current_organization, saved(orgs).current_catalog) == (
        "helio",
        "heliophysics",
    )


def test_org_when_no_organization_is_visible(orgs: Cli) -> None:
    orgs.login_as("mallory")
    shown = orgs.ok("org").stdout
    assert "CURRENT" not in shown
    assert shown.splitlines() == [
        "You can see no organizations.",
        f"No organization is selected on {API}.",
        "switch with: huron org <name>",
    ]
    assert json.loads(orgs.ok("-o", "json", "org").stdout)["organizations"] == []


def test_switching_org_clears_a_catalog_of_another_organization(orgs: Cli) -> None:
    orgs.ok("catalog", "heliophysics")
    orgs.configure(current_collection=COPY)
    switched = orgs.ok("org", "geo").stdout.splitlines()
    assert switched == [
        f"Now using organization geo on {API}",
        "Cleared catalog heliophysics (it belongs to helio); pick one with: huron catalog",
    ]
    config = saved(orgs)
    assert (config.current_organization, config.current_catalog) == ("geo", None)
    assert config.current_collection == COPY


def test_switching_org_keeps_a_catalog_of_that_organization(orgs: Cli) -> None:
    orgs.configure(current_catalog="heliophysics")
    switched = orgs.ok("org", "helio").stdout
    assert switched == f"Now using organization helio on {API}\n"
    config = saved(orgs)
    assert (config.current_organization, config.current_catalog) == ("helio", "heliophysics")


def test_switching_org_clears_a_catalog_that_cannot_be_found(orgs: Cli) -> None:
    orgs.configure(current_catalog="vanished")
    switched = orgs.ok("org", "geo").stdout
    assert "Cleared catalog vanished (you cannot see it); pick one with: huron catalog" in switched
    assert saved(orgs).current_catalog is None


def test_switching_org_without_a_catalog_clears_nothing(orgs: Cli) -> None:
    assert "Cleared" not in orgs.ok("org", "quiet").stdout
    assert saved(orgs).current_catalog is None


def test_catalog_switch_sets_the_organization(orgs: Cli) -> None:
    first = orgs.ok("catalog", "terra").stdout.splitlines()
    assert first == [
        f"Now using catalog terra on {API}",
        "Switched organization to geo",
        "No collection is checked out; pick one with: huron checkout",
    ]
    assert (saved(orgs).current_organization, saved(orgs).current_catalog) == ("geo", "terra")
    second = orgs.ok("catalog", "heliophysics").stdout
    assert "Switched organization to helio" in second
    same = orgs.ok("catalog", "spare").stdout
    assert "Now using catalog spare" in same and "Switched organization" not in same
    assert saved(orgs).current_organization == "helio"


def test_catalog_lists_the_catalogs_of_the_current_organization(orgs: Cli) -> None:
    orgs.ok("catalog", "heliophysics")
    shown = orgs.ok("catalog").stdout
    lines = shown.splitlines()
    assert lines[0].split() == ["CURRENT", "NAME", "ORGANIZATION", "SCHEMA", "NAMESPACES"]
    assert names(shown) == ["heliophysics", "spare"] and marked(shown) == ["heliophysics"]
    assert f"Using catalog heliophysics in organization helio on {API}" in lines
    assert "No collection is checked out; pick one with: huron checkout" in lines


def test_catalog_without_an_organization_lists_every_catalog(orgs: Cli) -> None:
    shown = orgs.ok("catalog").stdout
    assert names(shown) == ["heliophysics", "spare", "terra"] and marked(shown) == []
    assert shown.splitlines()[-2:] == [
        f"No catalog is selected on {API}.",
        "switch with: huron catalog <name>",
    ]


def test_catalog_of_an_organization_without_catalogs(orgs: Cli) -> None:
    orgs.ok("org", "quiet")
    shown = orgs.ok("catalog").stdout
    assert "CURRENT" not in shown
    assert shown.splitlines() == [
        "Organization quiet has no catalogs you can see;"
        " see every organization's with: huron get catalogs -A",
        f"No catalog is selected on {API}.",
        "switch with: huron catalog <name>",
    ]


def test_catalog_with_no_visible_catalogs_and_no_organization(orgs: Cli) -> None:
    orgs.login_as("mallory")
    assert orgs.ok("catalog").stdout.splitlines()[0] == "You can see no catalogs."


def test_catalog_override_is_shown_in_its_own_organization(orgs: Cli) -> None:
    orgs.ok("org", "quiet")
    shown = orgs.ok("--catalog", "heliophysics", "catalog").stdout
    assert names(shown) == ["heliophysics", "spare"] and marked(shown) == ["heliophysics"]
    assert f"Using catalog heliophysics in organization helio on {API}" in shown.splitlines()
    report = json.loads(orgs.ok("-o", "json", "--catalog", "heliophysics", "status").stdout)
    assert (report["organization"], report["catalog"]) == ("helio", "heliophysics")
    assert saved(orgs).current_organization == "quiet"


def test_catalog_override_that_cannot_be_found_omits_its_organization(orgs: Cli) -> None:
    orgs.ok("org", "helio")
    shown = orgs.ok("--catalog", "vanished", "catalog").stdout
    assert names(shown) == ["heliophysics", "spare", "terra"] and marked(shown) == []
    assert f"Using catalog vanished on {API}" in shown.splitlines()
    report = json.loads(orgs.ok("-o", "json", "--catalog", "vanished", "status").stdout)
    assert (report["organization"], report["catalog"]) == (None, "vanished")


def test_catalog_in_json(orgs: Cli) -> None:
    listed = json.loads(orgs.ok("-o", "json", "catalog").stdout)
    assert set(listed) == {"organization", "catalog", "api_url", "collection", "catalogs"}
    assert [row["name"] for row in listed["catalogs"]] == ["heliophysics", "spare", "terra"]
    switched = json.loads(orgs.ok("-o", "json", "catalog", "terra").stdout)
    assert (switched["organization"], switched["catalog"]) == ("geo", "terra")
    assert [row["name"] for row in switched["catalogs"]] == ["terra"]
    assert switched["collection"] is None and switched["api_url"] == API


def test_get_catalogs_is_scoped_to_the_current_organization(orgs: Cli) -> None:
    def listed(*argv: str) -> list[str]:
        rows = json.loads(orgs.ok("-o", "json", "get", "catalogs", *argv).stdout)
        return [row["name"] for row in rows]

    assert listed() == ["heliophysics", "spare", "terra"]
    orgs.ok("org", "helio")
    assert listed() == ["heliophysics", "spare"]
    assert listed("--org", "geo") == ["terra"]
    assert listed("-A") == listed("--all-orgs") == ["heliophysics", "spare", "terra"]
    table = orgs.ok("get", "catalogs").stdout
    assert table.splitlines()[0].split()[:2] == ["CURRENT", "NAME"]


def test_get_catalogs_refuses_org_with_all_orgs(orgs: Cli) -> None:
    refused = orgs.run("get", "catalogs", "--org", "helio", "-A")
    assert refused.exit_code == 2 and "--org and --all-orgs cannot be combined" in refused.stderr


def test_create_catalog_defaults_to_the_current_organization(
    orgs: Cli, share: MemoryStorage
) -> None:
    refused = orgs.run("create", "catalog", "extra")
    assert refused.exit_code == 2 and "no organization is selected" in refused.stderr
    assert "pass --org <org> or run: huron org <name>" in refused.stderr
    orgs.ok("org", "helio")
    assert "huron catalog extra" in orgs.ok("create", "catalog", "extra").stdout
    assert share.is_directory(PREFIX / "helio" / "extra")
    rows = json.loads(orgs.ok("-o", "json", "get", "catalogs", "--org", "helio").stdout)
    assert "extra" in [row["name"] for row in rows]


def test_status_reports_the_organization(orgs: Cli) -> None:
    assert json.loads(orgs.ok("-o", "json", "status").stdout)["organization"] is None
    orgs.ok("catalog", "heliophysics")
    report = json.loads(orgs.ok("-o", "json", "status").stdout)
    assert report == {
        "organization": "helio",
        "catalog": "heliophysics",
        "api_url": API,
        "collection": None,
    }
    assert re.search(r"^organization\s+helio$", orgs.ok("status").stdout, re.MULTILINE)


def test_current_organization_round_trips_through_the_config_file(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    Config(current_organization="geo", current_catalog="terra").save(path)
    loaded = Config.load(path, {})
    assert (loaded.current_organization, loaded.current_catalog) == ("geo", "terra")
    assert Config.load(tmp_path / "absent.yaml", {}).current_organization is None


def test_current_organization_is_not_a_settable_key(orgs: Cli) -> None:
    refused = orgs.run("config", "set", "current_organization", "geo")
    assert refused.exit_code == 2 and "unknown key" in refused.stderr


def test_switching_org_stops_when_the_current_catalog_cannot_be_checked(
    orgs: Cli, monkeypatch: pytest.MonkeyPatch
) -> None:
    orgs.ok("catalog", "heliophysics")
    forward = orgs.router.handle_request

    def unreachable_catalog(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/catalogs/heliophysics":
            raise httpx.ConnectError("connection refused", request=request)
        return forward(request)

    monkeypatch.setattr(orgs.router, "handle_request", unreachable_catalog)
    refused = orgs.run("org", "geo")
    assert refused.exit_code not in (0, 5) and refused.stdout == ""
    config = saved(orgs)
    assert (config.current_organization, config.current_catalog) == ("helio", "heliophysics")


GONE_HINT = (
    "the current organization gone no longer exists or is hidden from you;"
    " switch with: huron org <name>"
)


def test_deleting_the_current_organization_clears_it(orgs: Cli) -> None:
    orgs.ok("org", "quiet")
    deleted = orgs.ok("delete", "org", "quiet").stdout.splitlines()
    assert deleted == [
        "organization quiet deleted",
        "No organization is selected now; pick one with: huron org <name>",
    ]
    assert saved(orgs).current_organization is None
    assert names(orgs.ok("catalog").stdout) == ["heliophysics", "spare", "terra"]
    assert orgs.ok("org").stdout.splitlines()[-2] == f"No organization is selected on {API}."


def test_deleting_another_organization_keeps_the_current_one(orgs: Cli) -> None:
    orgs.ok("catalog", "heliophysics")
    assert "No organization is selected" not in orgs.ok("delete", "org", "quiet").stdout
    config = saved(orgs)
    assert (config.current_organization, config.current_catalog) == ("helio", "heliophysics")


def test_a_saved_organization_that_is_gone_gets_a_recovery_hint(orgs: Cli) -> None:
    orgs.configure(current_organization="gone")
    for argv in (("catalog",), ("get", "catalogs"), ("create", "catalog", "extra")):
        refused = orgs.run(*argv)
        assert refused.exit_code == 5, argv
        assert "organization 'gone' not found" in refused.stderr, argv
        assert GONE_HINT in " ".join(refused.stderr.split()), argv
    named = orgs.run("get", "catalogs", "--org", "missing")
    assert named.exit_code == 5 and "huron org <name>" not in named.stderr
    assert names(orgs.ok("get", "catalogs", "-A").stdout) == ["heliophysics", "spare", "terra"]


def test_org_warns_when_the_saved_organization_is_not_listed(orgs: Cli) -> None:
    orgs.configure(current_organization="gone")
    shown = orgs.ok("org").stdout
    assert names(shown) == ["geo", "helio", "quiet"] and marked(shown) == []
    assert shown.splitlines()[-2:] == [
        "The current organization gone no longer exists or is hidden from you.",
        "switch with: huron org <name>",
    ]
    assert "Using organization" not in shown


def test_org_warns_when_the_saved_organization_is_hidden(orgs: Cli) -> None:
    orgs.ok("catalog", "heliophysics")
    orgs.login_as("mallory")
    assert orgs.ok("org").stdout.splitlines() == [
        "You can see no organizations.",
        "The current organization helio no longer exists or is hidden from you.",
        "switch with: huron org <name>",
    ]


def test_get_catalogs_explains_an_empty_current_organization(orgs: Cli) -> None:
    orgs.ok("org", "quiet")
    lines = orgs.ok("get", "catalogs").stdout.splitlines()
    assert lines[0].split()[:2] == ["CURRENT", "NAME"]
    assert lines[1:] == [
        "Organization quiet has no catalogs you can see;"
        " see every organization's with: huron get catalogs -A"
    ]
    assert len(orgs.ok("get", "catalogs", "--org", "quiet").stdout.splitlines()) == 1
    assert json.loads(orgs.ok("-o", "json", "get", "catalogs").stdout) == []


def test_no_catalog_hints_point_at_the_catalog_listing(orgs: Cli) -> None:
    orgs.ok("org", "quiet")
    status = " ".join(orgs.ok("status").stdout.split())
    assert "list them with: huron catalog; then run: huron catalog <name>" in status
    refused = orgs.run("get", "collections")
    assert refused.exit_code == 2
    assert "list them with: huron catalog; then run: huron catalog <name>" in " ".join(
        refused.stderr.split()
    )
