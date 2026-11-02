"""Write the OpenAPI document: ``python -m huron.applications.api.openapi docs/openapi.json``."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from huron.applications.api.app import create_app

__all__ = ["document", "main"]


def document() -> dict[str, Any]:
    """The application's OpenAPI document."""
    return create_app().openapi()


def main(argv: list[str] | None = None) -> int:
    """Write the document to the path given, or to standard output."""
    args = sys.argv[1:] if argv is None else argv
    text = json.dumps(document(), indent=2, sort_keys=True) + "\n"
    if args:
        Path(args[0]).write_text(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
