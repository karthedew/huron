"""Every error code is registered once, raised codes are registered, and all are documented."""

import importlib
import re
from pathlib import Path

import pytest

from huron.pkg.errors import error_codes

ROOT = Path(__file__).resolve().parents[2]


PATTERN = re.compile(r'register\(\s*"([A-Z_]+)"')


@pytest.fixture(autouse=True)
def every_code_registered() -> None:
    """Import the API application, which imports every module that registers a code."""
    importlib.import_module("huron.applications.api.app")


def registered_in_source() -> list[str]:
    found: list[str] = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        found.extend(PATTERN.findall(path.read_text()))
    return found


def test_each_code_is_registered_exactly_once_in_source() -> None:
    codes = registered_in_source()
    assert len(codes) == len(set(codes))
    assert set(codes) == {entry.code for entry in error_codes().all()}


def test_every_code_is_documented_exactly_once() -> None:
    document = (ROOT / "docs" / "api-errors.md").read_text()
    rows = re.findall(r"^\| `([A-Z_]+)` \| (\d+) \|", document, flags=re.MULTILINE)
    assert len(rows) == len({code for code, _ in rows}), "a code has two rows"
    documented = {code: int(status) for code, status in rows}
    assert documented == {entry.code: entry.status for entry in error_codes().all()}
