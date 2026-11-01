"""The STE check extracts user-facing strings, lints them and the docs, and fails on hard rules."""

from __future__ import annotations

import ast
import functools
import importlib.util
import json
import sys
import textwrap
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ste_check.py"
WORDS = frozenset({"checkout", "login", "pull", "validate", "meta", "adm", "provision-orgs"})
CLEAN = "Huron keeps raw data on the share.\n"


@functools.cache
def ste() -> ModuleType:
    """The script as a module; registered first, as its dataclasses need."""
    spec = importlib.util.spec_from_file_location("ste_check", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def expression(source: str) -> ast.expr:
    """One parsed expression."""
    return ast.parse(source, mode="eval").body


def module(source: str) -> ast.Module:
    """One parsed module."""
    return ast.parse(textwrap.dedent(source))


def write(root: Path, path: str, text: str) -> None:
    """Write a file of the fake repository."""
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(textwrap.dedent(text), encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository with clean text in every source the check reads."""
    for path in ste().DOCS:
        write(tmp_path, path, CLEAN)
    write(tmp_path, f"{ste().CLI_REFERENCE}/index.md", CLEAN)
    write(
        tmp_path,
        f"{ste().CLI_PACKAGE}/errors.py",
        "class CliError(Exception): ...\nclass UsageError(CliError): ...\n",
    )
    write(tmp_path, f"{ste().SOURCE_PACKAGE}/pkg/errors.py", "class HuronError(Exception): ...\n")
    write(tmp_path, ste().WEB_HINTS, "const hint = { title: 'Check out this collection' };\n")
    return tmp_path


def check(root: Path, *only: str, kept: tuple[Any, ...] = ()) -> Any:
    """Run the check on the fake repository."""
    return ste().check(root, WORDS, only, kept)


def places(report: Any) -> list[tuple[str, int, str, str]]:
    """The (path, line, rule, level) of each finding."""
    return [(f.path, f.line, f.rule, f.level) for f in report.findings]


# --- Extraction ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ('"plain text"', ["plain text"]),
        ('f"catalog {name} has {count} namespaces"', ["catalog X has X namespaces"]),
        ('"run " + command', ["run X"]),
        ('"a" if flag else f"b {c}"', ["a", "b X"]),
        ('"{} of {total}".format(a, total=b)', ["X of X"]),
        ('"%s is %(what)s" % values', ["X is X"]),
        ("message", []),
        ("42", []),
    ],
)
def test_literal_texts_keep_literals_and_neutralize_placeholders(
    source: str, expected: list[str]
) -> None:
    assert ste().literal_texts(expression(source)) == expected


def test_cli_texts_cover_help_messages_hints_output_and_prompts() -> None:
    tree = module(
        '''
        import typer

        app = typer.Typer(help="Manage the catalog.")
        PUSH_HINT = "push with: huron push"
        _HINTS = {"A": "run: huron pull", "B": f"run: huron {verb}"}
        OTHER = "not user-facing"


        class ProblemError(UsageError):
            def __init__(self) -> None:
                super().__init__("the problem", hint="fix it")


        @app.command("show")
        def show(name: str = typer.Option(None, help="The name.")) -> None:
            """Show one thing.

            More detail on a second paragraph.
            """
            say(ctx, f"shown {name}")
            found.err.print("warning: slow")
            found.out.print("table output")
            found.prompter.confirm("Delete it?")
            raise UsageError("bad input", hint="run: huron checkout <identifier>")


        def helper() -> None:
            """Not a command, so not help text."""
            log("internal")
        '''
    )
    errors = frozenset({"CliError", "UsageError", "ProblemError"})
    found = {(text.line, text.text) for text in ste().cli_texts("cli.py", tree, errors)}
    assert found == {
        (4, "Manage the catalog."),
        (5, "push with: huron push"),
        (6, "run: huron pull"),
        (6, "run: huron X"),
        (12, "the problem"),
        (12, "fix it"),
        (16, "The name."),
        (17, "Show one thing.\n\nMore detail on a second paragraph."),
        (21, "shown X"),
        (22, "warning: slow"),
        (24, "Delete it?"),
        (25, "bad input"),
        (25, "run: huron checkout <identifier>"),
    }


def test_subclasses_follow_the_inheritance_chain_across_modules() -> None:
    first = module("class HuronError(Exception): ...\nclass NotFound(HuronError): ...\n")
    second = module("class Missing(NotFound): ...\nclass Unrelated(ValueError): ...\n")
    assert ste().subclasses([first, second], "HuronError") == {"HuronError", "NotFound", "Missing"}


def test_error_texts_read_calls_super_init_and_default_messages() -> None:
    tree = module(
        """
        class NotLoggedIn(CliError):
            def __init__(self, message: str = "you are not logged in") -> None:
                super().__init__(message, 3, hint="run: huron login")


        def find(name):
            raise NotFound(f"catalog {name!r} not found", {"name": name})
            raise ValueError("not a user-facing error")
        """
    )
    errors = frozenset({"CliError", "NotLoggedIn", "NotFound"})
    found = {(text.line, text.text) for text in ste().error_texts("e.py", tree, errors)}
    assert found == {
        (3, "you are not logged in"),
        (4, "run: huron login"),
        (8, "catalog X not found"),
    }


def test_triple_quoted_text_maps_each_line_to_its_source_line() -> None:
    tree = module(
        '''
        @app.command()
        def drift() -> None:
            """Report drift.

            Checks run first; the rest follows.
            """
        '''
    )
    (text,) = ste().cli_texts("adm.py", tree, frozenset({"CliError"}))
    source = ste().string_source("cli", "adm.py", [text], WORDS)
    report = [
        ste().finding_of(source, item, strict=True)
        for item in ste().linter().lint(source.markdown)[0]
    ]
    assert [(f.line, f.rule) for f in report] == [(6, "semicolon")]


def test_web_texts_read_typescript_and_svelte_hint_titles() -> None:
    typescript = "const a = [\n  { title: 'Check out this collection', command: x },\n];\n"
    svelte = (
        '<p>x</p>\n<CliHint\n\ttitle="Search this catalog"\n\tcommand={c}\n/>\n'
        '<Other title="no" />\n'
    )
    assert [(t.line, t.text) for t in ste().web_texts("cli.ts", typescript)] == [
        (2, "Check out this collection")
    ]
    assert [(t.line, t.text) for t in ste().web_texts("page.svelte", svelte)] == [
        (3, "Search this catalog")
    ]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("run: huron pull", "run: `huron pull`"),
        (
            "run: huron checkout <identifier>, or huron checkout to pick one",
            "run: `huron checkout <identifier>`, or `huron checkout` to pick one",
        ),
        ('push with: huron push -m "<message>"', 'push with: `huron push -m "<message>"`'),
        ("prepare them (huron adm provision-orgs)", "prepare them (`huron adm provision-orgs`)"),
        ("use --org X or groups.<role>", "use `--org` X or groups.`<role>`"),
        ("already `huron pull` here", "already `huron pull` here"),
        ("the Huron share", "the Huron share"),
    ],
)
def test_mark_code_marks_command_lines_flags_and_placeholders(text: str, expected: str) -> None:
    assert ste().mark_code(text, WORDS | {"push"}) == expected


# --- The check -------------------------------------------------------------------------------


def test_clean_repository_passes(repo: Path) -> None:
    report = check(repo)
    assert report.findings == []
    assert report.stale == []


def test_hard_violations_are_reported_at_their_source_lines(repo: Path) -> None:
    write(repo, "docs/operator.md", "# Operator\n\nStart the API; then start the web.\n")
    write(
        repo,
        f"{ste().CLI_PACKAGE}/commands/sync.py",
        """
        def push():
            raise UsageError(
                "nothing to push; stage files first",
            )
        """,
    )
    write(repo, ste().WEB_HINTS, "const h = [\n  { title: 'Grant a role; apply ACLs' },\n];\n")
    report = check(repo)
    assert places(report) == [
        ("docs/operator.md", 3, "semicolon", "hard"),
        (f"{ste().CLI_PACKAGE}/commands/sync.py", 4, "semicolon", "hard"),
        (ste().WEB_HINTS, 2, "semicolon", "hard"),
    ]
    assert report.areas() == {
        "api": {"hard": 0, "advisory": 0, "kept": 0},
        "cli": {"hard": 1, "advisory": 0, "kept": 0},
        "cli-reference": {"hard": 0, "advisory": 0, "kept": 0},
        "docs": {"hard": 1, "advisory": 0, "kept": 0},
        "web": {"hard": 1, "advisory": 0, "kept": 0},
    }


def test_huron_error_messages_are_checked_under_the_api_area(repo: Path) -> None:
    write(
        repo,
        f"{ste().SOURCE_PACKAGE}/pkg/errors.py",
        "class HuronError(Exception): ...\nclass NotFound(HuronError): ...\n",
    )
    write(repo, f"{ste().SOURCE_PACKAGE}/core/lake.py", 'raise NotFound("gone; ask again")\n')
    assert [(f.area, f.path, f.line) for f in check(repo).findings] == [
        ("api", f"{ste().SOURCE_PACKAGE}/core/lake.py", 1)
    ]


def test_long_sentence_fails(repo: Path) -> None:
    sentence = " ".join(["word"] * 30) + "."
    write(repo, "docs/user-guide.md", f"{sentence}\n")
    assert places(check(repo)) == [("docs/user-guide.md", 1, "long-sentence", "hard")]


def test_advisory_findings_do_not_fail(repo: Path) -> None:
    write(repo, "docs/user-guide.md", "The file is deleted by the service.\n")
    report = check(repo)
    assert places(report) == [("docs/user-guide.md", 1, "passive-voice", "advisory")]
    assert report.hard == []


def test_synonym_rotation_is_advisory_in_prose_and_hard_in_strict_text(repo: Path) -> None:
    rotation = "Check the file.\n\nVerify the copy.\n"
    write(repo, "docs/user-guide.md", rotation)
    write(repo, f"{ste().CLI_REFERENCE}/index.md", rotation)
    write(
        repo,
        "docs/api-errors.md",
        "Verify the code first.\n\n| Code | Meaning |\n| --- | --- |\n"
        "| `A` | Check the input. |\n| `B` | Confirm the input. |\n",
    )
    # Between prose and a row the rotation is advisory. Between two rows it is hard.
    assert places(check(repo)) == [
        ("docs/user-guide.md", 3, "synonym-rotation", "advisory"),
        ("docs/api-errors.md", 5, "synonym-rotation", "advisory"),
        ("docs/api-errors.md", 6, "synonym-rotation", "hard"),
        (f"{ste().CLI_REFERENCE}/index.md", 3, "synonym-rotation", "hard"),
    ]


def test_command_names_in_headings_are_code(repo: Path) -> None:
    write(repo, f"{ste().CLI_REFERENCE}/validate.md", "## huron validate meta\n\nCheck a draft.\n")
    assert check(repo).findings == []


def test_mdx_imports_are_not_prose(repo: Path) -> None:
    path = "web/docs-site/src/content/docs/index.mdx"
    write(repo, path, "---\ntitle: Huron\n---\n\nimport { Card } from 'x';\n\n<Card />\n")
    assert check(repo).findings == []


def test_kept_entries_stay_and_stale_entries_fail(repo: Path) -> None:
    write(repo, "docs/operator.md", "Mount the share; then start.\n")
    kept = ste().Kept("docs/operator.md", "semicolon", "Mount the share", "precision")
    stale = ste().Kept("docs/operator.md", "long-sentence", "gone", "precision")
    report = check(repo, kept=(kept, stale))
    assert [f.kept for f in report.findings] == ["precision"]
    assert report.hard == []
    assert report.stale == [stale]


def test_paths_limit_the_check(repo: Path) -> None:
    write(repo, "docs/operator.md", "Mount the share; then start.\n")
    write(repo, "docs/user-guide.md", "Log in; then push.\n")
    assert [f.path for f in check(repo, "docs/user-guide.md").findings] == ["docs/user-guide.md"]


def test_main_prints_json_and_exits_1_on_a_hard_violation(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    write(repo, "docs/operator.md", "Mount the share; then start.\n")
    monkeypatch.setattr(ste(), "ROOT", repo)
    monkeypatch.setattr(ste(), "command_words", lambda: WORDS)
    assert ste().main(["--json"]) == 1
    document = json.loads(capsys.readouterr().out)
    assert document["hard"] == 1
    assert document["areas"]["docs"] == {"hard": 1, "advisory": 0, "kept": 0}
    assert document["findings"][0]["rule"] == "semicolon"
    assert ste().main(["docs/user-guide.md"]) == 0
    assert "ste_check: no hard violations." in capsys.readouterr().out


def test_readable_output_names_the_place_and_the_rule(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    write(repo, "docs/operator.md", "Mount the share; then start.\n\nThe file is moved.\n")
    monkeypatch.setattr(ste(), "ROOT", repo)
    monkeypatch.setattr(ste(), "command_words", lambda: WORDS)
    assert ste().main([]) == 1
    out = capsys.readouterr().out
    assert "docs/operator.md:1:16 semicolon:" in out
    assert "passive-voice" not in out
    assert ste().main(["--advisory"]) == 1
    assert "docs/operator.md:3:10 passive-voice (advisory):" in capsys.readouterr().out


def test_command_words_come_from_the_cli() -> None:
    words = ste().command_words()
    assert {"checkout", "push", "provision-orgs", "meta"} <= words
