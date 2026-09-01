"""Fail when `migrations/schema.sql` is not stamped to the Alembic head.

`migrations/schema.sql` is a hand-maintained map of the metastore, not
generated output, so nothing keeps it current except review discipline given
teeth by this check: its `-- Reflects: <revision>` line must name the same
revision as the Alembic chain's current head. The comparison never opens a
database connection or executes `migrations/env.py` - it reads the head from
the revision files under `migrations/versions/` and the stamp from the map's
own header text.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.util import CommandError

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_MAP_PATH = REPO_ROOT / "migrations" / "schema.sql"
ALEMBIC_INI_PATH = REPO_ROOT / "alembic.ini"

_HEADER_LINES_READ = 30
_REFLECTS_LINE = re.compile(r"^-- Reflects: (\S+)\s*$")


class SchemaMapStampError(ValueError):
    """The map's `-- Reflects:` line is missing or malformed."""


def reflected_revision(text: str) -> str:
    """Return the revision id named by `text`'s `-- Reflects:` line.

    Reads only the first `_HEADER_LINES_READ` lines, matching the header
    window the map's own obligation names. Raises `SchemaMapStampError` when
    no such line is present there.
    """
    header = text.splitlines()[:_HEADER_LINES_READ]
    for line in header:
        match = _REFLECTS_LINE.match(line)
        if match is not None:
            return match.group(1)
    raise SchemaMapStampError(
        f"no '-- Reflects: <revision>' line in the first {_HEADER_LINES_READ} lines"
    )


def main(schema_map_path: Path | None = None, head: str | None = None) -> int:
    """Compare the map's stamp against the Alembic head; print and fail on drift.

    `schema_map_path` and `head` let a caller supply both independently of
    the real repository, which is how the unit tests pin this contract
    without reading `migrations/versions/`. Left `None`, each is resolved
    from this repository: the map from `SCHEMA_MAP_PATH`, the head from
    `ScriptDirectory.from_config(Config(ALEMBIC_INI_PATH)).get_current_head()`.
    """
    path = SCHEMA_MAP_PATH if schema_map_path is None else schema_map_path
    try:
        stamp = reflected_revision(path.read_text())
    except SchemaMapStampError as exc:
        print(f"{path}: {exc}", file=sys.stderr)
        return 1

    if head is None:
        config = Config(str(ALEMBIC_INI_PATH))
        try:
            script_dir = ScriptDirectory.from_config(config)
            head = script_dir.get_current_head()
        except CommandError as exc:
            print(f"alembic revision graph: {exc}", file=sys.stderr)
            return 1
        if head is None:
            print("alembic revision graph has no head", file=sys.stderr)
            return 1

    if stamp != head:
        print(f"migrations/schema.sql Reflects: {stamp}", file=sys.stderr)
        print(f"alembic head:                  {head}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
