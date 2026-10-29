"""Repository conventions: directory names and public-before-private module order."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_DIRECTORY_NAMES = frozenset({"_impl", "internal", "private"})
IGNORED_DIRECTORIES = frozenset({"__pycache__", ".pytest_cache", ".hypothesis", ".mypy_cache"})


def directory_violations(root: Path) -> list[str]:
    """Return directories under ``root`` whose names break the naming rule."""
    violations: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_dir() or any(part in IGNORED_DIRECTORIES for part in path.parts):
            continue
        name = path.name
        if "_" in name or name in FORBIDDEN_DIRECTORY_NAMES:
            violations.append(str(path.relative_to(root)))
    return violations


def ordering_violations(root: Path) -> list[str]:
    """Return modules where a private top-level definition precedes a public one."""
    violations: list[str] = []
    for path in sorted(root.rglob("*.py")):
        if any(part in IGNORED_DIRECTORIES for part in path.parts):
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        seen_private = False
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                continue
            if node.name.startswith("__") and node.name.endswith("__"):
                continue
            if node.name.startswith("_"):
                seen_private = True
            elif seen_private:
                violations.append(f"{path.relative_to(root)}:{node.lineno} {node.name}")
                break
    return violations


@pytest.mark.parametrize("area", ["src", "tests"])
def test_no_directory_contains_an_underscore(area: str) -> None:
    assert directory_violations(ROOT / area) == []


@pytest.mark.parametrize("area", ["src", "tests"])
def test_public_definitions_precede_private_ones(area: str) -> None:
    assert ordering_violations(ROOT / area) == []


def test_directory_check_flags_underscores_and_private_names(tmp_path: Path) -> None:
    (tmp_path / "a_b").mkdir()
    (tmp_path / "pkg" / "internal").mkdir(parents=True)
    (tmp_path / "pkg" / "__pycache__").mkdir()
    assert directory_violations(tmp_path) == ["a_b", "pkg/internal"]


def test_ordering_check_flags_a_private_function_before_a_public_one(tmp_path: Path) -> None:
    (tmp_path / "bad.py").write_text("def _helper():\n    pass\n\n\ndef public():\n    pass\n")
    (tmp_path / "good.py").write_text(
        "class Public:\n    pass\n\n\ndef _helper():\n    pass\n\n\ndef __getattr__(n):\n    pass\n"
    )
    assert ordering_violations(tmp_path) == ["bad.py:5 public"]
