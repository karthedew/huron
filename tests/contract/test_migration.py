"""The migrations build exactly the tables the code describes, and downgrade cleanly."""

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.contract

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_schema_map.py"


def test_schema_map_check_passes() -> None:
    spec = importlib.util.spec_from_file_location("check_schema_map", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.main() == 0
