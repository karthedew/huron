"""The directory verbs, ``activate`` and the metadata verbs call the API only.

The CLI sees the share through :class:`ReadOnlyShare`, so a write call fails the test.
"""

import json
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from huron.applications.cli.errors import StorageFailure
from huron.core.storage import MARKER_FILE, Marker, render_marker
from huron.core.storage.memory import MemoryStorage
from tests.fakes.storage import ReadOnlyShare
from tests.support.cli import Cli
from tests.unit.cli.conftest import CATALOG, PREFIX, make_collection
from tests.unit.cli.test_collections import BASE_ANSWERS

RUN7 = CATALOG / "solar-wind" / "run7"


@pytest.fixture
def cli(tmp_path: Path, share: MemoryStorage) -> Iterator[Cli]:
    """The CLI over the service, which holds ``share`` as its lake; the CLI only reads it."""
    running = Cli(tmp_path, lambda config: ReadOnlyShare(share), PREFIX, lake=share)
    yield running
    running.close()


@pytest.fixture
def requests(seeded_cli: Cli) -> list[tuple[str, str]]:
    """The method and path of each request that the CLI sends to the service."""
    seen: list[tuple[str, str]] = []
    seeded_cli.router.observe = lambda request: seen.append((request.method, request.url.path))
    return seen


def mounts(cli: Cli) -> list[dict[str, str]]:
    found: list[dict[str, str]] = json.loads(cli.run("-o", "json", "adm", "verify-mounts").stdout)
    return found


def changes(seen: list[tuple[str, str]]) -> list[tuple[str, str]]:
    return [(method, path) for method, path in seen if method != "GET"]


def test_verify_mounts_checks_the_share_root_marker(cli: Cli, share: MemoryStorage) -> None:
    cli.login_as("alice")
    empty = cli.ok("adm", "verify-mounts")
    assert empty.stdout.split()[:3] == ["ORG", "PATH", "STATE"]
    assert mounts(cli) == [{"organization": "-", "path": f"{PREFIX} (prefix)", "state": "ok"}]
    cli.ok("create", "org", "helio")
    assert mounts(cli) == [
        {"organization": "helio", "path": f"{PREFIX}/helio (prefix)", "state": "ok"}
    ]
    share.write_bytes(PREFIX / MARKER_FILE, render_marker(Marker(1, "http://other", "other-id")))
    refused = cli.run("adm", "verify-mounts")
    assert refused.exit_code == 1 and "wrong instance" in refused.stdout
    assert "scripts/init-root.sh" in refused.stdout and "provision-orgs" not in refused.stdout
    share.remove_file(PREFIX / MARKER_FILE)
    assert mounts(cli)[0]["state"] == "no marker"
    cli.configure(mount_prefix="/not/mounted")
    assert mounts(cli)[0]["state"] == "missing"
    assert cli.run("adm", "verify-mounts").exit_code == 1


def test_create_and_delete_call_the_api_without_a_mount(cli: Cli, share: MemoryStorage) -> None:
    cli.configure(mount_prefix="/not/mounted")
    cli.login_as("alice")
    assert cli.ok("create", "org", "helio", "--display-name", "Heliophysics").stdout == (
        "organization helio ready\n"
    )
    cli.ok("adm", "grant", "org_admin", "helio-org-admins", "--org", "helio")
    cli.login_as("bob")
    created = cli.ok("create", "catalog", "heliophysics", "--org", "helio")
    assert created.stdout == (
        "Catalog heliophysics is ready. To select it, run `huron catalog heliophysics`\n"
    )
    cli.ok("adm", "grant", "catalog_admin", "helio-catalog-admins", "--catalog", "heliophysics")
    cli.login_as("carol")
    cli.ok("catalog", "heliophysics")
    namespace = cli.ok("create", "namespace", "solar-wind.l0", "--parents", "--allow-collections")
    assert namespace.stdout == "namespace heliophysics.solar-wind.l0 ready\n"
    listing = json.loads(cli.ok("-o", "json", "get", "namespaces", "solar-wind").stdout)
    assert [(n["name"], n["collections_allowed"]) for n in listing] == [("l0", True)]
    cli.ok("delete", "namespace", "solar-wind.l0")
    assert cli.ok("delete", "namespace", "solar-wind").stdout == (
        "namespace heliophysics.solar-wind deleted\n"
    )
    cli.login_as("bob")
    assert cli.ok("delete", "catalog", "heliophysics").stdout == "catalog heliophysics deleted\n"
    cli.login_as("alice")
    assert cli.ok("delete", "org", "helio").stdout.splitlines() == [
        "organization helio deleted",
        "There is no current organization now. To select one, run `huron org <name>`",
    ]
    assert not share.exists(PREFIX / "helio")


def test_running_a_create_again_is_refused(seeded_cli: Cli) -> None:
    cli = seeded_cli
    cli.login_as("carol")
    again = cli.run("create", "namespace", "heliophysics.solar-wind", "--allow-collections")
    assert again.exit_code == 6 and "[NAME_TAKEN]" in again.stderr
    cli.login_as("bob")
    assert cli.run("create", "catalog", "heliophysics", "--org", "helio").exit_code == 6
    cli.login_as("alice")
    assert cli.run("create", "org", "helio").exit_code == 6


def test_parents_skips_existing_ancestors_and_creates_missing_ones(
    seeded_cli: Cli, requests: list[tuple[str, str]]
) -> None:
    cli = seeded_cli
    cli.login_as("carol")
    cli.ok("create", "namespace", "heliophysics.solar-wind.l0.daily", "--parents")
    posts = "/api/v1/catalogs/heliophysics/namespaces"
    assert changes(requests) == [("POST", posts)] * 3
    tree = json.loads(
        cli.ok("-o", "json", "get", "namespaces", "heliophysics.solar-wind.l0").stdout
    )
    assert [n["identifier"] for n in tree] == ["heliophysics.solar-wind.l0.daily"]


def test_missing_parents_are_refused_without_parents(seeded_cli: Cli) -> None:
    cli = seeded_cli
    cli.login_as("carol")
    result = cli.run("create", "namespace", "heliophysics.nope.child")
    assert result.exit_code == 5


def test_other_api_errors_pass_through(seeded_cli: Cli) -> None:
    cli = seeded_cli
    cli.login_as("erin")
    assert cli.run("create", "catalog", "x", "--org", "helio").exit_code == 4
    assert cli.run("create", "org", "x").exit_code == 4
    assert cli.run("create", "namespace", "heliophysics.x").exit_code == 4
    assert cli.run("create", "namespace", "heliophysics.x.y", "--parents").exit_code == 4


def test_set_namespace_changes_only_the_row(
    seeded_cli: Cli, requests: list[tuple[str, str]]
) -> None:
    cli = seeded_cli
    cli.login_as("carol")
    forbidden = cli.ok("set", "namespace", "heliophysics.solar-wind", "--no-allow-collections")
    assert forbidden.stdout == "namespace heliophysics.solar-wind does not allow collections\n"
    assert changes(requests) == [("PATCH", "/api/v1/catalogs/heliophysics/namespaces/solar-wind")]


@pytest.fixture
def contributor(seeded_cli: Cli) -> Cli:
    """dave is logged in with heliophysics selected."""
    seeded_cli.login_as("dave")
    seeded_cli.ok("catalog", "heliophysics")
    return seeded_cli


def test_activate_and_the_metadata_verbs_call_the_api_only(
    contributor: Cli, requests: list[tuple[str, str]], tmp_path: Path
) -> None:
    cli = contributor
    cli.prompter.answers.extend(BASE_ANSWERS)
    cli.ok("create", "collection", "solar-wind.run7", "--draft")
    activated = cli.ok("activate", "collection")
    assert activated.stdout == (
        "collection heliophysics.solar-wind.run7 is active at helio/heliophysics/solar-wind/run7\n"
    )
    collection = f"/api/v1/collections/{cli.config_current()}"
    requests.clear()
    cli.state.write_draft(cli.config_current(), {"title": "Run 7b", "description": "d"})
    cli.ok("publish", "meta")
    override = tmp_path / "override.json"
    override.write_text(json.dumps({"type": "object"}))
    cli.ok("set", "override", str(override))
    cli.ok("unset", "override")
    assert changes(requests) == [("PATCH", collection)] * 3
    assert not any(path.endswith("/metadata.json") for _, path in requests)


def test_create_collection_activates_without_a_mount(
    contributor: Cli, requests: list[tuple[str, str]]
) -> None:
    cli = contributor
    cli.configure(mount_prefix="/not/mounted")
    cli.prompter.answers.extend(BASE_ANSWERS)
    cli.ok("create", "collection", "solar-wind.run7")
    assert changes(requests)[-1] == ("POST", f"/api/v1/collections/{cli.config_current()}/activate")
    assert json.loads(cli.ok("-o", "json", "describe", "collection").stdout)["state"] == "active"


@pytest.mark.parametrize("mounted", [True, False])
def test_delete_collection_commits_the_removals_and_checks_no_unrecorded_file(
    contributor: Cli,
    share: MemoryStorage,
    requests: list[tuple[str, str]],
    tmp_path: Path,
    mounted: bool,
) -> None:
    cli = contributor
    cli.prompter.answers.extend(BASE_ANSWERS)
    cli.ok("create", "collection", "solar-wind.run7")
    make_collection(cli)
    source = tmp_path / "a.txt"
    source.write_text("alpha")
    cli.ok("add", str(source), "--as", "sub/a.txt")
    cli.ok("push")
    share.write_bytes(RUN7 / "stray.txt", b"x")
    if not mounted:
        cli.configure(mount_prefix="/not/mounted")
    collection = f"/api/v1/collections/{cli.config_current()}"
    commits: list[httpx.Request] = []
    cli.router.observe = lambda request: commits.extend(
        [request] if request.url.path.endswith("/commits") else []
    )
    deleted = cli.ok("delete", "collection", "solar-wind.run7", "--yes")
    assert deleted.stdout == "collection heliophysics.solar-wind.run7 deleted\n"
    (commit,) = commits
    assert json.loads(commit.content)["removes"] == ["sub/a.txt"]
    assert commit.url.path == f"{collection}/commits"
    assert share.read_bytes(RUN7 / "stray.txt") == b"x"
    assert cli.run("describe", "collection", "solar-wind.run7").exit_code == 5
    assert json.loads(cli.ok("-o", "json", "status").stdout)["collection"] is None


def test_delete_collection_without_files_commits_nothing(
    contributor: Cli, requests: list[tuple[str, str]]
) -> None:
    cli = contributor
    cli.prompter.answers.extend(BASE_ANSWERS)
    cli.ok("create", "collection", "solar-wind.run7")
    collection = f"/api/v1/collections/{cli.config_current()}"
    requests.clear()
    cli.prompter.answers.append(False)
    assert cli.run("delete", "collection", "solar-wind.run7").exit_code == 130
    cli.ok("delete", "collection", "solar-wind.run7", "--yes")
    assert changes(requests) == [("DELETE", collection)] * 2


def test_delete_draft_collection_lists_no_files(
    contributor: Cli, requests: list[tuple[str, str]]
) -> None:
    cli = contributor
    cli.prompter.answers.extend(BASE_ANSWERS)
    cli.ok("create", "collection", "solar-wind.draft", "--draft")
    requests.clear()
    cli.ok("delete", "collection", "solar-wind.draft", "--yes")
    assert not any(path.endswith("/files") for _, path in requests)
    assert cli.run("describe", "collection", "solar-wind.draft").exit_code == 5


def test_a_refused_lookup_is_not_tried_as_another_identifier(
    seeded_cli: Cli, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli = seeded_cli
    cli.login_as("carol")
    cli.ok("catalog", "heliophysics")
    forward = cli.router.handle_request
    tried: list[str] = []

    def refuse(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and "/namespaces/" in request.url.path:
            tried.append(request.url.path)
            problem = {"status": 403, "code": "FORBIDDEN", "detail": "no"}
            return httpx.Response(403, json=problem)
        return forward(request)

    monkeypatch.setattr(cli.router, "handle_request", refuse)
    refused = cli.run("delete", "namespace", "solar-wind")
    assert refused.exit_code == 4 and "[FORBIDDEN]" in refused.stderr
    assert tried == ["/api/v1/catalogs/heliophysics/namespaces/solar-wind"]


def test_verify_catalog_checks_the_marker_of_the_catalogs_organization(
    seeded_cli: Cli, share: MemoryStorage
) -> None:
    seeded_cli.login_as("dave")
    services, _, _ = seeded_cli.services()
    assert services.mount().verify_catalog("heliophysics").base == PREFIX
    share.remove_file(PREFIX / MARKER_FILE)
    services, _, _ = seeded_cli.services()
    with pytest.raises(StorageFailure):
        services.mount().verify_catalog("heliophysics")
