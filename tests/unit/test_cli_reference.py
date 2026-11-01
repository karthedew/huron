"""The CLI reference generator documents every visible command and keeps its pages current."""

from __future__ import annotations

import functools
import importlib.util
import json
import re
import sys
from enum import Enum
from pathlib import Path
from types import ModuleType
from typing import Annotated

import pytest
import typer

from huron.applications.cli.commands import LAYOUT

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "cli_reference.py"


class Colour(Enum):
    """A choice option's values."""

    RED = "red"
    BLUE = "blue"


@functools.cache
def generator() -> ModuleType:
    """The script as a module; registered first, as its dataclasses need."""
    spec = importlib.util.spec_from_file_location("cli_reference", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def sample_app() -> typer.Typer:
    """A small CLI with a group, a hidden alias, a hidden option and every kind of parameter."""
    sample = typer.Typer(help="A sample tool.")
    things = typer.Typer(help="Work with things.")

    @things.command("list", rich_help_panel="Reading")
    def list_things(
        colour: Annotated[Colour, typer.Option("--colour", "-c", help="The <colour> * to use")] = (
            Colour.RED
        ),
        everything: Annotated[bool, typer.Option("--all", "-A", help="Every ``thing``.")] = False,
        secret: Annotated[str, typer.Option(hidden=True)] = "",
        token: Annotated[str | None, typer.Option(envvar="SAMPLE_TOKEN")] = None,
    ) -> None:
        """List things | all of them.

        Second paragraph [with brackets].
        """

    things.command("thing", hidden=True)(list_things)

    @things.command("add", rich_help_panel="Writing")
    def add(
        name: Annotated[str, typer.Argument(help="The new thing")],
        paths: Annotated[list[str] | None, typer.Argument(help="Its files.")] = None,
        count: Annotated[int, typer.Option(help="How many.")] = 1,
        label: Annotated[str, typer.Option(help="A label.")] = "",
        shared: Annotated[bool, typer.Option("--shared/--private", help="Who sees it.")] = False,
        loud: Annotated[bool, typer.Option("--loud/--quiet", help="How it says so.")] = True,
    ) -> None:
        """Add a thing."""

    @sample.command("hello")
    def hello() -> None:
        """Say hello."""

    sample.add_typer(things, name="things")
    return sample


SAMPLE_LAYOUT = (("Basics", ("hello",)), ("Things", ("things",)))


def sample_page(name: str) -> str:
    """One generated page of the sample CLI."""
    cli_reference = generator()
    return str(cli_reference.pages(cli_reference.tree(sample_app(), "sample"), SAMPLE_LAYOUT)[name])


def test_the_committed_reference_matches_the_cli() -> None:
    cli_reference = generator()
    files = cli_reference.pages(cli_reference.tree())
    assert cli_reference.differences(files, cli_reference.OUTPUT) == []


def test_every_verb_of_the_layout_has_a_page_and_every_panel_an_index() -> None:
    cli_reference = generator()
    files = cli_reference.pages(cli_reference.tree())
    verbs = [verb for _, panel_verbs in LAYOUT for verb in panel_verbs]
    assert {f"{verb}.md" for verb in verbs} <= set(files)
    panels = [cli_reference.slug(panel) for panel, _ in LAYOUT]
    assert {f"panels/{panel}.md" for panel in panels} <= set(files)
    sidebar = json.loads(files["_sidebar.json"])
    assert [group["label"] for group in sidebar[1:]] == [panel for panel, _ in LAYOUT]
    assert [item["label"] for item in sidebar[1]["items"][1:]] == list(LAYOUT[0][1])


def test_the_real_reference_omits_hidden_aliases() -> None:
    cli_reference = generator()
    page = cli_reference.pages(cli_reference.tree())["get.md"]
    assert "## `huron get orgs`\n" in page
    assert "## `huron get org`\n" not in page
    assert "`--all-orgs`, `-A`" in page


def test_a_group_page_lists_subcommands_by_panel_with_their_parameters() -> None:
    page = sample_page("things.md")
    assert page.startswith("---\ntitle: sample things\ndescription: Work with things.\n")
    assert "sidebar:\n  label: things\n" in page
    assert "Panel: [Things](/docs/reference/cli/panels/things/)." in page
    assert page.index("**Reading**") < page.index("**Writing**")
    assert "[`sample things list`](#sample-things-list)" in page
    assert "## `sample things thing`" not in page
    assert "```text\nsample things add [OPTIONS] NAME [PATHS...]\n```" in page
    assert re.search(r"\| `NAME` +\| str +\| The new thing\. Required\. +\|", page)
    assert "Its files. Takes any number of values." in page
    assert re.search(r"\| `--count` +\| int +\| `1` +\| How many\. +\|", page)


def test_defaults_read_as_help_shows_them() -> None:
    page = sample_page("things.md")
    assert "``" not in page.replace("```", "")
    assert re.search(r"\| `--label` +\| str +\| +\| A label\. +\|", page)
    assert re.search(r"\| `--shared` / `--private` +\| boolean +\| `private` +\|", page)
    assert re.search(r"\| `--loud` / `--quiet` +\| boolean +\| `loud` +\|", page)


def test_options_show_names_types_defaults_and_escaped_help() -> None:
    page = sample_page("things.md")
    assert "`--colour`, `-c`" in page
    assert "red \\| blue" in page
    assert "`red`" in page
    assert "The &lt;colour&gt; \\* to use." in page
    assert re.search(r"\| `--all`, `-A` +\| flag +\| +\| Every `thing`\. +\|", page)
    assert "Every `thing`." in page
    assert "Environment: `SAMPLE_TOKEN`." in page
    assert "--secret" not in page
    assert "List things \\| all of them." in page
    assert "Second paragraph \\[with brackets\\]." in page


def test_tables_are_padded_to_equal_widths() -> None:
    page = sample_page("things.md")
    tables = [block for block in page.split("\n\n") if block.startswith("| ")]
    assert tables
    for table in tables:
        assert len({len(line) for line in table.splitlines()}) == 1


def test_the_overview_lists_global_options_and_every_panel() -> None:
    cli_reference = generator()
    files = cli_reference.pages(cli_reference.tree())
    overview = files["index.md"]
    assert "## Global options" in overview
    assert "`--output`, `-o`" in overview
    for panel, _ in LAYOUT:
        assert f"### [{panel}](/docs/reference/cli/panels/{cli_reference.slug(panel)}/)" in overview


@pytest.mark.parametrize(
    ("layout", "message"),
    [
        ((("Basics", ("hello",)),), r"leaves out \['things'\]"),
        ((("Basics", ("hello", "things", "gone")),), r"missing commands \['gone'\]"),
    ],
)
def test_a_layout_that_disagrees_with_the_cli_is_refused(
    layout: tuple[tuple[str, tuple[str, ...]], ...], message: str
) -> None:
    cli_reference = generator()
    with pytest.raises(ValueError, match=message):
        cli_reference.pages(cli_reference.tree(sample_app(), "sample"), layout)


def test_write_replaces_stale_pages_and_differences_reports_them(tmp_path: Path) -> None:
    cli_reference = generator()
    files = {"a.md": "one\n", "panels/b.md": "two\n", "_sidebar.json": "[]\n"}
    (tmp_path / "old.md").write_text("gone\n")
    (tmp_path / "panels").mkdir()
    (tmp_path / "panels" / "extra.mdx").write_text("stray\n")
    (tmp_path / "notes.txt").write_text("stray\n")
    assert cli_reference.differences(files, tmp_path) == [
        "_sidebar.json",
        "a.md",
        "notes.txt",
        "old.md",
        "panels/b.md",
        "panels/extra.mdx",
    ]
    cli_reference.write(files, tmp_path)
    assert cli_reference.differences(files, tmp_path) == []
    assert not (tmp_path / "old.md").exists()
    assert not (tmp_path / "panels" / "extra.mdx").exists()
    assert not (tmp_path / "notes.txt").exists()
    assert (tmp_path / "panels" / "b.md").read_text() == "two\n"


def test_check_fails_on_stale_pages_with_a_hint_and_passes_once_written(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cli_reference = generator()
    assert cli_reference.main(["--check", "--output", str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert "stale:" in err
    assert "hint: run `uv run python scripts/cli_reference.py`" in err
    assert cli_reference.main(["--output", str(tmp_path)]) == 0
    assert cli_reference.main(["--check", "--output", str(tmp_path)]) == 0
    assert (tmp_path / "checkout.md").exists()


def test_slug_matches_heading_anchors() -> None:
    cli_reference = generator()
    assert cli_reference.slug("huron adm apply-acl") == "huron-adm-apply-acl"
    assert cli_reference.slug("Reading `huron adm check`") == "reading-huron-adm-check"
    assert cli_reference.slug("Administration") == "administration"
