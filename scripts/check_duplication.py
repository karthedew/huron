"""Enforce a duplication regression guard against a committed clone baseline.

pyscn 1.31.1 writes JSON to a generated path announced on stderr and has no
score-threshold flag. Read only the report announced by this successful run,
never the newest report in a directory (which might belong to an older run).

Clone detection runs at similarity 0.80. This tree's clones are type-2/type-4
structural silhouettes with a measured maximum similarity of 0.85, so pyscn's
native ``summary.duplication_score`` cannot reach 90 by design; it is reported
for information only and never gates the build. Instead, each scan's clone
inventory (see ``clone_group_signatures``) is compared against the committed
baseline in ``scripts/duplication_baseline.json``: the gate fails only when
detection grows past that baseline (more total clones, a clone group with a
file signature the baseline has never seen, or a known signature that grew
larger), never on an absolute score. Lowering the baseline (``--update-
baseline``) ratchets detection down when a change genuinely removes
duplication; raising it is a reviewed manual edit, never automatic.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

SUPPORTED_VERSION = "1.31.1"
CLONE_THRESHOLD = 0.80
REPO_ROOT = Path(__file__).resolve().parent.parent
# Relative so it resolves against the caller's working directory (repository
# root, per documented usage), letting tests redirect it with a chdir.
BASELINE_PATH = Path("scripts") / "duplication_baseline.json"


class DuplicationReport(NamedTuple):
    """Validated native score and clone counts, without a replacement scoring formula."""

    score: int
    total_fragments: int
    total_clones: int
    clone_pairs: int
    clone_groups: int


class CloneGroupSignature(NamedTuple):
    """A clone group's location signature: its sorted unique files and member count."""

    files: tuple[str, ...]
    size: int


class Baseline(NamedTuple):
    """A validated committed duplication baseline used as a regression guard."""

    pyscn_version: str
    clone_threshold: float
    total_clones: int
    clone_groups: int
    groups: tuple[CloneGroupSignature, ...]


def _object(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"missing or malformed pyscn {field}")
    return value


def _count(value: object, field: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"invalid pyscn {field}; expected a nonnegative integer")
    return value


def duplication_report(report: object) -> DuplicationReport:
    """Read the native score and counts only from a complete clone-analysis report.

    Args:
        report: Decoded pyscn JSON report.

    Returns:
        The native duplication score and its fragment, pair, and group context.

    Raises:
        ValueError: If the report is unsupported, malformed, incomplete, or failed.
    """
    data = _object(report, "report")
    if data.get("version") != SUPPORTED_VERSION:
        raise ValueError(f"unsupported pyscn version; expected {SUPPORTED_VERSION}")
    if type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        raise ValueError("unsupported pyscn schema_version; expected 1")
    summary = _object(data.get("summary"), "summary")
    clone = _object(data.get("clone"), "clone")
    statistics = _object(clone.get("statistics"), "clone.statistics")
    score = summary.get("duplication_score")
    if type(score) is not int or not 0 <= score <= 100:
        raise ValueError("invalid native duplication_score; expected an integer in [0, 100]")
    if summary.get("clone_enabled") is not True:
        raise ValueError("clone analysis was not enabled")
    if clone.get("success") is not True or clone.get("error", "") != "":
        raise ValueError("clone analysis did not succeed")
    for field, issues in (
        ("diagnostics", data.get("diagnostics", [])),
        ("failures", data.get("failures", [])),
        ("clone.errors", clone.get("errors", [])),
        ("clone.failures", clone.get("failures", [])),
    ):
        if issues != []:
            raise ValueError(f"pyscn {field} is nonempty or malformed: {issues!r}")
    total = _count(summary.get("total_files"), "summary.total_files")
    if (
        total == 0
        or _count(summary.get("analyzed_files"), "summary.analyzed_files") != total
        or _count(summary.get("skipped_files"), "summary.skipped_files") != 0
        or _count(statistics.get("files_analyzed"), "clone.statistics.files_analyzed") != total
    ):
        raise ValueError("pyscn report has missing, empty, or incomplete file coverage")
    fragments = _count(statistics.get("total_fragments"), "clone.statistics.total_fragments")
    counts: dict[str, int] = {}
    for summary_key, statistics_key, results_key in (
        ("total_clones", "total_clones", "clones"),
        ("clone_pairs", "total_clone_pairs", "clone_pairs"),
        ("clone_groups", "total_clone_groups", "clone_groups"),
    ):
        count = _count(summary.get(summary_key), f"summary.{summary_key}")
        if _count(statistics.get(statistics_key), f"clone.statistics.{statistics_key}") != count:
            raise ValueError(f"inconsistent pyscn {summary_key} counts")
        results = clone.get(results_key, ())
        # Go serializes a nil result slice as null when no clones were found.
        if results is None and count == 0:
            results = []
        if (
            not isinstance(results, list)
            or len(results) != count
            or any(not isinstance(item, dict) for item in results)
        ):
            raise ValueError(f"missing, malformed, or incomplete clone.{results_key}")
        counts[summary_key] = count
    if counts["total_clones"] > fragments:
        raise ValueError("cloned fragments exceed total fragments")
    return DuplicationReport(
        score, fragments, counts["total_clones"], counts["clone_pairs"], counts["clone_groups"]
    )


def _relative_to_repo_root(file_path: str) -> str:
    """Resolve a pyscn-reported file path to a path relative to the repository root.

    Args:
        file_path: Absolute or repo-relative path as reported by pyscn.

    Returns:
        A POSIX-style path relative to ``REPO_ROOT``.
    """
    resolved = Path(file_path)
    if not resolved.is_absolute():
        resolved = REPO_ROOT / resolved
    try:
        relative = resolved.resolve().relative_to(REPO_ROOT.resolve())
    except ValueError:
        relative = resolved
    return relative.as_posix()


def clone_group_signatures(report: object) -> list[CloneGroupSignature]:
    """Resolve every clone group to a deterministic file-signature and member count.

    Args:
        report: Decoded pyscn JSON report, already accepted by ``duplication_report``.

    Returns:
        One signature per reported clone group, in report order.

    Raises:
        ValueError: If clone members, groups, or their locations are malformed.
    """
    data = _object(report, "report")
    clone = _object(data.get("clone"), "clone")
    locations = _clone_locations(clone)
    groups = clone.get("clone_groups")
    if not isinstance(groups, list) or any(not isinstance(item, dict) for item in groups):
        raise ValueError("missing, malformed, or incomplete clone.clone_groups")
    return [_group_signature(group, locations) for group in groups]


def _clone_locations(clone: dict[str, object]) -> dict[object, str]:
    """Map every clone id to its reported file path.

    Args:
        clone: The report's ``clone`` section.

    Returns:
        Each clone id's ``location.file_path``.

    Raises:
        ValueError: If ``clone.clones`` or any member's location is malformed.
    """
    clones = clone.get("clones")
    if not isinstance(clones, list) or any(not isinstance(item, dict) for item in clones):
        raise ValueError("missing, malformed, or incomplete clone.clones")
    locations: dict[object, str] = {}
    for item in clones:
        location = _object(item.get("location"), "clone.location")
        file_path = location.get("file_path")
        if type(file_path) is not str or file_path == "":
            raise ValueError("missing or malformed clone.location.file_path")
        locations[item.get("id")] = file_path
    return locations


def _group_signature(group: dict[str, object], locations: dict[object, str]) -> CloneGroupSignature:
    """Resolve one clone group to its file signature and size.

    Args:
        group: One entry of ``clone.clone_groups``.
        locations: Every clone id's file path, from ``_clone_locations``.

    Returns:
        The group's sorted unique files and its reported size.

    Raises:
        ValueError: If the group's members or size are malformed or unresolvable.
    """
    members = group.get("clones")
    size = group.get("size")
    if type(size) is not int or size < 0:
        raise ValueError("invalid clone_group size; expected a nonnegative integer")
    if (
        not isinstance(members, list)
        or members == []
        or any(not isinstance(member, dict) for member in members)
    ):
        raise ValueError("missing, malformed, or incomplete clone_group.clones")
    files: set[str] = set()
    for member in members:
        member_id = member.get("id")
        if member_id not in locations:
            raise ValueError(f"clone_group references unknown clone id {member_id!r}")
        files.add(_relative_to_repo_root(locations[member_id]))
    return CloneGroupSignature(files=tuple(sorted(files)), size=size)


def _load_baseline(path: Path) -> Baseline:
    """Read and strictly validate the committed duplication baseline.

    Args:
        path: Location of the baseline JSON file.

    Returns:
        The parsed and validated baseline.

    Raises:
        ValueError: If the file is missing, unreadable, or malformed.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"duplication baseline is missing or unreadable: {exc}") from exc
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"duplication baseline is not valid JSON: {exc}") from exc
    data = _object(decoded, "baseline")
    if data.get("pyscn_version") != SUPPORTED_VERSION:
        raise ValueError(f"baseline pyscn_version must be {SUPPORTED_VERSION}")
    if data.get("clone_threshold") != CLONE_THRESHOLD:
        raise ValueError(f"baseline clone_threshold must be {CLONE_THRESHOLD}")
    total_clones = _count(data.get("total_clones"), "baseline.total_clones")
    clone_groups = _count(data.get("clone_groups"), "baseline.clone_groups")
    groups = data.get("groups")
    if not isinstance(groups, list) or len(groups) != clone_groups:
        raise ValueError("baseline groups must list exactly clone_groups entries")
    parsed = tuple(_baseline_group(group) for group in groups)
    return Baseline(
        pyscn_version=SUPPORTED_VERSION,
        clone_threshold=CLONE_THRESHOLD,
        total_clones=total_clones,
        clone_groups=clone_groups,
        groups=parsed,
    )


def _baseline_group(group: object) -> CloneGroupSignature:
    """Validate and parse one baseline group entry.

    Args:
        group: One entry of the baseline's ``groups`` list.

    Returns:
        The group's sorted unique files and its recorded size.

    Raises:
        ValueError: If the entry's files or size are malformed.
    """
    entry = _object(group, "baseline group")
    files = entry.get("files")
    size = entry.get("size")
    if (
        not isinstance(files, list)
        or files == []
        or any(type(item) is not str or item == "" for item in files)
        or files != sorted(set(files))
    ):
        raise ValueError("baseline group files must be a sorted list of unique paths")
    if type(size) is not int or size < 1:
        raise ValueError("baseline group size must be a positive integer")
    return CloneGroupSignature(files=tuple(files), size=size)


def _write_baseline(
    path: Path, report: DuplicationReport, signatures: list[CloneGroupSignature]
) -> None:
    """Write the committed duplication baseline from a fresh scan.

    Args:
        path: Location to write the baseline JSON file.
        report: The scan's validated native report.
        signatures: The scan's clone-group signatures.
    """
    groups = sorted(
        ({"files": list(signature.files), "size": signature.size} for signature in signatures),
        key=lambda group: (group["files"], group["size"]),
    )
    baseline = {
        "pyscn_version": SUPPORTED_VERSION,
        "clone_threshold": CLONE_THRESHOLD,
        "total_clones": report.total_clones,
        "clone_groups": report.clone_groups,
        "groups": groups,
    }
    with path.open("w", encoding="utf-8") as handle:
        json.dump(baseline, handle, indent=2, sort_keys=True)
        handle.write("\n")


def _baseline_max_sizes(baseline: Baseline) -> dict[tuple[str, ...], int]:
    """Map each baseline clone-group file signature to its largest recorded size.

    Args:
        baseline: The parsed committed baseline.

    Returns:
        The largest committed size for every distinct file signature.
    """
    sizes: dict[tuple[str, ...], int] = {}
    for group in baseline.groups:
        sizes[group.files] = max(sizes.get(group.files, 0), group.size)
    return sizes


def _regressions(
    signatures: list[CloneGroupSignature], baseline_sizes: dict[tuple[str, ...], int]
) -> list[tuple[str, CloneGroupSignature]]:
    """Classify scanned clone groups against the baseline's known signatures and sizes.

    Args:
        signatures: The scan's clone-group signatures.
        baseline_sizes: The baseline's largest recorded size per file signature.

    Returns:
        One ``(reason, signature)`` pair per new or grown clone group.
    """
    findings: list[tuple[str, CloneGroupSignature]] = []
    for signature in signatures:
        baseline_size = baseline_sizes.get(signature.files)
        if baseline_size is None:
            findings.append(("new clone group", signature))
        elif signature.size > baseline_size:
            findings.append(("grown clone group", signature))
    return findings


def _update_baseline(
    path: Path, report: DuplicationReport, signatures: list[CloneGroupSignature]
) -> int:
    """Ratchet the committed baseline down to match a scan; never raise it automatically.

    Args:
        path: Location of the committed duplication baseline.
        report: The scan's validated native report.
        signatures: The scan's clone-group signatures.

    Returns:
        Zero once the baseline is bootstrapped or ratcheted down, one if the
        scan would raise it, two if an existing baseline is malformed.
    """
    if path.exists():
        try:
            baseline = _load_baseline(path)
        except ValueError as exc:
            print(f"pyscn duplication gate: {exc}", file=sys.stderr)
            return 2
        regressions = _regressions(signatures, _baseline_max_sizes(baseline))
        if report.total_clones > baseline.total_clones or regressions:
            print(
                "refusing to update the duplication baseline: this scan would raise it "
                f"(total clones {report.total_clones} vs baseline {baseline.total_clones}, "
                f"{len(regressions)} new or grown group(s)); raising the baseline is a "
                "reviewed manual edit, never an automatic update",
                file=sys.stderr,
            )
            return 1
    _write_baseline(path, report, signatures)
    print(f"Updated {path} ({report.total_clones} clones, {report.clone_groups} groups).")
    return 0


def _check_baseline(
    path: Path, report: DuplicationReport, signatures: list[CloneGroupSignature]
) -> int:
    """Gate a scan against the committed baseline: fail only on clone growth.

    Args:
        path: Location of the committed duplication baseline.
        report: The scan's validated native report.
        signatures: The scan's clone-group signatures.

    Returns:
        Zero when the scan matches or improves on the baseline, one on
        regression, two if the baseline is missing or malformed.
    """
    if not path.exists():
        print(f"pyscn duplication gate: missing duplication baseline at {path}", file=sys.stderr)
        return 2
    try:
        baseline = _load_baseline(path)
    except ValueError as exc:
        print(f"pyscn duplication gate: {exc}", file=sys.stderr)
        return 2
    print(
        f"Baseline: {baseline.total_clones} clones, {baseline.clone_groups} groups "
        f"(clone threshold {baseline.clone_threshold})."
    )
    regressions = _regressions(signatures, _baseline_max_sizes(baseline))
    if report.total_clones > baseline.total_clones or regressions:
        print(
            f"Duplication regression: total clones {report.total_clones} "
            f"(baseline {baseline.total_clones}, delta "
            f"{report.total_clones - baseline.total_clones:+d}).",
            file=sys.stderr,
        )
        for reason, signature in regressions:
            print(f"  {reason}: {list(signature.files)} (size {signature.size})", file=sys.stderr)
        return 1
    if report.total_clones < baseline.total_clones:
        print(
            "Duplication decreased with no new or grown groups; run with "
            "--update-baseline to ratchet the baseline down."
        )
    return 0


def main(
    package: str, *, update_baseline: bool = False, baseline_path: Path = BASELINE_PATH
) -> int:
    """Analyze a package and fail only on clone growth relative to the committed baseline.

    Args:
        package: Package path to analyze from the current working directory.
        update_baseline: When true, rewrite the baseline from this scan instead
            of gating against it. Refuses to raise total clones or introduce an
            unrecognized group signature; bootstraps only when no baseline exists.
        baseline_path: Location of the committed duplication baseline.

    Returns:
        Zero when the scan matches or improves on the baseline (or a baseline
        update succeeds), one on regression or a refused update, two for tool,
        report, or baseline failures.
    """
    try:
        result = subprocess.run(
            [
                "uv",
                "run",
                "--locked",
                "pyscn",
                "analyze",
                "--select",
                "clones",
                "--json",
                "--clone-threshold",
                "0.80",
                package,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        print(result.stdout, end="")
        print(result.stderr, end="", file=sys.stderr)
        paths = re.findall(r"Unified JSON report generated: (.+)$", result.stderr, re.MULTILINE)
        if len(paths) != 1:
            print("expected exactly one generated pyscn JSON report path", file=sys.stderr)
            return 2
        raw_report = json.loads(Path(paths[0]).read_text(encoding="utf-8"))
        report = duplication_report(raw_report)
        signatures = clone_group_signatures(raw_report)
    except subprocess.CalledProcessError as exc:
        print(exc.stdout, end="")
        print(exc.stderr, end="", file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(f"pyscn duplication gate: {exc}", file=sys.stderr)
        return 2
    print(
        f"pyscn {SUPPORTED_VERSION} native duplication score: {report.score}/100 "
        "(reported, not gated)"
    )
    print(
        f"Cloned fragments: {report.total_clones}/{report.total_fragments}; "
        f"clone pairs: {report.clone_pairs}; clone groups: {report.clone_groups}"
    )
    if update_baseline:
        return _update_baseline(baseline_path, report, signatures)
    return _check_baseline(baseline_path, report, signatures)


if __name__ == "__main__":
    argv = sys.argv[1:]
    update = "--update-baseline" in argv
    positional = [arg for arg in argv if arg != "--update-baseline"]
    if len(positional) != 1:
        print("usage: check_duplication.py <package> [--update-baseline]", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(positional[0], update_baseline=update))
