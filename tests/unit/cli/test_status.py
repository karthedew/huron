"""``huron status``: the header, the staged table, drift, next-step hints and ``--all``."""

import json
from pathlib import Path

import httpx
import pytest
from rich.console import Console

from huron.applications.cli.commands.status import STAGED_COLUMNS
from huron.applications.cli.localstate import StagedAdd
from huron.applications.cli.output import OutputFormat, human_size, render
from huron.core.storage import LakePath
from huron.core.storage.memory import MemoryStorage
from tests.support.cli import Cli
from tests.unit.cli.conftest import make_collection

BASE_ANSWERS = ["Run 7", "Solar wind run seven", *([False] * 7)]
RUN7 = "heliophysics.solar-wind.run7"
RUN8 = "heliophysics.solar-wind.run8"
RUN7_DIR = LakePath.of("helio", "heliophysics", "solar-wind", "run7")
WHERE = "in catalog heliophysics, organization helio"
NOTHING_STAGED = "Nothing is staged. To stage files, run `huron add <file>`"
PUSH_HINT = 'To push, run `huron push -m "<message>"`. To unstage a path, run `huron rm <path>`'
NOTHING_ANYWHERE = "Nothing is staged in any working copy"
REPORT_KEYS = {
    "organization",
    "catalog",
    "collection",
    "state",
    "your_version",
    "service_version",
    "behind",
    "adds",
    "removes",
    "unrecorded",
    "unreadable",
    "staged",
    "pending_commit",
}


@pytest.fixture
def ready(seeded_cli: Cli) -> Cli:
    """run7 and run8 are active at version 3 with working copies; run8 is checked out."""
    seeded_cli.login_as("dave")
    seeded_cli.ok("catalog", "heliophysics")
    for name in ("run7", "run8"):
        seeded_cli.prompter.answers.extend(BASE_ANSWERS)
        seeded_cli.ok("create", "collection", f"solar-wind.{name}")
        make_collection(seeded_cli, name)
    return seeded_cli


@pytest.fixture
def staged(ready: Cli, tmp_path: Path) -> Cli:
    """run7 checked out at version 4 with a.txt recorded, b.txt (2000 bytes) staged to add and
    a.txt staged to remove."""
    source = tmp_path / "a.txt"
    source.write_text("alpha" * 400)
    ready.ok("checkout", "solar-wind.run7")
    ready.ok("add", str(source))
    ready.ok("push", "-m", "first")
    ready.ok("add", str(source), "--as", "b.txt")
    ready.ok("rm", "a.txt")
    return ready


def lines(cli: Cli, *argv: str) -> list[str]:
    return [line.rstrip() for line in cli.ok(*argv).stdout.splitlines()]


def requested(cli: Cli, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The paths of every service request from now on."""
    paths: list[str] = []
    forward = cli.router.handle_request

    def record(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return forward(request)

    monkeypatch.setattr(cli.router, "handle_request", record)
    return paths


def test_status_with_nothing_staged_says_how_to_stage(ready: Cli) -> None:
    assert lines(ready, "status") == [
        f"On collection {RUN8} (version 3, up to date) {WHERE}",
        NOTHING_STAGED,
    ]


def test_status_lists_staged_adds_and_removes_in_a_table(staged: Cli, tmp_path: Path) -> None:
    shown = lines(staged, "status")
    assert shown[0] == f"On collection {RUN7} (version 4, up to date) {WHERE}"
    assert shown[1].split() == ["STAGED", "PATH", "SIZE", "UPLOAD", "FROM"]
    source = str((tmp_path / "a.txt").resolve())
    assert shown[2].split() == ["add", "b.txt", "2.0", "KiB", "-", source]
    assert shown[3].split() == ["remove", "a.txt", "-", "-", "-"]
    assert shown[4:] == [PUSH_HINT]


def test_status_names_unrecorded_files_on_the_share(staged: Cli, share: MemoryStorage) -> None:
    share.write_bytes(RUN7_DIR.joinpath("stray.txt"), b"x", 0o644)
    share.make_directory(RUN7_DIR.joinpath("deep"), 0o2750)
    share.write_bytes(RUN7_DIR.joinpath("deep", "other.txt"), b"y", 0o644)
    shown = lines(staged, "status")
    assert "Unrecorded files on the share: deep/other.txt, stray.txt" in shown
    assert shown[-1] == PUSH_HINT


def test_status_does_not_name_nfs_files_or_what_a_snapshot_directory_holds(
    staged: Cli, share: MemoryStorage
) -> None:
    share.write_bytes(RUN7_DIR.joinpath(".nfs000000000123abcd00000001"), b"x", 0o600)
    share.make_directory(RUN7_DIR.joinpath(".snapshot"), 0o777)
    share.write_bytes(RUN7_DIR.joinpath(".snapshot", "copy.txt"), b"x", 0o644)
    share.write_bytes(RUN7_DIR.joinpath("stray.txt"), b"x", 0o644)
    report = json.loads(staged.ok("-o", "json", "status").stdout)
    assert (report["unrecorded"], report["unreadable"]) == (["stray.txt"], [])


def test_status_names_the_entries_that_it_cannot_read_and_goes_on(
    staged: Cli, share: MemoryStorage
) -> None:
    share.make_directory(RUN7_DIR.joinpath("closed"), 0o2750)
    share.write_bytes(RUN7_DIR.joinpath("closed", "hidden.txt"), b"x", 0o644)
    share.unreadable.add(RUN7_DIR.joinpath("closed"))
    share.write_bytes(RUN7_DIR.joinpath(".nfs000000000123abcd00000001"), b"x", 0o600)
    share.write_bytes(RUN7_DIR.joinpath("stray.txt"), b"x", 0o644)
    shown = lines(staged, "status")
    assert "Unrecorded files on the share: stray.txt" in shown
    assert (
        "The CLI cannot read these entries on the share: helio/heliophysics/solar-wind/run7/closed"
    ) in shown
    report = json.loads(staged.ok("-o", "json", "status").stdout)
    assert (report["unrecorded"], report["unreadable"]) == (
        ["stray.txt"],
        ["helio/heliophysics/solar-wind/run7/closed"],
    )


def test_status_names_a_collection_directory_that_it_cannot_list(
    staged: Cli, share: MemoryStorage
) -> None:
    share.unreadable.add(RUN7_DIR)
    report = json.loads(staged.ok("-o", "json", "status").stdout)
    assert (report["unrecorded"], report["unreadable"]) == (
        [],
        ["helio/heliophysics/solar-wind/run7"],
    )
    share.unreadable.add(RUN7_DIR.parent)
    report = json.loads(staged.ok("-o", "json", "status").stdout)
    assert report["unreadable"] == ["helio/heliophysics/solar-wind/run7"]


def test_status_refuses_a_collection_directory_that_is_a_link(
    staged: Cli, share: MemoryStorage
) -> None:
    for location in [p for p in share.nodes if p.names[: len(RUN7_DIR.names)] == RUN7_DIR.names]:
        del share.nodes[location]
    share.symlink(RUN7_DIR, "/etc")
    refused = staged.run("status")
    assert refused.exit_code == 1
    assert refused.stderr.splitlines() == [
        "error: helio/heliophysics/solar-wind/run7 is a symbolic link. The lake must not contain"
        " symbolic links. Remove it. [SYMLINK_IN_LAKE]"
    ]
    assert refused.stdout == ""


def test_status_says_when_the_share_is_not_mounted(staged: Cli) -> None:
    staged.configure(mount_prefix="/elsewhere")
    shown = lines(staged, "status")
    assert (
        "The share is not mounted on this machine. The CLI did not check for unrecorded files"
        in shown
    )
    assert not any(line.startswith("Unrecorded files on the share") for line in shown)


def test_status_behind_the_service_names_both_versions_and_says_pull(ready: Cli) -> None:
    version = ready.working().base_version
    ready.ok("unset", "override")
    ready.rebase(version)
    shown = lines(ready, "status")
    assert shown[0] == f"On collection {RUN8} (version 3, behind the service's version 4) {WHERE}"
    assert shown[1:] == [
        "Your working copy is behind the service. Run `huron pull`",
        NOTHING_STAGED,
    ]
    ready.ok("pull")
    assert "up to date" in lines(ready, "status")[0]


def test_status_without_a_checkout_shows_the_context_and_hints(seeded_cli: Cli) -> None:
    seeded_cli.login_as("dave")
    assert "huron catalog <name>" in seeded_cli.ok("status").stdout
    seeded_cli.ok("catalog", "heliophysics")
    shown = seeded_cli.ok("status").stdout
    assert "organization  helio" in shown and "To choose one, run `huron checkout`" in shown


def test_status_json_keeps_every_key_and_adds_the_staged_rows(staged: Cli, tmp_path: Path) -> None:
    report = json.loads(staged.ok("-o", "json", "status").stdout)
    assert set(report) == REPORT_KEYS
    assert (report["adds"], report["removes"], report["behind"]) == (["b.txt"], ["a.txt"], False)
    source = str((tmp_path / "a.txt").resolve())
    assert report["staged"] == [
        {"action": "add", "rel_path": "b.txt", "size": 2000, "upload": None, "source": source},
        {"action": "remove", "rel_path": "a.txt", "size": None, "upload": None, "source": None},
    ]
    assert report["pending_commit"] is None
    assert "staged" in staged.ok("-o", "yaml", "status").stdout


def test_status_json_of_an_empty_stage_has_no_staged_rows(ready: Cli) -> None:
    assert json.loads(ready.ok("-o", "json", "status").stdout)["staged"] == []


def test_status_all_shows_only_copies_with_something_staged(
    staged: Cli, monkeypatch: pytest.MonkeyPatch
) -> None:
    staged.ok("checkout", "solar-wind.run8")
    paths = requested(staged, monkeypatch)
    shown = lines(staged, "status", "--all")
    assert shown[0] == f"On collection {RUN7} (version 4) {WHERE}"
    assert [row.split()[0] for row in shown[1:4]] == ["STAGED", "add", "remove"]
    assert shown[4:] == [f"To push or unstage these changes, run `huron checkout {RUN7}` first"]
    run7 = _id_of(staged, RUN7)
    assert not any(run7 in path for path in paths)


def test_status_all_marks_the_checked_out_copy(staged: Cli, tmp_path: Path) -> None:
    staged.ok("checkout", "solar-wind.run8")
    source = tmp_path / "c.txt"
    source.write_text("c")
    staged.ok("add", str(source))
    shown = lines(staged, "status", "--all")
    first, second = _sections(shown)
    assert first[0] == f"On collection {RUN7} (version 4) {WHERE}"
    assert second[0] == f"* On collection {RUN8} (version 3, up to date) {WHERE}"
    assert second[-1] == PUSH_HINT
    assert second[2].split()[:4] == ["add", "c.txt", "1", "B"]


def test_status_all_with_nothing_staged_shows_only_the_checked_out_copy(ready: Cli) -> None:
    assert lines(ready, "status", "--all") == [
        f"* On collection {RUN8} (version 3, up to date) {WHERE}",
        NOTHING_ANYWHERE,
    ]
    ready.configure(current_collection=None)
    assert lines(ready, "status", "--all") == [NOTHING_ANYWHERE]


def test_status_all_without_any_working_copy(seeded_cli: Cli) -> None:
    seeded_cli.login_as("dave")
    assert lines(seeded_cli, "status", "--all") == [
        "There are no working copies on this machine."
        " To make one, run `huron checkout <identifier>`",
        NOTHING_ANYWHERE,
    ]
    assert json.loads(seeded_cli.ok("-o", "json", "status", "--all").stdout) == []


def test_status_all_without_a_checkout_needs_no_service(
    staged: Cli, monkeypatch: pytest.MonkeyPatch
) -> None:
    staged.configure(current_collection=None)
    paths = requested(staged, monkeypatch)
    shown = lines(staged, "status", "--all")
    assert shown[0] == f"On collection {RUN7} (version 4) {WHERE}"
    assert not any("/collections/" in path for path in paths)


def test_status_all_in_json_is_a_list_of_reports(staged: Cli) -> None:
    staged.ok("checkout", "solar-wind.run8")
    reports = json.loads(staged.ok("-o", "json", "status", "--all").stdout)
    assert [(r["collection"], r["current"]) for r in reports] == [(RUN7, False), (RUN8, True)]
    assert all(set(report) == {*REPORT_KEYS, "current"} for report in reports)
    other, current = reports
    assert other["catalog"] == "heliophysics" and other["your_version"] == 4
    assert (other["state"], other["service_version"], other["behind"]) == (None, None, None)
    assert other["unrecorded"] is None and len(other["staged"]) == 2
    assert (current["state"], current["behind"], current["staged"]) == ("active", False, [])


def test_status_all_in_json_names_each_collections_own_catalog_and_organization(
    ready: Cli,
) -> None:
    ready.state.check_out("c-1", "terra.ground.site1", 2, "geo/terra/ground/site1")
    ready.state.check_out("c-2", "terra.ground.site2", 1, None)
    reports = json.loads(ready.ok("--catalog", "terra", "-o", "json", "status", "--all").stdout)
    places = {r["collection"]: (r["catalog"], r["organization"]) for r in reports}
    assert places == {
        RUN7: ("heliophysics", "helio"),
        RUN8: ("heliophysics", "helio"),
        "terra.ground.site1": ("terra", "geo"),
        "terra.ground.site2": ("terra", None),
    }


def test_status_all_of_a_copy_in_another_catalog_names_its_organization(ready: Cli) -> None:
    ready.state.check_out("c-1", "terra.ground.site1", 2, "geo/terra/ground/site1")
    with ready.state.changing("c-1") as working:
        working.adds = [StagedAdd("x.txt", "/src/x.txt", 3, 10, "ab" * 32)]
    assert lines(ready, "status", "--all")[0] == (
        "On collection terra.ground.site1 (version 2) in catalog terra, organization geo"
    )


def test_status_table_wraps_a_long_source_path_instead_of_cutting_its_file_name() -> None:
    source = "/very/long/" + "directory/" * 12 + "the-file-name.bin"
    row = {
        "action": "add",
        "rel_path": "the-file-name.bin",
        "size": 3000,
        "upload": None,
        "source": source,
    }
    out = Console(width=72, color_system=None, record=True)
    with out.capture() as captured:
        render(out, [row], STAGED_COLUMNS, OutputFormat.TABLE)
    shown = captured.get()
    assert "…" not in shown
    folded = "".join(line.split()[-1] for line in shown.splitlines()[1:])
    assert folded.endswith("the-file-name.bin")


def test_status_shows_the_upload_state_of_each_add_and_the_pending_commit(
    staged: Cli, tmp_path: Path
) -> None:
    staged.ok("rm", "a.txt")
    staged.router.fail_commits = "before"
    assert staged.run("push").exit_code == 1
    pending = staged.working().pending_commit
    assert pending is not None
    shown = lines(staged, "status")
    assert shown[2].split()[:5] == ["add", "b.txt", "2.0", "KiB", "ready"]
    assert shown[3:] == [
        f"The CLI did not get the result of the commit request {pending.request_id}."
        " To get the result, run `huron push`"
    ]
    report = json.loads(staged.ok("-o", "json", "status").stdout)
    assert report["pending_commit"] == pending.request_id
    assert [row["upload"] for row in report["staged"]] == ["ready"]


def test_rm_twice_unstages_the_removal_and_rm_of_an_add_says_so(staged: Cli) -> None:
    assert staged.ok("rm", "a.txt").stdout.strip() == "unstaged removal of a.txt"
    assert staged.ok("rm", "b.txt").stdout.strip() == "unstaged b.txt"
    assert lines(staged, "status")[1:] == [NOTHING_STAGED]
    assert staged.ok("rm", "A.TXT").stdout.strip() == "staged removal of a.txt"
    assert [row.split()[:2] for row in lines(staged, "status")[2:3]] == [["remove", "a.txt"]]


@pytest.mark.parametrize(
    ("size", "text"),
    [
        (0, "0 B"),
        (1023, "1023 B"),
        (1024, "1.0 KiB"),
        (1536, "1.5 KiB"),
        (1024**2 - 1, "1.0 MiB"),
        (5 * 1024**3, "5.0 GiB"),
        (3 * 1024**5, "3.0 PiB"),
        (2048 * 1024**5, "2048.0 PiB"),
    ],
)
def test_human_size_uses_binary_units(size: int, text: str) -> None:
    assert human_size(size) == text


def _id_of(cli: Cli, identifier: str) -> str:
    return next(c.collection_id for c in cli.state.working_copies() if c.identifier == identifier)


def _sections(shown: list[str]) -> list[list[str]]:
    sections: list[list[str]] = [[]]
    for line in shown:
        if line:
            sections[-1].append(line)
        else:
            sections.append([])
    return sections
