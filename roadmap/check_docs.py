"""Check repository documentation links, fragments and owned text whitespace."""

import re
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
untracked = subprocess.check_output(
    ["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=ROOT
).decode().split("\0")
paths = {ROOT / p for p in tracked if p and (p.startswith(("design/", "docs/")) or p in {"README.md", "CONTEXT.md", "AGENTS.md", "web/README.md", "web/src/lib/api/README.md"})}
paths.update(ROOT.glob("design/*.md"))
errors = []

def anchors(path):
    text = path.read_text()
    result = set(re.findall(r'\b(?:id|name)=["\']([^"\']+)', text))
    seen = {}
    for heading in re.findall(r"^#{1,6}\s+(.+)$", text, re.M):
        slug = re.sub(r"[^\w\- ]", "", heading.replace("`", "").lower()).replace(" ", "-")
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        result.add(slug + (f"-{count}" if count else ""))
    return result

for path in sorted(paths):
    if not path.is_file() or path.suffix not in {".md", ".html"}:
        continue
    text = path.read_text()
    # Ignore fenced examples; inspect actual Markdown links and HTML navigation.
    scan = re.sub(r"```.*?```", "", text, flags=re.S) if path.suffix == ".md" else text
    links = re.findall(r'(?:href|src)=["\']([^"\']+)', scan)
    links += re.findall(r"!?\[[^\]\n]*\]\(([^\s)]+)(?:\s+[^)]*)?\)", scan)
    links += re.findall(r"^\[[^\]]+\]:\s*(\S+)", scan, re.M)
    for link in links:
        url = urlsplit(link)
        if url.scheme or url.netloc or link.startswith("//"):
            continue
        target = (path.parent / unquote(url.path)).resolve() if url.path else path
        if ROOT / "roadmap" in target.parents:
            errors.append(f"{path.relative_to(ROOT)}: ignored-plan link {link}")
        elif not target.exists():
            errors.append(f"{path.relative_to(ROOT)}: missing {link}")
        elif url.fragment and target.is_file() and target.suffix in {".md", ".html"} and unquote(url.fragment) not in anchors(target):
            errors.append(f"{path.relative_to(ROOT)}: missing fragment {link}")

for path in sorted({*paths, *ROOT.glob("roadmap/**/*.md"), *ROOT.glob("roadmap/*.py")}):
    if path.is_file() and path.suffix in {".md", ".html", ".py"}:
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if line.rstrip() != line:
                errors.append(f"{path.relative_to(ROOT)}:{number}: trailing whitespace")

# git diff omits new text, including unrelated work; report defects without editing it.
for name in untracked:
    path = ROOT / name
    if not name or not path.is_file():
        continue
    try:
        text = path.read_text()
    except UnicodeDecodeError:
        continue  # Binary artifacts are not text-whitespace inputs.
    if "\0" in text:
        continue
    for number, line in enumerate(text.splitlines(), 1):
        if line.rstrip() != line:
            errors.append(f"{name}:{number}: untracked text trailing whitespace")

# No tracked Markdown/HTML asset may acquire a dependency on ignored local plans.
for name in tracked:
    path = ROOT / name
    if path.is_file() and path.suffix in {".md", ".html"}:
        text = path.read_text()
        links = re.findall(r'(?:href|src)=["\']([^"\']+)', text)
        links += re.findall(r"!?\[[^\]\n]*\]\(([^\s)]+)", text)
        for link in links:
            url = urlsplit(link)
            if not url.scheme and not url.netloc and ROOT / "roadmap" in (path.parent / unquote(url.path)).resolve().parents:
                errors.append(f"{name}: tracked dependency on ignored plan {link}")

TASK_HEADINGS = ("## Per-subject serial task slices", "## Serial task slices")


def count_task_headings(text):
    """Count exact standalone task headings outside backtick/tilde fenced examples."""
    count = 0
    fence = ""
    for line in text.splitlines():
        marker = re.fullmatch(r" {0,3}(`{3,}|~{3,})(.*)", line)
        if fence:
            if (marker and marker[1][0] == fence[0]
                    and len(marker[1]) >= len(fence) and not marker[2].strip()):
                fence = ""
        elif marker:
            fence = marker[1]
        elif line in TASK_HEADINGS:
            count += 1
    return count


sections = ["Context and outcome", "Prototype evidence", "Exact scope and ownership",
            "Interfaces and implementation examples", "Skills",
            "Acceptance and complete applicable gates", "Blockers and readiness",
            "Execution ledger", "Escalation / final receipt"]
phase_paths = sorted(ROOT.glob("roadmap/plans/*.md"))
for phase_id in range(11):
    matches = [p for p in phase_paths if p.name.startswith(f"{phase_id:03}-")]
    if len(matches) != 1:
        errors.append(f"phase {phase_id:03}: expected exactly one plan, found {len(matches)}")

for path in [ROOT / "roadmap/README.md", *phase_paths]:
    text = path.read_text()
    for filename in re.findall(r"\b\d{3}-[a-z][a-z0-9-]*\.md\b", text):
        if not (ROOT / "roadmap/plans" / filename).is_file():
            errors.append(f"{path.relative_to(ROOT)}: missing phase cross-reference {filename}")
    for skill in re.findall(r"\.agents/skills/[a-z-]+/SKILL\.md", text):
        if not (ROOT / skill).is_file():
            errors.append(f"{path.relative_to(ROOT)}: missing local skill {skill}")

for path in sorted(ROOT.glob("roadmap/plans/*.md")):
    if path.name.startswith("000-"):
        continue  # Prior independently verified tooling ledger uses its original headings.
    text = path.read_text()
    for section in sections:
        if f"## {section}" not in text:
            errors.append(f"{path.name}: missing phase section {section}")
    task_count = count_task_headings(text)
    if task_count != 1:
        errors.append(
            f"{path.name}: expected exactly one phase task heading "
            f"({' or '.join(TASK_HEADINGS)}), found {task_count}"
        )
    for skill in re.findall(r"\.agents/skills/[a-z-]+/SKILL\.md", text):
        if not (ROOT / skill).is_file():
            errors.append(f"{path.name}: missing local skill {skill}")
    # Validate an explicit lifecycle state, not a permanent execution prohibition.
    # Evidence/review determine readiness; syntax alone cannot certify a transition.
    statuses = re.findall(r"^Status:[ \t]*(.*)$", text, re.M)
    if len(statuses) != 1 or not re.fullmatch(
        r"(?:draft|blocked|ready|implementing|verified)(?:[ \t]+[—–-][ \t]+\S.*)?",
        statuses[0] if statuses else "",
        re.I,
    ):
        errors.append(f"{path.name}: expected one explicit lifecycle Status: draft/blocked/ready/implementing/verified")
    for required in ["No", "make docs", "git diff --check", "review"]:
        if required not in text:
            errors.append(f"{path.name}: missing readiness/gate marker {required}")

print("\n".join(errors) if errors else "PASS: local documentation links/fragments, no tracked ignored-plan links, owned/untracked text whitespace, 000–010 phase cross-references/skills and 10 product phase structures")
raise SystemExit(bool(errors))
