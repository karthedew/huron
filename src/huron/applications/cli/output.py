"""Render results as a table, JSON or YAML."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import yaml
from rich.console import Console, OverflowMethod
from rich.table import Table

__all__ = ["Column", "OutputFormat", "human_size", "render", "render_one"]


class OutputFormat(StrEnum):
    """The ``-o`` choices."""

    TABLE = "table"
    JSON = "json"
    YAML = "yaml"


@dataclass(frozen=True, slots=True)
class Column:
    """A table column: its header, how to read the value from a row, and how a long value wraps.

    ``overflow`` is Rich's: ``ellipsis`` cuts the end off, ``fold`` wraps it onto further lines.
    """

    header: str
    value: Callable[[Mapping[str, Any]], Any]
    overflow: OverflowMethod = "ellipsis"


def render(
    console: Console,
    rows: Iterable[Mapping[str, Any]],
    columns: Sequence[Column],
    fmt: OutputFormat,
) -> None:
    """Print rows in the chosen format; JSON and YAML print the full rows."""
    items = list(rows)
    if fmt is OutputFormat.JSON:
        console.print_json(json.dumps(items, default=str))
        return
    if fmt is OutputFormat.YAML:
        console.print(yaml.safe_dump(items, sort_keys=False), end="", markup=False)
        return
    table = Table(box=None, pad_edge=False, header_style="bold")
    for column in columns:
        table.add_column(column.header, overflow=column.overflow)
    for item in items:
        table.add_row(*(_text(column.value(item)) for column in columns))
    console.print(table)


def render_one(console: Console, item: Mapping[str, Any], fmt: OutputFormat) -> None:
    """Print one object: key/value lines, or JSON/YAML."""
    if fmt is OutputFormat.JSON:
        console.print_json(json.dumps(item, default=str))
        return
    if fmt is OutputFormat.YAML:
        console.print(yaml.safe_dump(dict(item), sort_keys=False), end="", markup=False)
        return
    width = max((len(key) for key in item), default=0)
    for key, value in item.items():
        console.print(f"{key.ljust(width)}  {_text(value)}", markup=False, highlight=False)


def human_size(size: int) -> str:
    """``size`` bytes for people: ``512 B``, ``1.5 KiB``, ``2.0 GiB`` (binary units)."""
    if size < 1024:
        return f"{size} B"
    value = float(size)
    for unit in _UNITS:
        value /= 1024
        if round(value, 1) < 1024 or unit == _UNITS[-1]:
            break
    return f"{value:.1f} {unit}"


_UNITS = ("KiB", "MiB", "GiB", "TiB", "PiB")


def _text(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, dict | list):
        return json.dumps(value, sort_keys=True)
    return str(value)
