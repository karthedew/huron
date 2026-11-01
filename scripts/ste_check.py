"""Check Huron's user-facing English against the ASD-STE100 rules of the project's writing skill.

Runs the skill's linter (``.claude/skills/asd-ste100/scripts/ste-lint.py``) over two kinds of text:

1. Documentation: the user guide, the operator guide, the API error reference, the hand-written
   pages of the docs site and the generated CLI reference pages.
2. Strings extracted from code with ``ast`` and regular expressions:

   - The help text of the CLI: Typer command docstrings and ``help=``.
   - The messages of the CLI: ``CliError`` and its subclasses, ``hint=``, ``say()``,
     ``err.print()``, prompts and ``*_HINT`` constants.
   - The messages of ``HuronError`` subclasses under ``src/huron``.
   - The titles of the web's CLI hints.

   Each string is one Markdown paragraph. An f-string keeps its literal parts and puts ``X`` for
   each placeholder. ``huron`` command lines, flags and ``<placeholder>`` names are code, not prose.

Two modes, as the skill defines them. STRICT text (code strings, CLI reference pages and the rows
of the API error table) fails on every hard rule. STE-FLAVORED text (documentation prose) fails on
the structural rules only: the lexical rule synonym-rotation is advisory there. Advisory findings
(passive voice, compound tenses) never fail the check.

A sentence that must stay longer to keep its precision goes into ``KEPT`` with the reason. A
``KEPT`` entry that matches no finding fails the check, so the list cannot go stale.

Usage: ``uv run python scripts/ste_check.py [--json] [--advisory] [PATH ...]``. A PATH limits the
check to the sources at or under it. Exit 1 when a hard violation remains, 2 on a usage error.
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import inspect
import json
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence
    from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
LINTER = ROOT / ".claude" / "skills" / "asd-ste100" / "scripts" / "ste-lint.py"

STRICT = "strict"
# The areas of the report: documentation, generated CLI reference, CLI strings, error messages of
# the service, and the web's CLI hint titles.
AREAS = ("docs", "cli-reference", "cli", "api", "web")
FLAVORED = "ste-flavored"

DOCS = (
    "docs/user-guide.md",
    "docs/operator.md",
    "docs/api-errors.md",
    "web/docs-site/src/content/docs/index.mdx",
    "web/docs-site/src/content/docs/getting-started.md",
)
# Rows of these Markdown tables are strict text inside STE-flavored documentation.
STRICT_TABLES = frozenset({"docs/api-errors.md"})
CLI_REFERENCE = "web/docs-site/src/content/docs/reference/cli"
CLI_PACKAGE = "src/huron/applications/cli"
SOURCE_PACKAGE = "src/huron"
WEB_HINTS = "web/src/lib/cli.ts"
WEB_SOURCE = "web/src"

# The neutral word for an f-string placeholder.
PLACEHOLDER = "X"
LEXICAL_RULES = frozenset({"synonym-rotation"})
HINT_NAME = re.compile(r"^_?[A-Z0-9_]*HINTS?$")
HELP_KEYWORDS = frozenset({"help", "short_help", "epilog"})
PROMPT_METHODS = frozenset({"confirm", "text", "select"})
# Typer and Click decorators whose function docstring is help text.
COMMAND_DECORATORS = frozenset({"command", "callback"})

TS_TITLE = re.compile(r"""\btitle:\s*'((?:[^'\\\n]|\\.)*)'""")
SVELTE_HINT_TITLE = re.compile(r'<CliHint\b[^>]*?\btitle="([^"]*)"')
MDX_ESM = re.compile(r"^(?:import|export)\s")
HEADING = re.compile(r"^ {0,3}#{1,6}\s")
# A word token, a quoted argument or a run of other characters.
SHELL_TOKEN = re.compile(r"\"[^\"]*\"|'[^']*'|\S+")
FLAG = re.compile(r"^-{1,2}[A-Za-z][\w-]*(?:=\S+)?$")
ANGLE = re.compile(r"<[A-Za-z][\w.\-]*>…?")
# An identifier, path or value: one token with a dot, slash, equals sign or underscore.
OPERAND = re.compile(r"^[\w.\-/=@*…]*[./=_][\w.\-/=@*…]*$")
TRAILING = ",;:.)]"
OPENERS = "(["
PROGRAM = "huron"


@dataclass(frozen=True)
class Kept:
    """A finding that stays because a shorter form would drop precision."""

    path: str
    rule: str
    text: str
    reason: str


# Each entry names the source, the rule, and a piece of the line that holds the finding.
KEPT: tuple[Kept, ...] = ()


@dataclass(frozen=True)
class Text:
    """One user-facing string from code, with the source line of its first line."""

    path: str
    line: int
    text: str
    # True when each line of the text is on its own source line (a triple-quoted string).
    tracks_lines: bool = False


@dataclass(frozen=True)
class Source:
    """One unit the linter reads: a document, or the strings of one file in one area."""

    area: str
    path: str
    mode: str
    markdown: str
    # The source line of each Markdown line, for strings extracted from code.
    lines: tuple[int, ...] | None = None
    strict_table: bool = False


@dataclass
class Finding:
    """One linter finding, mapped back to its source."""

    area: str
    path: str
    line: int
    col: int
    rule: str
    level: str
    match: str
    message: str
    excerpt: str
    kept: str | None = field(default=None)

    @property
    def hard(self) -> bool:
        """Whether this finding fails the check."""
        return self.level == "hard" and self.kept is None


@cache
def linter() -> ModuleType:
    """The vendored ste-lint.py as a module."""
    spec = importlib.util.spec_from_file_location("ste_lint", LINTER)
    if spec is None or spec.loader is None:
        raise SystemExit(f"ste_check: cannot load {LINTER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- Text from expressions -------------------------------------------------------------------


def literal_texts(node: ast.expr | None) -> list[str]:
    """The literal strings an expression can produce, with ``X`` for each value from code.

    Returns an empty list when the expression holds no string literal.
    """
    if node is None:
        return []
    if isinstance(node, ast.Constant):
        return [node.value] if isinstance(node.value, str) else []
    if isinstance(node, ast.JoinedStr):
        parts = [
            part.value if isinstance(part, ast.Constant) else PLACEHOLDER for part in node.values
        ]
        return ["".join(str(part) for part in parts)]
    if isinstance(node, ast.IfExp):
        return literal_texts(node.body) + literal_texts(node.orelse)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = literal_texts(node.left), literal_texts(node.right)
        if not left and not right:
            return []
        return [a + b for a in left or [PLACEHOLDER] for b in right or [PLACEHOLDER]]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
        return [
            re.sub(r"%(?:\([^)]*\))?[-#0 +]*\d*(?:\.\d+)?[sdrfx]", PLACEHOLDER, text)
            for text in literal_texts(node.left)
        ]
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "format"
    ):
        return [re.sub(r"\{[^{}]*\}", PLACEHOLDER, text) for text in literal_texts(node.func.value)]
    return []


def texts_of(path: str, node: ast.expr | None) -> list[Text]:
    """The literal strings of an expression as texts of ``path``."""
    if node is None:
        return []
    tracks = (node.end_lineno or node.lineno) > node.lineno
    found = []
    for value in literal_texts(node):
        text, lead = clean(value)
        if text:
            found.append(Text(path, node.lineno + lead, text, tracks and "\n" in text))
    return found


def clean(value: str) -> tuple[str, int]:
    """The text of a string as a reader sees it, and the number of blank lines removed before it.

    Removes the common indentation of a triple-quoted string and Click's no-rewrap marker.
    """
    value = value.replace("\b", "")
    lines = value.expandtabs().split("\n")
    lead = 0
    while lead < len(lines) - 1 and not lines[lead].strip():
        lead += 1
    return inspect.cleandoc(value).strip(), lead


def name_of(node: ast.expr) -> str | None:
    """The last name of a ``Name`` or ``Attribute`` expression."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def keyword(call: ast.Call, name: str) -> ast.expr | None:
    """The value of keyword ``name`` in a call."""
    return next((item.value for item in call.keywords if item.arg == name), None)


def argument(call: ast.Call, index: int, name: str) -> ast.expr | None:
    """Argument ``index`` of a call, given by position or as keyword ``name``."""
    if len(call.args) > index and not isinstance(call.args[index], ast.Starred):
        return call.args[index]
    return keyword(call, name)


def subclasses(trees: Iterable[ast.Module], base: str) -> frozenset[str]:
    """The names of ``base`` and of every class that derives from it in ``trees``."""
    bases: dict[str, set[str]] = {}
    for tree in trees:
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                names = {name_of(item) for item in node.bases}
                bases.setdefault(node.name, set()).update(n for n in names if n)
    found = {base}
    grew = True
    while grew:
        grew = False
        for name, parents in bases.items():
            if name not in found and parents & found:
                found.add(name)
                grew = True
    return frozenset(found)


def is_super_init(call: ast.Call) -> bool:
    """Whether a call is ``super().__init__(...)``."""
    func = call.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "__init__"
        and isinstance(func.value, ast.Call)
        and name_of(func.value.func) == "super"
    )


def error_texts(path: str, tree: ast.Module, errors: frozenset[str]) -> list[Text]:
    """The messages and hints passed to the error classes ``errors`` in one module."""
    found: list[Text] = []
    for cls in (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)):
        if cls.name not in errors:
            continue
        for init in cls.body:
            if isinstance(init, ast.FunctionDef) and init.name == "__init__":
                found.extend(default_texts(path, init.args, ("message", "hint")))
                for call in (node for node in ast.walk(init) if isinstance(node, ast.Call)):
                    if is_super_init(call):
                        found.extend(texts_of(path, argument(call, 0, "message")))
                        found.extend(texts_of(path, keyword(call, "hint")))
    for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
        if name_of(call.func) in errors:
            found.extend(texts_of(path, argument(call, 0, "message")))
            found.extend(texts_of(path, keyword(call, "hint")))
    return found


def default_texts(path: str, args: ast.arguments, names: Sequence[str]) -> list[Text]:
    """The string defaults of the parameters ``names``."""
    positional = args.posonlyargs + args.args
    pairs = list(
        zip(positional[len(positional) - len(args.defaults) :], args.defaults, strict=True)
    )
    pairs += [
        (arg, default)
        for arg, default in zip(args.kwonlyargs, args.kw_defaults, strict=True)
        if default is not None
    ]
    return [text for arg, default in pairs if arg.arg in names for text in texts_of(path, default)]


def cli_texts(path: str, tree: ast.Module, errors: frozenset[str]) -> list[Text]:
    """The help text and the messages of one CLI module."""
    found = error_texts(path, tree, errors)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and is_command(node):
            docstring = node.body[0] if node.body else None
            if isinstance(docstring, ast.Expr):
                found.extend(texts_of(path, docstring.value))
        elif isinstance(node, ast.Call):
            found.extend(call_texts(path, node))
    for statement in tree.body:
        targets: list[ast.expr] = []
        if isinstance(statement, ast.Assign):
            targets = statement.targets
        elif isinstance(statement, ast.AnnAssign):
            targets = [statement.target]
        names = [name_of(target) for target in targets]
        value = getattr(statement, "value", None)
        if value is not None and any(name and HINT_NAME.match(name) for name in names):
            values = value.values if isinstance(value, ast.Dict) else [value]
            for item in values:
                found.extend(texts_of(path, item))
    return found


def is_command(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Whether a function is a Typer command or callback, so its docstring is help text."""
    for decorator in function.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Attribute) and target.attr in COMMAND_DECORATORS:
            return True
    return False


def call_texts(path: str, call: ast.Call) -> list[Text]:
    """The help text, output lines and prompts one call passes."""
    found: list[Text] = []
    for item in call.keywords:
        if item.arg in HELP_KEYWORDS:
            found.extend(texts_of(path, item.value))
    func = call.func
    if isinstance(func, ast.Name) and func.id == "say":
        found.extend(texts_of(path, argument(call, 1, "message")))
    elif isinstance(func, ast.Attribute):
        receiver = name_of(func.value) or ""
        printed = func.attr == "print" and receiver == "err"
        prompted = func.attr in PROMPT_METHODS and receiver.endswith("prompter")
        if printed or prompted:
            found.extend(texts_of(path, argument(call, 0, "message")))
    return found


def web_texts(path: str, source: str) -> list[Text]:
    """The CLI hint titles of one web file: ``title: '...'`` in TypeScript, ``<CliHint title>``."""
    pattern = TS_TITLE if path.endswith(".ts") else SVELTE_HINT_TITLE
    found = []
    for match in pattern.finditer(source):
        line = source.count("\n", 0, match.start(1)) + 1
        text = match.group(1).replace("\\'", "'")
        if text.strip():
            found.append(Text(path, line, text.strip()))
    return found


# --- Code and placeholders in extracted strings -----------------------------------------------


def mark_code(text: str, words: frozenset[str]) -> str:
    """Put backticks around the code in a string: command lines, flags and placeholders.

    A command line is ``huron`` and the tokens after it that are command words, flags, quoted
    arguments, placeholders or identifiers. The first other word ends it. Text that is already in
    a code span stays as it is.
    """
    spans: list[tuple[int, int]] = []
    tokens = list(SHELL_TOKEN.finditer(text))
    index = 0
    while index < len(tokens):
        raw = tokens[index].group()
        index += 1
        if raw.lstrip(OPENERS) != PROGRAM:
            token = raw.lstrip(OPENERS).rstrip(TRAILING)
            if FLAG.match(token) or ANGLE.fullmatch(token):
                start = tokens[index - 1].start() + raw.index(token)
                spans.append((start, start + len(token)))
            continue
        start = tokens[index - 1].end() - len(PROGRAM)
        end = tokens[index - 1].end()
        while index < len(tokens):
            raw = tokens[index].group()
            token = raw.rstrip(TRAILING)
            if not token or not is_command_token(token, words):
                break
            end = tokens[index].start() + len(token)
            index += 1
            if token != raw:
                break
        spans.append((start, end))
    spans += [
        match.span()
        for match in ANGLE.finditer(text)
        if not any(a <= match.start() < b for a, b in spans)
    ]
    code = [match.span() for match in re.finditer(r"`[^`]*`", text)]
    out, position = [], 0
    for start, end in sorted(spans):
        if start < position or any(a <= start < b for a, b in code):
            continue
        out += [text[position:start], "`", text[start:end], "`"]
        position = end
    out.append(text[position:])
    return "".join(out)


def is_command_token(token: str, words: frozenset[str]) -> bool:
    """Whether a token after ``huron`` still belongs to the command line."""
    return (
        token in words
        or token == PLACEHOLDER
        or token[:1] in "\"'"
        or bool(FLAG.match(token) or ANGLE.fullmatch(token) or OPERAND.match(token))
    )


@cache
def command_words() -> frozenset[str]:
    """The names of every command and command group of the ``huron`` CLI."""
    import typer.main

    from huron.applications.cli.app import app

    words: set[str] = set()
    stack: list[Any] = [typer.main.get_command(app)]
    while stack:
        commands = getattr(stack.pop(), "commands", None) or {}
        for name, command in commands.items():
            words.add(name)
            stack.append(command)
    return frozenset(words)


# --- Sources ---------------------------------------------------------------------------------


def string_source(area: str, path: str, texts: Sequence[Text], words: frozenset[str]) -> Source:
    """One Markdown document of the strings of one file: a paragraph per string."""
    lines: list[str] = []
    origins: list[int] = []
    for text in texts:
        if lines:
            lines.append("")
            origins.append(text.line)
        for offset, line in enumerate(mark_code(text.text, words).split("\n")):
            lines.append(line)
            origins.append(text.line + offset if text.tracks_lines else text.line)
    return Source(area, path, STRICT, "\n".join(lines) + "\n", tuple(origins))


def read(root: Path, path: str) -> str:
    """A repository file's text."""
    return (root / path).read_text(encoding="utf-8")


def python_files(root: Path, package: str) -> list[str]:
    """The Python files of a package, as repository paths."""
    return sorted(p.relative_to(root).as_posix() for p in (root / package).rglob("*.py"))


def sources(root: Path, words: frozenset[str]) -> Iterator[Source]:
    """Every source the check reads."""
    for path in DOCS:
        text = markdown(read(root, path), words, mdx=path.endswith(".mdx"))
        yield Source("docs", path, FLAVORED, text, strict_table=path in STRICT_TABLES)
    for page in sorted((root / CLI_REFERENCE).rglob("*.md")):
        text = markdown(page.read_text(encoding="utf-8"), words)
        yield Source("cli-reference", page.relative_to(root).as_posix(), STRICT, text)
    trees = {path: ast.parse(read(root, path), path) for path in python_files(root, SOURCE_PACKAGE)}
    cli = {path: tree for path, tree in trees.items() if path.startswith(CLI_PACKAGE + "/")}
    cli_errors = subclasses(cli.values(), "CliError")
    for path, tree in cli.items():
        if texts := cli_texts(path, tree, cli_errors):
            yield string_source("cli", path, unique(texts), words)
    huron_errors = subclasses(trees.values(), "HuronError")
    for path, tree in trees.items():
        if texts := error_texts(path, tree, huron_errors):
            yield string_source("api", path, unique(texts), words)
    svelte = sorted(
        p.relative_to(root).as_posix()
        for p in (root / WEB_SOURCE).rglob("*.svelte")
        if ".test." not in p.name
    )
    web = [WEB_HINTS, *svelte]
    for path in web:
        if texts := web_texts(path, read(root, path)):
            yield string_source("web", path, texts, words)


def markdown(text: str, words: frozenset[str], *, mdx: bool = False) -> str:
    """A Markdown document as the linter reads it, line for line.

    Command lines in headings (``## huron adm grant``) become code. In MDX, the ``import`` and
    ``export`` lines are code and become blank.
    """
    lines = text.split("\n")
    for index, line in enumerate(lines):
        if mdx and MDX_ESM.match(line):
            lines[index] = ""
        elif HEADING.match(line):
            lines[index] = mark_code(line, words)
    return "\n".join(lines)


def unique(texts: Iterable[Text]) -> list[Text]:
    """Texts in source order, each one once."""
    return sorted(set(texts), key=lambda text: (text.line, text.text))


# --- Linting ---------------------------------------------------------------------------------


def lint_source(source: Source) -> list[Finding]:
    """The findings of one source, at their source lines."""
    raw, _ = linter().lint(source.markdown, filename=source.path)
    findings = [finding_of(source, item, strict=source.mode == STRICT) for item in raw]
    if source.strict_table:
        # The rows of the table are strict: synonym rotation among them fails the check.
        rows = "\n".join(
            line if line.lstrip().startswith("|") else "" for line in source.markdown.split("\n")
        )
        table, _ = linter().lint(rows, filename=source.path)
        strict = [
            finding_of(source, item, strict=True) for item in table if item["rule"] in LEXICAL_RULES
        ]
        places = {(f.line, f.col, f.rule) for f in strict}
        findings = [f for f in findings if (f.line, f.col, f.rule) not in places] + strict
    return sorted(findings, key=lambda f: (f.line, f.col, f.rule))


def finding_of(source: Source, item: dict[str, Any], *, strict: bool) -> Finding:
    """A linter finding of a source, with its level under the source's mode."""
    lines = source.markdown.split("\n")
    number = int(item["line"])
    excerpt = lines[number - 1].strip() if 0 < number <= len(lines) else ""
    hard = item["level"] == "advisory-free" and (strict or item["rule"] not in LEXICAL_RULES)
    line = source.lines[number - 1] if source.lines and number <= len(source.lines) else number
    return Finding(
        area=source.area,
        path=source.path,
        line=line,
        col=int(item["col"]),
        rule=str(item["rule"]),
        level="hard" if hard else "advisory",
        match=str(item["match"]),
        message=str(item["message"]),
        excerpt=excerpt,
    )


@dataclass
class Report:
    """The findings of a run, and the ``KEPT`` entries no finding matched."""

    findings: list[Finding]
    stale: list[Kept]
    checked: list[str] = field(default_factory=list)

    @property
    def hard(self) -> list[Finding]:
        """The findings that fail the check."""
        return [f for f in self.findings if f.hard]

    def areas(self) -> dict[str, dict[str, int]]:
        """The number of hard, advisory and kept findings per area."""
        counts: dict[str, Counter[str]] = {area: Counter() for area in self.checked}
        for f in self.findings:
            kind = "kept" if f.kept else f.level
            counts.setdefault(f.area, Counter())[kind] += 1
        return {
            area: {kind: counts[area][kind] for kind in ("hard", "advisory", "kept")}
            for area in counts
        }


def check(
    root: Path,
    words: frozenset[str],
    only: Sequence[str] = (),
    kept: Sequence[Kept] = KEPT,
) -> Report:
    """Lint every source under ``root``, or only the sources at or under the paths ``only``."""
    findings: list[Finding] = []
    checked: set[str] = set()
    areas = [] if only else list(AREAS)
    for source in sources(root, words):
        if only and not any(within(source.path, path) for path in only):
            continue
        checked.add(source.path)
        if source.area not in areas:
            areas.append(source.area)
        findings.extend(lint_source(source))
    used: set[Kept] = set()
    for f in findings:
        for entry in kept:
            if entry.path == f.path and entry.rule == f.rule and entry.text in f.excerpt:
                f.kept = entry.reason
                used.add(entry)
                break
    stale = [entry for entry in kept if entry not in used and entry.path in checked]
    return Report(findings, stale, areas)


def within(path: str, prefix: str) -> bool:
    """Whether ``path`` is ``prefix`` or lies under it."""
    prefix = prefix.rstrip("/")
    return path == prefix or path.startswith(prefix + "/")


# --- Output ----------------------------------------------------------------------------------


def render(report: Report, *, advisory: bool) -> str:
    """The readable report: findings, then a count per area."""
    lines = []
    for f in report.findings:
        if f.hard or advisory:
            label = f.rule if f.hard else f"{f.rule} (advisory)"
            if f.kept:
                label = f"{f.rule} (kept: {f.kept})"
            lines.append(f"{f.path}:{f.line}:{f.col} {label}: {f.message} [{f.match}]")
            lines.append(f"    {f.excerpt}")
    for entry in report.stale:
        lines.append(
            f"{entry.path}: stale KEPT entry, no {entry.rule} finding holds {entry.text!r}"
        )
    if lines:
        lines.append("")
    lines.append(f"{'area':<16}{'hard':>6}{'advisory':>10}{'kept':>6}")
    for area, counts in report.areas().items():
        lines.append(f"{area:<16}{counts['hard']:>6}{counts['advisory']:>10}{counts['kept']:>6}")
    failures = len(report.hard) + len(report.stale)
    lines.append("")
    lines.append(
        f"ste_check: {failures} hard violations." if failures else "ste_check: no hard violations."
    )
    if not advisory:
        lines.append("Advisory findings do not fail the check. Use --advisory to list them.")
    return "\n".join(lines)


def as_json(report: Report) -> str:
    """The report as JSON."""
    document = {
        "hard": len(report.hard) + len(report.stale),
        "areas": report.areas(),
        "findings": [{**asdict(f), "hard": f.hard} for f in report.findings],
        "stale": [asdict(entry) for entry in report.stale],
    }
    return json.dumps(document, indent=2)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the check. Exit 1 when a hard violation remains."""
    parser = argparse.ArgumentParser(
        prog="ste_check.py",
        description="Check Huron's user-facing English against the ASD-STE100 rules.",
    )
    parser.add_argument("paths", nargs="*", metavar="PATH", help="check only sources under PATH")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument("--advisory", action="store_true", help="also list advisory findings")
    args = parser.parse_args(argv)
    only = [
        Path(p).resolve().relative_to(ROOT).as_posix()
        if Path(p).is_absolute()
        else Path(p).as_posix()
        for p in args.paths
    ]
    report = check(ROOT, command_words(), only)
    print(as_json(report) if args.json else render(report, advisory=args.advisory))
    return 1 if report.hard or report.stale else 0


if __name__ == "__main__":
    sys.exit(main())
