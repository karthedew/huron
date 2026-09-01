"""Pin `scripts/check_schema_map.py`'s contract against fixture headers only.

`scripts/` is not a package, so the module is loaded by file path rather than
import. Every assertion here is built from a header written inside the test;
none reads the real `migrations/schema.sql` or `migrations/versions/` - see
the module's own docstring for why a fixture-only suite is the hermetic
choice for this check.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from types import ModuleType

pytestmark = pytest.mark.unit

_MODULE_PATH = Path(__file__).resolve().parent.parent.parent / "scripts" / "check_schema_map.py"


def _load_check_schema_map() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_schema_map", _MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check_schema_map = _load_check_schema_map()


def test_reflected_revision_parses_the_named_stamp() -> None:
    header = (
        "-- Huron metastore: table architecture summary\n-- Reflects: 0008_schema_conformance\n--\n"
    )

    assert check_schema_map.reflected_revision(header) == "0008_schema_conformance"


def test_main_exits_nonzero_when_stamp_names_a_revision_other_than_the_head(
    tmp_path: Path,
) -> None:
    schema_map = tmp_path / "schema.sql"
    schema_map.write_text("-- Reflects: 0006_role_simplification\n")

    exit_code = check_schema_map.main(
        schema_map_path=schema_map, head="0007_roleless_service_accounts"
    )

    assert exit_code != 0


def test_main_exits_nonzero_when_the_header_has_no_reflects_line(tmp_path: Path) -> None:
    schema_map = tmp_path / "schema.sql"
    schema_map.write_text("-- Huron metastore: table architecture summary\n-- no stamp here\n")

    exit_code = check_schema_map.main(
        schema_map_path=schema_map, head="0007_roleless_service_accounts"
    )

    assert exit_code != 0
