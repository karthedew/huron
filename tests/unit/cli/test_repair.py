"""``huron adm repair``: the catalog and organization forms of the repair, through the API."""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from huron.core.storage import ORGANIZATION_MODE, LakePath
from huron.core.storage.memory import MemoryStorage
from tests.fakes.storage import rooted
from tests.support.cli import Cli
from tests.unit.cli.conftest import CATALOG, ORGANIZATION, PREFIX, share_group_warning

SOLAR_WIND = CATALOG.joinpath("solar-wind")
NOTHING = "The API changed nothing\n"


@pytest.fixture
def admin(seeded_cli: Cli) -> Cli:
    """carol, the catalog admin, is logged in with heliophysics selected."""
    seeded_cli.login_as("carol")
    seeded_cli.ok("catalog", "heliophysics")
    return seeded_cli


def remove(share: MemoryStorage, location: LakePath) -> None:
    """Remove the empty directory or the symbolic link at ``location``, as an operator can."""
    del share.nodes[location]


def test_a_catalog_repair_prints_each_directory_that_it_makes(
    admin: Cli, share: MemoryStorage
) -> None:
    remove(share, SOLAR_WIND)
    repaired = admin.ok("adm", "repair", "heliophysics.solar-wind")
    assert (repaired.stdout, repaired.stderr) == (f"changed {SOLAR_WIND}\n", "")
    assert share.stat(SOLAR_WIND) is not None
    assert admin.ok("adm", "repair", "heliophysics.solar-wind").stdout == NOTHING


@pytest.mark.parametrize(
    ("argv", "said"),
    [
        (("heliophysics",), NOTHING),
        (("heliophysics", "--recursive"), f"changed {SOLAR_WIND}\n"),
        (("solar-wind",), f"changed {SOLAR_WIND}\n"),
    ],
    ids=["catalog", "recursive", "relative"],
)
def test_a_catalog_repair_covers_the_identifier_and_below_it_only_when_recursive(
    admin: Cli, share: MemoryStorage, argv: tuple[str, ...], said: str
) -> None:
    remove(share, SOLAR_WIND)
    assert admin.ok("adm", "repair", *argv).stdout == said


def test_a_pending_share_group_is_a_warning_with_the_provisioning_step(admin: Cli) -> None:
    admin.login_as("bob")
    admin.ok("set", "catalog", "heliophysics", "--share-group", "geo-readers")
    admin.login_as("carol")
    repaired = admin.ok("adm", "repair", "heliophysics")
    assert repaired.stdout == NOTHING
    assert repaired.stderr.splitlines() == share_group_warning(
        "geo-readers", "this machine does not know the group geo-readers"
    )


@pytest.mark.parametrize(
    ("namespaces", "count"),
    [(("solar-wind",), "1 path"), (("aurora", "solar-wind"), "2 paths")],
    ids=["one", "two"],
)
def test_each_path_that_the_api_cannot_repair_is_printed_with_its_reason_and_detail(
    admin: Cli, share: MemoryStorage, namespaces: tuple[str, ...], count: str
) -> None:
    admin.ok("create", "namespace", "aurora")
    links = [CATALOG.joinpath(namespace) for namespace in namespaces]
    for link in links:
        remove(share, link)
        share.symlink(link, "/elsewhere")
    failed = admin.run("adm", "repair", "heliophysics", "--recursive")
    assert failed.exit_code == 8
    assert sorted(failed.stdout.splitlines()) == [
        f"failed {link} (symbolic_link): {link} is a symbolic link."
        " The lake must not contain symbolic links. Remove it."
        for link in links
    ]
    assert failed.stderr == f"error: the API could not repair {count}\n"


def test_json_output_is_the_answer_of_the_api(admin: Cli, share: MemoryStorage) -> None:
    remove(share, SOLAR_WIND)
    repaired = admin.ok("-o", "json", "adm", "repair", "heliophysics", "--recursive")
    assert json.loads(repaired.stdout) == {
        "changed": [str(SOLAR_WIND)],
        "warnings": [],
        "failed": [],
    }


def test_an_organization_repair_sets_the_mode_of_its_directory(
    seeded_cli: Cli, share: MemoryStorage
) -> None:
    share.nodes[ORGANIZATION].mode = 0o2750
    seeded_cli.login_as("bob")
    assert seeded_cli.ok("adm", "repair", "--org", "helio").stdout == f"changed {ORGANIZATION}\n"
    assert share.nodes[ORGANIZATION].mode == ORGANIZATION_MODE
    assert seeded_cli.ok("adm", "repair", "--org", "helio").stdout == NOTHING


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        ((), "use an identifier or `--org <org>`"),
        (("heliophysics", "--org", "helio"), "use an identifier or `--org`, not both"),
        (("--org", "helio", "--recursive"), "use `--recursive` only with an identifier"),
        (("Bad",), "'Bad' is not an identifier (segment_chars)"),
    ],
    ids=["neither", "both", "recursive-org", "invalid"],
)
def test_a_repair_needs_one_identifier_or_one_organization(
    admin: Cli, argv: tuple[str, ...], message: str
) -> None:
    refused = admin.run("adm", "repair", *argv)
    assert refused.exit_code == 2
    assert refused.stderr.splitlines()[0] == f"error: {message}"


def test_a_failed_catalog_directory_is_made_by_the_repair_that_its_hint_names(
    seeded_cli: Cli, share: MemoryStorage
) -> None:
    cli = seeded_cli
    cli.login_as("bob")
    share.denied.add(ORGANIZATION)
    failed = cli.run("create", "catalog", "geophysics", "--org", "helio")
    repair = "huron --catalog geophysics adm repair geophysics"
    assert failed.exit_code == 8 and "[STORAGE_FAILED]" in failed.stderr
    assert failed.stderr.splitlines()[-1] == f"hint: to make the directory again, run `{repair}`"
    share.denied.clear()
    repaired = cli.ok(*repair.split()[1:])
    assert repaired.stdout == f"changed {ORGANIZATION.joinpath('geophysics')}\n"


def test_a_symbolic_link_at_a_new_directory_names_the_repair_after_its_removal(
    admin: Cli, share: MemoryStorage
) -> None:
    aurora = CATALOG.joinpath("aurora")
    share.symlink(aurora, "/elsewhere")
    failed = admin.run("create", "namespace", "aurora")
    assert "[SYMLINK_IN_LAKE]" in failed.stderr
    assert failed.stderr.splitlines()[-1] == (
        "hint: the storage administrator must remove the symbolic link."
        " Then the storage administrator must run `huron adm repair heliophysics.aurora`"
    )
    remove(share, aurora)
    assert admin.ok("adm", "repair", "heliophysics.aurora").stdout == f"changed {aurora}\n"


@pytest.fixture
def no_lake(tmp_path: Path, share: MemoryStorage) -> Iterator[Cli]:
    """A service without ``lake_path`` that has helio and heliophysics; bob is logged in."""
    running = Cli(tmp_path, rooted(share), PREFIX)
    running.login_as("alice")
    running.ok("create", "org", "helio")
    running.ok("adm", "grant", "org_admin", "helio-org-admins", "--org", "helio")
    running.login_as("bob")
    running.ok("create", "catalog", "heliophysics", "--org", "helio")
    yield running
    running.close()


@pytest.mark.parametrize("argv", [("heliophysics",), ("--org", "helio")], ids=["catalog", "org"])
def test_a_service_without_a_lake_cannot_repair(no_lake: Cli, argv: tuple[str, ...]) -> None:
    refused = no_lake.run("adm", "repair", *argv)
    assert refused.exit_code == 1
    assert refused.stderr.splitlines()[0] == (
        "error: lake_path is not set. The API cannot repair directories. [LAKE_UNAVAILABLE]"
    )
