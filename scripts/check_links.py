"""Fail when a Markdown file links to a relative path that does not exist.

Usage: ``python scripts/check_links.py README.md docs``.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterator
from pathlib import Path

LINK = re.compile(r"\]\(([^)\s]+)\)")


def broken_links(paths: list[Path]) -> Iterator[str]:
    """``file: target`` for every relative link whose target is missing."""
    for path in _markdown(paths):
        for target in LINK.findall(path.read_text()):
            if "://" in target or target.startswith(("#", "mailto:")):
                continue
            relative = target.split("#", 1)[0]
            if relative and not (path.parent / relative).exists():
                yield f"{path}: {target}"


def main(argv: list[str]) -> int:
    """Print broken links; exit 1 when there are any."""
    broken = list(broken_links([Path(arg) for arg in argv]))
    for line in broken:
        print(line)
    return 1 if broken else 0


def _markdown(paths: list[Path]) -> Iterator[Path]:
    for path in paths:
        if path.is_dir():
            yield from sorted(path.rglob("*.md"))
        else:
            yield path


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
