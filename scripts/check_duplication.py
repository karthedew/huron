"""Enforce pyscn's native duplication score without replacing its scoring formula.

pyscn 1.31.1 writes JSON to a generated path announced on stderr and has no
score-threshold flag. Read only the report announced by this successful run,
never the newest report in a directory (which might belong to an older run).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

SUPPORTED_VERSION = "1.31.1"


class DuplicationReport(NamedTuple):
    """Validated native score and clone counts, without a replacement scoring formula."""

    score: int
    total_fragments: int
    total_clones: int
    clone_pairs: int
    clone_groups: int


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


def main(package: str) -> int:
    """Analyze a package and fail unless its native duplication score is at least 90.

    Args:
        package: Package path to analyze from the current working directory.

    Returns:
        Zero for a passing score, one below 90, or two for tool/report failures.
    """
    try:
        result = subprocess.run(
            ["uv", "run", "--locked", "pyscn", "analyze", "--select", "clones", "--json", package],
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
        report = duplication_report(json.loads(Path(paths[0]).read_text(encoding="utf-8")))
    except subprocess.CalledProcessError as exc:
        print(exc.stdout, end="")
        print(exc.stderr, end="", file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(f"pyscn duplication gate: {exc}", file=sys.stderr)
        return 2
    print(
        f"pyscn {SUPPORTED_VERSION} native duplication score: {report.score}/100 "
        "(required: >=90/100)"
    )
    print(
        f"Cloned fragments: {report.total_clones}/{report.total_fragments}; "
        f"clone pairs: {report.clone_pairs}; clone groups: {report.clone_groups}"
    )
    return 0 if report.score >= 90 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
