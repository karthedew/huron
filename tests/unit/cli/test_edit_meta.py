"""``huron edit meta --file``: a metadata draft from a JSON document, without questions."""

import json
from pathlib import Path

import pytest

from tests.support.cli import Cli

BASE_ANSWERS = ["Run 7", "Solar wind run seven", *([False] * 7)]
RUN8 = "heliophysics.solar-wind.run8"


@pytest.fixture
def ready(seeded_cli: Cli) -> Cli:
    """run7 (version 3, checked out) and run8 are active; dave is logged in."""
    seeded_cli.login_as("carol")
    seeded_cli.ok("create", "namespace", "heliophysics.solar-wind", "--allow-collections")
    seeded_cli.login_as("dave")
    seeded_cli.ok("catalog", "heliophysics")
    for name in ("run8", "run7"):
        seeded_cli.prompter.answers.extend(BASE_ANSWERS)
        seeded_cli.ok("create", "collection", f"solar-wind.{name}")
    return seeded_cli


def document(tmp_path: Path, content: object, name: str = "meta.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(content))
    return path


def test_edit_meta_from_a_file_stores_the_draft_without_asking(ready: Cli, tmp_path: Path) -> None:
    wanted = {"title": "From a file", "description": "No questions"}
    asked = len(ready.prompter.asked)
    edited = ready.ok("edit", "meta", "--file", str(document(tmp_path, wanted)))
    assert edited.stdout == "Draft saved with 0 problems. To publish it, run `huron publish meta`\n"
    assert len(ready.prompter.asked) == asked
    assert ready.state.read_draft(ready.config_current()) == wanted
    ready.ok("publish", "meta")
    shown = json.loads(ready.ok("-o", "json", "describe", "collection").stdout)
    assert shown["metadata"] == wanted
    assert ready.state.read_draft(ready.config_current()) is None


def test_edit_meta_from_a_file_reports_problems_like_the_walkthrough(
    ready: Cli, tmp_path: Path
) -> None:
    edited = ready.ok("edit", "meta", "--file", str(document(tmp_path, {"title": ""})))
    assert edited.stdout.startswith("Draft saved with ") and "0 problems" not in edited.stdout
    assert edited.stdout.endswith(" problems. To publish it, run `huron publish meta`\n")
    invalid = ready.run("validate", "meta")
    assert invalid.exit_code == 7 and "/title" in invalid.stderr
    assert "the draft has " in invalid.stderr


def test_edit_meta_from_a_file_targets_a_named_collection(ready: Cli, tmp_path: Path) -> None:
    wanted = {"title": "Run eight", "description": "named"}
    ready.ok("edit", "meta", "solar-wind.run8", "--file", str(document(tmp_path, wanted)))
    run8 = json.loads(ready.ok("-o", "json", "describe", "collection", RUN8).stdout)
    assert ready.state.read_draft(str(run8["id"])) == wanted
    assert ready.state.read_draft(ready.config_current()) is None


def test_edit_meta_refuses_file_with_from_scratch(ready: Cli, tmp_path: Path) -> None:
    path = document(tmp_path, {"title": "x"})
    refused = ready.run("edit", "meta", "--file", str(path), "--from-scratch")
    assert refused.exit_code == 2
    assert "use `--file` or `--from-scratch`, not both" in refused.stderr
    assert ready.state.read_draft(ready.config_current()) is None


@pytest.mark.parametrize(
    ("content", "message"),
    [(None, "cannot read"), ("[1, 2]", "must hold a JSON object"), ("{not json", "cannot read")],
)
def test_edit_meta_refuses_an_unreadable_or_non_object_file(
    ready: Cli, tmp_path: Path, content: str | None, message: str
) -> None:
    path = tmp_path / "meta.json"
    if content is not None:
        path.write_text(content)
    refused = ready.run("edit", "meta", "--file", str(path))
    assert refused.exit_code == 2 and message in refused.stderr
    assert ready.state.read_draft(ready.config_current()) is None
