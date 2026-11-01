"""Finding your way: help, get, describe, tree, the current catalog, status and checkout."""

import io
import json
import re
from pathlib import Path

import pytest

from huron.applications.cli.prompts import QuestionaryPrompter
from tests.support.cli import Cli
from tests.support.lake import CATALOG_ADMIN, CONTRIBUTOR, ORG_ADMIN, VALID_METADATA

RUN7 = "heliophysics.solar-wind.run7"
DAILY = "heliophysics.solar-wind.l0.daily"


@pytest.fixture
def browsable(seeded_cli: Cli) -> Cli:
    """heliophysics holds solar-wind (run7, active), solar-wind.l0 (daily, a draft) and an empty
    archive; the empty catalog ``spare`` exists too. dave is logged in, no catalog selected."""
    cli = seeded_cli
    lake = cli.runtime.lake
    cli.loop.call(lake.namespaces.create(CATALOG_ADMIN, "heliophysics", "solar-wind", "l0", True))
    cli.loop.call(lake.namespaces.create(CATALOG_ADMIN, "heliophysics", "", "archive", False))
    run7 = cli.loop.call(
        lake.collections.create(
            CONTRIBUTOR, "heliophysics", "solar-wind", "run7", dict(VALID_METADATA)
        )
    )
    cli.loop.call(lake.collections.activate(CONTRIBUTOR, run7.collection.id, 1))
    cli.loop.call(
        lake.collections.create(
            CONTRIBUTOR, "heliophysics", "solar-wind.l0", "daily", dict(VALID_METADATA)
        )
    )
    cli.loop.call(lake.catalogs.create(ORG_ADMIN, "helio", "spare"))
    cli.login_as("dave")
    return cli


def help_text(cli: Cli, capsys: pytest.CaptureFixture[str], *argv: str) -> str:
    capsys.readouterr()
    assert cli.run(*argv, "--help").exit_code == 0
    return capsys.readouterr().out


def test_get_lists_plural_nouns_and_hides_singular_aliases(
    browsable: Cli, capsys: pytest.CaptureFixture[str]
) -> None:
    text = help_text(browsable, capsys, "get")
    for noun in ("orgs", "catalogs", "namespaces", "collections", "files", "log", "schemas"):
        assert re.search(rf"^│ {noun}\s", text, re.MULTILINE), noun
    for alias in ("org", "catalog", "namespace", "collection", "file", "schema", "grant"):
        assert not re.search(rf"^│ {alias}\s", text, re.MULTILINE), alias
    assert browsable.ok("get", "catalog").stdout == browsable.ok("get", "catalogs").stdout
    assert browsable.ok("get", "org").stdout == browsable.ok("get", "orgs").stdout


def test_adm_help_groups_its_verbs(browsable: Cli, capsys: pytest.CaptureFixture[str]) -> None:
    text = help_text(browsable, capsys, "adm")
    assert all(f"─ {title} ─" in text for title in ("Access", "Share", "Schemas"))


def test_get_catalogs_marks_the_current_catalog(browsable: Cli) -> None:
    def marked(stdout: str) -> list[str]:
        return [line.split()[1] for line in stdout.splitlines() if line.startswith("*")]

    first = browsable.ok("get", "catalogs").stdout
    assert first.splitlines()[0].split()[:2] == ["CURRENT", "NAME"] and marked(first) == []
    browsable.ok("catalog", "heliophysics")
    assert marked(browsable.ok("get", "catalogs").stdout) == ["heliophysics"]
    assert marked(browsable.ok("--catalog", "spare", "get", "catalogs").stdout) == []
    rows = json.loads(browsable.ok("-o", "json", "get", "catalogs").stdout)
    assert all("current" not in row and "CURRENT" not in row for row in rows)


def test_get_namespaces_hints_at_the_next_step(browsable: Cli) -> None:
    browsable.ok("catalog", "heliophysics")
    listing = browsable.ok("get", "namespaces").stdout
    assert "heliophysics.archive" in listing and "heliophysics.solar-wind" in listing
    assert "huron get collections <namespace>" in listing and "huron tree" in listing
    rows = json.loads(browsable.ok("-o", "json", "get", "namespaces", "solar-wind").stdout)
    assert [row["identifier"] for row in rows] == ["heliophysics.solar-wind.l0"]


def test_get_collections_in_a_namespace_or_the_whole_catalog(browsable: Cli) -> None:
    browsable.ok("catalog", "heliophysics")
    direct = browsable.ok("get", "collections", "solar-wind").stdout
    assert RUN7 in direct and DAILY not in direct
    assert "check out one with: huron checkout <COLLECTION>" in direct
    everything = browsable.ok("get", "collections").stdout
    assert RUN7 in everything and DAILY in everything and "draft" in everything
    rows = json.loads(browsable.ok("-o", "json", "get", "collections").stdout)
    assert {row["identifier"] for row in rows} == {RUN7, DAILY}
    browsable.configure(current_catalog=None)
    assert browsable.run("get", "collections").exit_code == 2


def test_get_hints_fit_an_empty_listing(browsable: Cli) -> None:
    browsable.login_as("bob")
    browsable.ok("catalog", "spare")
    namespaces = browsable.ok("get", "namespaces").stdout
    assert "huron create namespace <identifier>" in namespaces
    assert "huron get collections <namespace>" not in namespaces
    collections = browsable.ok("get", "collections").stdout
    assert "huron create collection <identifier>" in collections
    assert "huron checkout" not in collections
    archive = browsable.ok("get", "collections", "heliophysics.archive").stdout
    assert "huron checkout" not in archive and "huron tree" in archive


def test_full_identifiers_of_another_catalog_are_found(browsable: Cli) -> None:
    browsable.login_as("bob")
    browsable.ok("catalog", "spare")
    assert f"checked out {RUN7}" in browsable.ok("checkout", RUN7).stdout
    described = json.loads(browsable.ok("-o", "json", "describe", "collection", RUN7).stdout)
    assert described["identifier"] == RUN7
    children = json.loads(browsable.ok("-o", "json", "get", "namespaces", "heliophysics").stdout)
    assert {row["identifier"] for row in children} == {
        "heliophysics.archive",
        "heliophysics.solar-wind",
    }
    rows = json.loads(
        browsable.ok("-o", "json", "get", "collections", "heliophysics.solar-wind").stdout
    )
    assert [row["identifier"] for row in rows] == [RUN7]
    assert RUN7 in browsable.ok("tree", "heliophysics.solar-wind").stdout


def test_a_missing_identifier_names_what_was_tried(browsable: Cli) -> None:
    browsable.login_as("bob")
    browsable.ok("catalog", "spare")
    missing = browsable.run("describe", "collection", "heliophysics.solar-wind.gone")
    assert missing.exit_code == 5
    assert "spare.heliophysics.solar-wind.gone or heliophysics.solar-wind.gone" in missing.stderr
    assert "relative to the current catalog spare" in missing.stderr
    nowhere = browsable.run("get", "namespaces", "nowhere")
    assert nowhere.exit_code == 5 and "spare.nowhere or nowhere" in nowhere.stderr


@pytest.mark.parametrize("argv", [(), ("get",), ("describe",), ("create",), ("adm",), ("set",)])
def test_a_verb_without_a_noun_shows_help_without_an_error_line(
    browsable: Cli, argv: tuple[str, ...]
) -> None:
    result = browsable.run(*argv)
    assert result.exit_code == 2 and "error:" not in result.stderr


def test_get_grants_of_a_catalog_or_an_organization(browsable: Cli) -> None:
    browsable.login_as("alice")
    assert browsable.run("get", "grants").exit_code == 2
    table = browsable.ok("get", "grants", "--catalog", "heliophysics").stdout
    assert "contributor" in table and "helio-contributors" in table
    organization = browsable.ok("get", "grants", "--org", "helio").stdout
    assert "org_admin" in organization and "helio-org-admins" in organization
    both = browsable.run("get", "grants", "--org", "helio", "--catalog", "heliophysics")
    assert both.exit_code == 2


def test_tree_shows_namespaces_and_collections(browsable: Cli) -> None:
    assert browsable.run("tree").exit_code == 2
    browsable.ok("catalog", "heliophysics")
    lines = browsable.ok("tree").stdout.splitlines()
    assert lines[0] == "heliophysics"
    text = "\n".join(lines)
    assert "archive/  (no collections)" in text
    assert "solar-wind/  (collections allowed)" in text and "l0/" in text
    assert f"{RUN7}  active" in text and f"{DAILY}  draft" in text
    assert "huron checkout <COLLECTION>" in text
    assert text.index("solar-wind/") < text.index("l0/") < text.index(DAILY)


def test_tree_in_json_is_nested(browsable: Cli) -> None:
    browsable.ok("catalog", "heliophysics")
    tree = json.loads(browsable.ok("-o", "json", "tree").stdout)
    assert (tree["catalog"], tree["namespace"], tree["collections"]) == ("heliophysics", None, [])
    names = [node["name"] for node in tree["namespaces"]]
    assert names == ["archive", "solar-wind"]
    wind = tree["namespaces"][1]
    assert wind["collections"] == [{"identifier": RUN7, "name": "run7", "state": "active"}]
    assert wind["namespaces"][0]["identifier"] == "heliophysics.solar-wind.l0"
    assert wind["namespaces"][0]["collections"][0]["identifier"] == DAILY


def test_tree_of_a_subtree(browsable: Cli) -> None:
    browsable.ok("catalog", "heliophysics")
    sub = json.loads(browsable.ok("-o", "json", "tree", "solar-wind.l0").stdout)
    assert sub["namespace"] == "solar-wind.l0" and sub["namespaces"] == []
    assert sub["collections_allowed"] is True
    assert [c["identifier"] for c in sub["collections"]] == [DAILY]
    lines = browsable.ok("tree", "solar-wind").stdout.splitlines()
    assert lines[0] == "heliophysics" and "solar-wind/  (collections allowed)" in lines[1]
    table = "\n".join(lines)
    assert "archive" not in table and RUN7 in table and "l0/" in table
    assert browsable.run("tree", "nowhere").exit_code == 5


def test_tree_of_an_empty_catalog(browsable: Cli) -> None:
    browsable.login_as("bob")
    table = browsable.ok("--catalog", "spare", "tree").stdout
    assert table.splitlines()[0] == "spare" and "huron create namespace" in table
    tree = json.loads(browsable.ok("--catalog", "spare", "-o", "json", "tree").stdout)
    assert tree == {"catalog": "spare", "namespace": None, "collections": [], "namespaces": []}


def test_describe_namespace(browsable: Cli) -> None:
    browsable.ok("catalog", "heliophysics")
    described = json.loads(
        browsable.ok("-o", "json", "describe", "namespace", "solar-wind.l0").stdout
    )
    assert described["identifier"] == "heliophysics.solar-wind.l0"
    assert described["collections_allowed"] is True
    full = browsable.ok("describe", "namespace", "heliophysics.archive").stdout
    assert "disk_path" in full
    assert browsable.run("describe", "namespace", "missing").exit_code == 5
    assert browsable.run("describe", "namespace", "Bad").exit_code == 2


def test_catalog_without_a_selection_says_how_to_choose(browsable: Cli) -> None:
    shown = browsable.ok("catalog").stdout
    assert "No catalog is selected" in shown
    assert "heliophysics" in shown and "switch with: huron catalog <name>" in shown
    context = json.loads(browsable.ok("-o", "json", "catalog").stdout)
    assert [row["name"] for row in context.pop("catalogs")] == ["heliophysics"]
    assert context == {
        "organization": None,
        "catalog": None,
        "api_url": "http://huron.test",
        "collection": None,
    }


def test_catalog_without_a_selection_still_reports_the_checked_out_collection(
    browsable: Cli,
) -> None:
    browsable.ok("catalog", "heliophysics")
    browsable.ok("checkout", "solar-wind.run7")
    browsable.configure(current_catalog=None)
    shown = browsable.ok("catalog").stdout
    assert "No catalog is selected" in shown and "huron catalog <name>" in shown
    assert f"Checked out: {RUN7}" in shown and "in catalog heliophysics" in shown


def test_catalog_switches_and_reports_the_checked_out_collection(browsable: Cli) -> None:
    switched = browsable.ok("catalog", "heliophysics").stdout
    assert "Now using catalog heliophysics" in switched
    assert "No collection is checked out" in switched
    shown = browsable.ok("catalog").stdout
    assert "Using catalog heliophysics in organization helio on http://huron.test" in shown
    browsable.ok("checkout", "solar-wind.run7")
    assert re.search(rf"Checked out: {RUN7} \(version \d+\)", browsable.ok("catalog").stdout)
    context = json.loads(browsable.ok("-o", "json", "catalog").stdout)
    assert [row["name"] for row in context.pop("catalogs")] == ["heliophysics"]
    assert context == {
        "organization": "helio",
        "catalog": "heliophysics",
        "api_url": "http://huron.test",
        "collection": RUN7,
    }
    assert browsable.run("catalog", "missing").exit_code == 5
    assert "Using catalog heliophysics" in browsable.ok("catalog").stdout


def test_switching_catalog_mentions_a_collection_of_another_catalog(browsable: Cli) -> None:
    browsable.login_as("bob")
    browsable.ok("catalog", "heliophysics")
    browsable.ok("checkout", "solar-wind.run7")
    switched = browsable.ok("catalog", "spare").stdout
    assert "Now using catalog spare" in switched
    assert f"Checked out: {RUN7}" in switched and "in catalog heliophysics" in switched
    as_json = json.loads(browsable.ok("-o", "json", "catalog", "heliophysics").stdout)
    assert as_json["catalog"] == "heliophysics" and as_json["collection"] == RUN7


def test_status_without_a_checked_out_collection(browsable: Cli) -> None:
    nothing = browsable.ok("status").stdout
    assert "list them with: huron catalog;" in nothing and "huron catalog <name>" in nothing
    assert "huron checkout" not in nothing
    browsable.ok("catalog", "heliophysics")
    table = browsable.ok("status").stdout
    assert "huron checkout" in table
    report = json.loads(browsable.ok("-o", "json", "status").stdout)
    assert report == {
        "organization": "helio",
        "catalog": "heliophysics",
        "api_url": "http://huron.test",
        "collection": None,
    }
    browsable.ok("checkout", "solar-wind.run7")
    report = json.loads(browsable.ok("-o", "json", "status").stdout)
    assert report["catalog"] == "heliophysics" and report["collection"] == RUN7
    assert report["organization"] == "helio"
    assert {"state", "your_version", "service_version", "behind", "adds", "removes"} <= set(report)


def test_checkout_picker_descends_goes_up_and_picks(browsable: Cli) -> None:
    browsable.ok("catalog", "heliophysics")
    prompter = browsable.prompter
    prompter.answers.extend(["solar-wind/", "l0/", "..", "run7"])
    result = browsable.ok("checkout")
    assert f"checked out {RUN7}" in result.stdout
    assert prompter.choices[0] == ["archive/", "solar-wind/"]
    assert prompter.choices[1] == ["..", "l0/", "run7"]
    assert prompter.choices[2] == ["..", "daily"]
    assert prompter.choices[3] == prompter.choices[1]
    assert json.loads(browsable.ok("-o", "json", "status").stdout)["collection"] == RUN7


def test_checkout_picker_leaves_an_empty_namespace_by_going_up(browsable: Cli) -> None:
    browsable.ok("catalog", "heliophysics")
    prompter = browsable.prompter
    prompter.answers.extend(["archive/", "..", "solar-wind/", "l0/", "daily"])
    assert f"checked out {DAILY}" in browsable.ok("checkout").stdout
    assert prompter.choices[1] == [".."]
    assert "heliophysics.archive is empty" in prompter.asked[1]


def test_checkout_picker_refuses_a_catalog_without_namespaces(browsable: Cli) -> None:
    browsable.login_as("bob")
    refused = browsable.run("--catalog", "spare", "checkout")
    assert refused.exit_code == 2 and "has no namespaces" in refused.stderr
    assert browsable.prompter.asked == []


def test_checkout_without_an_identifier_needs_a_terminal_and_a_catalog(browsable: Cli) -> None:
    assert browsable.run("checkout").exit_code == 2
    browsable.ok("catalog", "heliophysics")
    browsable.prompter.interactive = False
    refused = browsable.run("checkout")
    assert refused.exit_code == 2
    assert "huron tree" in refused.stderr and "huron checkout <identifier>" in refused.stderr
    browsable.prompter.interactive = True
    as_json = browsable.run("-o", "json", "checkout")
    assert as_json.exit_code == 2 and "huron tree" in as_json.stderr
    assert browsable.prompter.asked == []


def test_search_uses_the_current_catalog(browsable: Cli) -> None:
    assert browsable.run("search", "-q", "run").exit_code == 2
    browsable.ok("catalog", "heliophysics")
    assert RUN7 in browsable.ok("search", "-q", "solar").stdout
    assert DAILY in browsable.ok("search", "--state", "draft").stdout
    assert browsable.run("search", "heliophysics").exit_code == 2


@pytest.mark.parametrize(
    "argv",
    [
        ("catalog", "use", "heliophysics"),
        ("namespace", "list"),
        ("collection", "list", "solar-wind"),
        ("meta", "edit"),
        ("org", "grant", "helio", "x"),
        ("acl", "apply", "heliophysics"),
        ("platform", "verify-root"),
        ("adm", "verify-root"),
        ("schema", "publish", "helio", "x", "x.json"),
        ("files",),
        ("log",),
        ("check",),
    ],
)
def test_old_spellings_are_usage_errors(browsable: Cli, argv: tuple[str, ...]) -> None:
    assert browsable.run(*argv).exit_code == 2


def test_hints_name_only_current_spellings() -> None:
    root = Path(__file__).resolve().parents[3] / "src" / "huron" / "applications" / "cli"
    old = re.compile(
        r"huron (catalog use|catalog list|namespace |collection |meta |acl |platform |"
        r"org (list|create|delete|describe|grants?|revoke)\b|schema |check\b|files\b|log\b)"
    )
    offenders = [
        f"{path.name}: {match.group(0)}"
        for path in root.rglob("*.py")
        for match in old.finditer(path.read_text())
    ]
    assert offenders == []


def test_questionary_prompter_is_interactive_only_on_a_terminal() -> None:
    class Terminal(io.StringIO):
        def isatty(self) -> bool:
            return True

    assert QuestionaryPrompter(io.StringIO()).interactive is False
    assert QuestionaryPrompter(Terminal()).interactive is True
    assert isinstance(QuestionaryPrompter().interactive, bool)
