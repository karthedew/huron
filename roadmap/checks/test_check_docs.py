"""Exercise documentation-checker CLI contracts with disposable real-plan copies."""

import hashlib
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
PLANS = ROOT / "roadmap/plans"
LEGACY = "## Serial task slices"
CANONICAL = "## Per-subject serial task slices"
TASK_ERROR = (
    "{name}: expected exactly one phase task heading "
    f"({CANONICAL} or {LEGACY}), found "
)
STATUS_ERROR = (
    "{name}: expected one explicit lifecycle Status: "
    "draft/blocked/ready/implementing/verified"
)


def git(*args):
    """Read Git state without refreshing the index stat cache."""
    return subprocess.check_output(["git", "--no-optional-locks", *args], cwd=ROOT)


def fingerprint(paths):
    """Hash ordered paths and their contents, including missing tracked files."""
    digest = hashlib.sha256()
    for path in paths:
        content = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "missing"
        digest.update(path.relative_to(ROOT).as_posix().encode() + b"\0")
        digest.update(content.encode() + b"\0")
    return digest.hexdigest()


def preservation_state():
    """Capture source, real plans, HEAD, dirty inventory and raw index bytes."""
    names = sorted(set(filter(None, git(
        "ls-files", "--cached", "--others", "--exclude-standard", "-z"
    ).decode().split("\0"))))
    plans = sorted(PLANS.glob("*.md"))
    index = ROOT / git("rev-parse", "--git-path", "index").decode().strip()
    return {
        "HEAD": git("rev-parse", "HEAD").decode().strip(),
        f"source ({len(names)} Git-visible paths)": fingerprint([ROOT / name for name in names]),
        f"plans ({len(plans)} real plans)": fingerprint(plans),
        "index": hashlib.sha256(index.read_bytes()).hexdigest(),
        "status": hashlib.sha256(git("status", "--porcelain=v1", "-uall")).hexdigest(),
    }


def replace_once(text, old, new):
    """Change one known fixture contract and refuse an ambiguous source copy."""
    assert text.count(old) == 1, (old, "expected one fixture marker")
    return text.replace(old, new, 1)


def cases(source):
    """Cover exact headings and retain the existing lifecycle rejection matrix."""
    def heading_case(name, replacement, count=1):
        expected = () if count == 1 else (TASK_ERROR + str(count),)
        return name, replace_once(source, LEGACY + "\n", replacement + "\n"), expected

    yield heading_case("legacy heading", LEGACY)
    yield heading_case("canonical heading", CANONICAL)
    yield heading_case("missing task heading", "", 0)
    for first in (CANONICAL, LEGACY):
        for second in (CANONICAL, LEGACY):
            yield heading_case(f"duplicate {first} / {second}", first + "\n\n" + second, 2)

    for heading in (CANONICAL, LEGACY):
        malformed = {
            "inline prose": "Text " + heading,
            "deeper level": "#" + heading,
            "suffix": heading + " extra",
            "missing separator": "##" + heading[3:],
            "wrong case": heading.lower(),
            "inline code": "`" + heading + "`",
            "indented code": "    " + heading,
            "closing hashes": heading + " ##",
            "split line": "##\n" + heading[3:],
            "lookalike letter": heading.replace("slices", "slice\u0455"),
        }
        for name, replacement in malformed.items():
            yield heading_case(f"{name}: {heading}", replacement, 0)
        for fence in ("```", "~~~"):
            example = f"{fence}markdown\n{heading}\n{fence}"
            yield heading_case(f"fenced-only {fence}: {heading}", example, 0)
            yield heading_case(f"heading plus fenced example {fence}: {heading}", heading + "\n" + example)
            yield heading_case(f"unclosed fence {fence}: {heading}", f"{fence}markdown\n{heading}", 0)

    yield heading_case("short inner fence stays literal", f"````markdown\n```\n{CANONICAL}\n````", 0)
    yield heading_case("other fence marker stays literal", f"~~~markdown\n```\n{LEGACY}\n~~~", 0)
    yield heading_case("longer closing fence", f"````markdown\n{LEGACY}\n`````\n{CANONICAL}")
    yield heading_case("indented fences", f"   ~~~markdown\n{LEGACY}\n   ~~~\n{CANONICAL}")

    status_match = re.search(r"^Status:.*$", source, re.M)
    status_line = status_match.group()
    status_line_number = source.count("\n", 0, status_match.start()) + 1
    for status in (
        "draft", "blocked", "ready", "implementing", "verified",
        "DRAFT", "BLOCKED", "READY", "IMPLEMENTING", "VERIFIED",
        "ready — independently reviewed",
    ):
        yield f"lifecycle {status}", replace_once(source, status_line, "Status: " + status), ()
    for status in ("PASS", "ready/blocked", "readyish", "", "ready\nStatus: blocked"):
        yield (
            f"invalid lifecycle {status!r}",
            replace_once(source, status_line, "Status: " + status),
            (f"{{path}}:{status_line_number}: trailing whitespace", STATUS_ERROR)
            if status == "" else (STATUS_ERROR,),
        )
    yield "missing status", replace_once(source, status_line, "State: blocked"), (STATUS_ERROR,)
    yield (
        "missing non-task section",
        replace_once(source, "## Skills", "## Missing skills heading"),
        ("{name}: missing phase section Skills",),
    )
    yield (
        "missing gate marker", source.replace("make docs", "make absent"),
        ("{name}: missing readiness/gate marker make docs",),
    )
    missing_skill = ".agents/skills/nonexistent/SKILL.md"
    yield (
        "missing local skill",
        source.replace(".agents/skills/design-plan/SKILL.md", missing_skill),
        ("{path}: missing local skill " + missing_skill, "{name}: missing local skill " + missing_skill),
    )


def run_checker():
    """Invoke the real checker through its public CLI with a bounded wait."""
    return subprocess.run(
        [sys.executable, "roadmap/check_docs.py"], cwd=ROOT,
        capture_output=True, text=True, timeout=30,
    )


def main():
    """Check exact CLI outcomes and always remove only this run's owned fixture."""
    before = preservation_state()
    source = (PLANS / "001-decisions-prototypes.md").read_text()
    assert CANONICAL in (ROOT / ".agents/templates/phase-plan.md").read_text().splitlines()
    accepted = rejected = 0
    try:
        baseline = run_checker()
        assert baseline.returncode == 0 and not baseline.stderr, (baseline.stdout, baseline.stderr)
        assert baseline.stdout.startswith("PASS: "), baseline.stdout
        fixture = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", prefix="check-docs-", suffix=".md", dir=PLANS, delete=False,
        )
        path = Path(fixture.name)
        try:
            git("check-ignore", "--quiet", str(path))
            for name, text, errors in cases(source):
                fixture.seek(0)
                fixture.truncate()
                fixture.write(text)
                fixture.flush()
                result = run_checker()
                expected_exit = 1 if errors else 0
                expected_output = "\n".join(
                    error.format(name=path.name, path=path.relative_to(ROOT)) for error in errors
                ) + "\n" if errors else baseline.stdout
                assert (result.returncode, result.stdout, result.stderr) == (
                    expected_exit, expected_output, ""
                ), (name, result.returncode, result.stdout, result.stderr, expected_exit, expected_output)
                accepted += not errors
                rejected += bool(errors)
                print(f"{name!r}: exit {result.returncode}", flush=True)
        finally:
            fixture.close()
            path.unlink()
    finally:
        after = preservation_state()
        assert after == before, ("preservation mismatch; no automatic restore attempted", before, after)
        for label, digest in before.items():
            print(f"Preserved {label}: {digest}", flush=True)
    print(f"OK: {accepted} accepted + {rejected} rejected = {accepted + rejected} CLI cases; baseline exit 0")


if __name__ == "__main__":
    main()
