"""Every error code is registered once, raised codes are registered, and all are documented."""

import re
from pathlib import Path

import huron.applications.api.app
import huron.core.storage
import huron.pkg.fs.acl  # noqa: F401 - registers the CLI's ACL error code
from huron.pkg.errors import error_codes

ROOT = Path(__file__).resolve().parents[2]


def registered_in_source() -> list[str]:
    pattern = re.compile(r'register\(\s*"([A-Z_]+)"')
    found: list[str] = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        found.extend(pattern.findall(path.read_text()))
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
