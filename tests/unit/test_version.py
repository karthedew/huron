"""The package version matches the project metadata."""

import tomllib
from pathlib import Path

import huron


def test_package_version_matches_pyproject() -> None:
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    project = tomllib.loads(pyproject.read_text())["project"]
    assert huron.__version__ == project["version"]
