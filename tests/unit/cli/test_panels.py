"""The root help: its panels, their order and the verbs in each."""

import re

import pytest

from huron.applications.cli.commands import LAYOUT, PANEL_OF, PANELS, VERBS
from tests.support.cli import Cli

EXPECTED = (
    ("Catalog", ("org", "catalog", "get", "describe", "tree", "search", "checkout")),
    (
        "Collection",
        ("status", "add", "rm", "pull", "push", "edit", "validate", "publish", "activate"),
    ),
    ("Manage", ("create", "delete", "set", "unset")),
    ("Administration", ("adm",)),
    ("Settings", ("login", "logout", "whoami", "config")),
)
PANEL_TITLE = re.compile(r"^╭─ (.+?) ─+╮$", re.MULTILINE)


def root_help(cli: Cli, capsys: pytest.CaptureFixture[str]) -> str:
    capsys.readouterr()
    assert cli.run("--help").exit_code == 0
    return capsys.readouterr().out


def panels_of(text: str) -> list[tuple[str, tuple[str, ...]]]:
    """Each boxed panel's title and the verbs listed in it, in the order help prints them."""
    found = []
    for title, body in zip(
        PANEL_TITLE.findall(text), re.split(PANEL_TITLE, text)[2::2], strict=True
    ):
        found.append((title, tuple(re.findall(r"^│ (\S+)\s", body, re.MULTILINE))))
    return found


def test_root_help_lists_exactly_the_five_verb_panels_in_order(
    cli: Cli, capsys: pytest.CaptureFixture[str]
) -> None:
    shown = panels_of(root_help(cli, capsys))
    assert shown[0][0] == "Options"
    assert shown[1:] == list(EXPECTED)


def test_the_old_panels_are_gone(cli: Cli, capsys: pytest.CaptureFixture[str]) -> None:
    text = root_help(cli, capsys)
    for title in ("Context", "Basic Commands", "Working Copy", "Create and Change", "Commands"):
        assert f"─ {title} ─" not in text, title


def test_the_layout_is_the_single_source_of_order_and_panels() -> None:
    assert LAYOUT == EXPECTED
    assert PANELS == ("Catalog", "Collection", "Manage", "Administration", "Settings")
    assert tuple(verb for _, verbs in EXPECTED for verb in verbs) == VERBS
    assert len(set(VERBS)) == len(VERBS)
    assert PANEL_OF["checkout"] == "Catalog" and PANEL_OF["activate"] == "Collection"
    assert PANEL_OF["set"] == PANEL_OF["unset"] == "Manage"


def test_command_spellings_are_unchanged(cli: Cli) -> None:
    for verb in ("org", "catalog", "status", "checkout", "edit", "activate", "set", "unset"):
        assert cli.run(verb, "--help").exit_code == 0, verb
