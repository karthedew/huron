"""The duplication gate uses native scores and fails closed on missing evidence."""

from __future__ import annotations

import importlib.util
import json
import runpy
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit

_PATH = Path(__file__).resolve().parents[2] / "scripts" / "check_duplication.py"
_SPEC = importlib.util.spec_from_file_location("check_duplication", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
gate = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(gate)


def _report(score: object = 90) -> dict[str, object]:
    clones = [
        {
            "id": index,
            "type": 0,
            "location": {
                "file_path": f"src/example{index}.py",
                "start_line": 1,
                "end_line": 10,
                "start_col": 0,
                "end_col": 12,
            },
            "hash": f"abc{index}",
            "size": 24,
            "line_count": 10,
            "complexity": 0,
        }
        for index in (1, 2)
    ]
    return {
        "version": "1.31.1",
        "schema_version": 1,
        "generated_at": "2026-09-09T14:48:12Z",
        "duration_ms": 2,
        "summary": {
            "duplication_score": score,
            "health_score": 100,
            "clone_enabled": True,
            "total_files": 2,
            "analyzed_files": 2,
            "skipped_files": 0,
            "total_clones": 2,
            "clone_pairs": 1,
            "clone_groups": 1,
            "code_duplication_percentage": 10.0,
        },
        "clone": {
            "success": True,
            "duration_ms": 1,
            "clones": clones,
            "clone_pairs": [
                {
                    "id": 1,
                    "clone1": clones[0],
                    "clone2": clones[1],
                    "similarity": 0.8,
                    "distance": 0.2,
                    "type": 2,
                    "confidence": 1,
                }
            ],
            "clone_groups": [{"id": 1, "clones": clones, "type": 2, "similarity": 0.8, "size": 2}],
            "statistics": {
                "total_fragments": 20,
                "total_clones": 2,
                "total_clone_pairs": 1,
                "total_clone_groups": 1,
                "clones_by_type": {"Type-2": 1},
                "average_similarity": 0.8,
                "lines_analyzed": 200,
                "nodes_analyzed": 480,
                "files_analyzed": 2,
            },
        },
    }


def _section(report: dict[str, object], path: tuple[str, ...]) -> dict[str, object]:
    for key in path:
        child = report[key]
        assert isinstance(child, dict)
        report = child
    return report


@pytest.mark.parametrize(
    ("score", "status"), [(0, 1), (45, 1), (89, 1), (90, 0), (91, 0), (100, 0)]
)
def test_native_score_threshold(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], score: int, status: int
) -> None:
    """Exactly 90 passes; native scores are never replaced by health or clone-count math."""
    report = tmp_path / "report with spaces.json"
    report.write_text(json.dumps(_report(score)))
    result = subprocess.CompletedProcess([], 0, "", f"Unified JSON report generated: {report}\n")
    with patch.object(gate.subprocess, "run", return_value=result) as run:
        assert gate.main("src/huron") == status
    assert run.call_args.args[0] == [
        "uv",
        "run",
        "--locked",
        "pyscn",
        "analyze",
        "--select",
        "clones",
        "--json",
        "src/huron",
    ]
    assert run.call_args.kwargs["check"] is True
    output = capsys.readouterr()
    assert f"pyscn 1.31.1 native duplication score: {score}/100 (required: >=90/100)" in output.out
    assert "Cloned fragments: 2/20; clone pairs: 1; clone groups: 1" in output.out
    assert str(report) in output.err


@pytest.mark.parametrize("score", [None, True, "90", 90.0, -1, 101, float("nan")])
def test_invalid_native_scores(score: object) -> None:
    """Malformed or out-of-range scores cannot pass through coercion."""
    with pytest.raises(ValueError, match="invalid native"):
        gate.duplication_report(_report(score))


@pytest.mark.parametrize("report", [None, [], {}, True, "report"])
def test_missing_or_malformed_report_object(report: object) -> None:
    """Missing native evidence is not treated as a perfect score."""
    with pytest.raises(ValueError):
        gate.duplication_report(report)


@pytest.mark.parametrize("version", [None, True, 1311, "1.30.0", "1.31.0", "1.31.2", "v1.31.1"])
def test_unsupported_version(version: object) -> None:
    """Reports from unpinned scoring implementations cannot satisfy the gate."""
    report = _report()
    report["version"] = version
    with pytest.raises(ValueError, match="unsupported pyscn version"):
        gate.duplication_report(report)


@pytest.mark.parametrize("version", [None, True, False, 0, 2, "1", 1.0])
def test_unsupported_schema_version(version: object) -> None:
    """Only the pinned native report schema is accepted, without type coercion."""
    report = _report()
    report["schema_version"] = version
    with pytest.raises(ValueError, match="unsupported pyscn schema_version"):
        gate.duplication_report(report)


@pytest.mark.parametrize(
    "path",
    [
        ("version",),
        ("schema_version",),
        ("summary",),
        ("clone",),
        ("summary", "duplication_score"),
        ("summary", "clone_enabled"),
        ("summary", "total_files"),
        ("summary", "analyzed_files"),
        ("summary", "skipped_files"),
        ("summary", "total_clones"),
        ("summary", "clone_pairs"),
        ("summary", "clone_groups"),
        ("clone", "success"),
        ("clone", "clones"),
        ("clone", "clone_pairs"),
        ("clone", "clone_groups"),
        ("clone", "statistics"),
        ("clone", "statistics", "files_analyzed"),
        ("clone", "statistics", "total_fragments"),
        ("clone", "statistics", "total_clones"),
        ("clone", "statistics", "total_clone_pairs"),
        ("clone", "statistics", "total_clone_groups"),
    ],
)
def test_missing_required_evidence(path: tuple[str, ...]) -> None:
    """Every required native score, coverage, success, and clone field must be present."""
    report = _report()
    del _section(report, path[:-1])[path[-1]]
    with pytest.raises(ValueError):
        gate.duplication_report(report)


@pytest.mark.parametrize("path", [("summary",), ("clone",), ("clone", "statistics")])
@pytest.mark.parametrize("value", [None, [], "", False])
def test_malformed_report_sections(path: tuple[str, ...], value: object) -> None:
    """Summary, clone analysis, and statistics must be native JSON objects."""
    report = _report()
    _section(report, path[:-1])[path[-1]] = value
    with pytest.raises(ValueError, match="missing or malformed"):
        gate.duplication_report(report)


@pytest.mark.parametrize("path", [("summary", "clone_enabled"), ("clone", "success")])
@pytest.mark.parametrize("value", [False, None, 1, "true"])
def test_unsuccessful_or_disabled_clones(path: tuple[str, ...], value: object) -> None:
    """Both enabled and successful clone analysis require explicit boolean true."""
    report = _report()
    _section(report, path[:-1])[path[-1]] = value
    with pytest.raises(ValueError, match="clone analysis"):
        gate.duplication_report(report)


@pytest.mark.parametrize(
    "path",
    [
        ("summary", "total_files"),
        ("summary", "analyzed_files"),
        ("summary", "skipped_files"),
        ("summary", "total_clones"),
        ("summary", "clone_pairs"),
        ("summary", "clone_groups"),
        ("clone", "statistics", "files_analyzed"),
        ("clone", "statistics", "total_fragments"),
        ("clone", "statistics", "total_clones"),
        ("clone", "statistics", "total_clone_pairs"),
        ("clone", "statistics", "total_clone_groups"),
    ],
)
@pytest.mark.parametrize("value", [None, True, False, -1, "2", 2.0])
def test_malformed_counts(path: tuple[str, ...], value: object) -> None:
    """All native file and clone counts are nonnegative integers, never coerced."""
    report = _report()
    _section(report, path[:-1])[path[-1]] = value
    with pytest.raises(ValueError, match="expected a nonnegative integer"):
        gate.duplication_report(report)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("summary", "total_files"), 0),
        (("summary", "analyzed_files"), 1),
        (("summary", "analyzed_files"), 3),
        (("summary", "skipped_files"), 1),
        (("clone", "statistics", "files_analyzed"), 1),
        (("clone", "statistics", "files_analyzed"), 3),
    ],
)
def test_incomplete_analysis(path: tuple[str, ...], value: int) -> None:
    """Empty or partial file coverage fails even when summary and clone success look healthy."""
    report = _report()
    _section(report, path[:-1])[path[-1]] = value
    with pytest.raises(ValueError, match="incomplete file coverage"):
        gate.duplication_report(report)


@pytest.mark.parametrize(
    ("path", "issue"),
    [
        (
            ("diagnostics",),
            {"file_path": "src/broken.py", "code": "parse_error", "message": "invalid syntax"},
        ),
        (
            ("failures",),
            {"analysis": "clones", "code": "execution_error", "message": "analysis failed"},
        ),
        (("clone", "errors"), "src/broken.py: invalid syntax"),
        (
            ("clone", "failures"),
            {"analysis": "clones", "code": "execution_error", "message": "analysis failed"},
        ),
    ],
)
def test_analysis_diagnostics_and_failures(path: tuple[str, ...], issue: object) -> None:
    """Native failure evidence is rejected despite successful status and complete file counts."""
    report = _report()
    _section(report, path[:-1])[path[-1]] = [issue]
    with pytest.raises(ValueError, match="nonempty or malformed"):
        gate.duplication_report(report)


@pytest.mark.parametrize(
    "path", [("diagnostics",), ("failures",), ("clone", "errors"), ("clone", "failures")]
)
@pytest.mark.parametrize("value", [None, False, 0, "", {}])
def test_malformed_failure_evidence(path: tuple[str, ...], value: object) -> None:
    """Falsey malformed diagnostics cannot masquerade as empty native failure lists."""
    report = _report()
    _section(report, path[:-1])[path[-1]] = value
    with pytest.raises(ValueError, match="nonempty or malformed"):
        gate.duplication_report(report)


@pytest.mark.parametrize("error", ["analysis failed", None, False, 0, [], {}])
def test_clone_error(error: object) -> None:
    """A clone error or malformed error field invalidates even an explicit success flag."""
    report = _report()
    _section(report, ("clone",))["error"] = error
    with pytest.raises(ValueError, match="did not succeed"):
        gate.duplication_report(report)


def test_explicit_empty_failure_fields() -> None:
    """Omitted or correctly typed empty optional failure fields both mean no failures."""
    report = _report()
    for path in [("diagnostics",), ("failures",), ("clone", "errors"), ("clone", "failures")]:
        _section(report, path[:-1])[path[-1]] = []
    _section(report, ("clone",))["error"] = ""
    assert gate.duplication_report(report).score == 90


@pytest.mark.parametrize("field", ["total_clones", "total_clone_pairs", "total_clone_groups"])
def test_inconsistent_clone_counts(field: str) -> None:
    """Summary counts must agree with the successful clone analyzer's own statistics."""
    report = _report()
    _section(report, ("clone", "statistics"))[field] = 3
    with pytest.raises(ValueError, match="inconsistent pyscn"):
        gate.duplication_report(report)


@pytest.mark.parametrize("field", ["clones", "clone_pairs", "clone_groups"])
@pytest.mark.parametrize("value", [None, False, "", {}, [], [None], [None, None]])
def test_incomplete_clone_results(field: str, value: object) -> None:
    """Missing, truncated, or malformed clone collections cannot substantiate native counts."""
    report = _report()
    _section(report, ("clone",))[field] = value
    with pytest.raises(ValueError, match="missing, malformed, or incomplete clone"):
        gate.duplication_report(report)


def test_cloned_fragments_cannot_exceed_total() -> None:
    """Fragment counts must describe a possible analysis population."""
    report = _report()
    _section(report, ("clone", "statistics"))["total_fragments"] = 1
    with pytest.raises(ValueError, match="cloned fragments exceed"):
        gate.duplication_report(report)


@pytest.mark.parametrize("results", [None, []])
@pytest.mark.parametrize("fragments", [0, 20])
def test_no_clones_in_complete_analysis(results: object, fragments: int) -> None:
    """A complete scan without clones accepts native empty or null result slices."""
    report = _report(100)
    summary = _section(report, ("summary",))
    clone = _section(report, ("clone",))
    statistics = _section(report, ("clone", "statistics"))
    summary.update(total_clones=0, clone_pairs=0, clone_groups=0, code_duplication_percentage=0)
    clone.update(clones=results, clone_pairs=results, clone_groups=results)
    statistics.update(
        total_fragments=fragments, total_clones=0, total_clone_pairs=0, total_clone_groups=0
    )
    assert gate.duplication_report(report) == gate.DuplicationReport(100, fragments, 0, 0, 0)
    del clone["clones"]
    with pytest.raises(ValueError, match=r"missing, malformed, or incomplete clone\.clones"):
        gate.duplication_report(report)


@pytest.mark.parametrize("content", [None, "not json", "{}", "null", "[]"])
def test_missing_or_invalid_report(tmp_path: Path, content: str | None) -> None:
    """An announced but unreadable or invalid report is an analysis failure."""
    path = tmp_path / "report.json"
    if content is not None:
        path.write_text(content)
    result = subprocess.CompletedProcess([], 0, "", f"Unified JSON report generated: {path}\n")
    with patch.object(gate.subprocess, "run", return_value=result):
        assert gate.main("src/huron") == 2


def test_invalid_report_encoding(tmp_path: Path) -> None:
    """An announced report with invalid UTF-8 fails closed without a traceback."""
    path = tmp_path / "report.json"
    path.write_bytes(b"\xff")
    result = subprocess.CompletedProcess([], 0, "", f"Unified JSON report generated: {path}\n")
    with patch.object(gate.subprocess, "run", return_value=result):
        assert gate.main("src/huron") == 2


@pytest.mark.parametrize(
    "stderr", ["", "Unified JSON report generated: a\nUnified JSON report generated: b\n"]
)
def test_missing_or_ambiguous_report_announcement(stderr: str) -> None:
    """The gate never falls back to stale files when the run lacks one report path."""
    result = subprocess.CompletedProcess([], 0, "", stderr)
    with patch.object(gate.subprocess, "run", return_value=result):
        assert gate.main("src/huron") == 2


@pytest.mark.parametrize(
    "error",
    [FileNotFoundError("pyscn"), subprocess.CalledProcessError(2, "pyscn", "", "parse error")],
)
def test_tool_failure(error: Exception) -> None:
    """Missing executables and unsuccessful analyses cannot supply passing evidence."""
    with patch.object(gate.subprocess, "run", side_effect=error):
        assert gate.main("src/huron") == 2


def test_command_entrypoint(tmp_path: Path) -> None:
    """The executable command propagates a passing gate's exit status."""
    report = tmp_path / "report.json"
    report.write_text(json.dumps(_report()))
    result = subprocess.CompletedProcess([], 0, "", f"Unified JSON report generated: {report}\n")
    with (
        patch.object(subprocess, "run", return_value=result),
        patch.object(sys, "argv", [str(_PATH), "src/huron"]),
        pytest.raises(SystemExit) as exc,
    ):
        runpy.run_path(str(_PATH), run_name="__main__")
    assert exc.value.code == 0
