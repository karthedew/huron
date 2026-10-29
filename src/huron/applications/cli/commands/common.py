"""Helpers every command module uses."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

import typer

from huron.applications.cli.client import ApiClient
from huron.applications.cli.output import Column, render, render_one
from huron.applications.cli.services import Services

__all__ = ["api", "say", "services", "show", "show_list"]


def services(ctx: typer.Context) -> Services:
    """The services the root command was given."""
    found: Services = ctx.obj
    return found


def api(ctx: typer.Context) -> ApiClient:
    """The authenticated API client."""
    return services(ctx).api()


def show_list(
    ctx: typer.Context, rows: Iterable[Mapping[str, Any]], columns: Sequence[Column]
) -> None:
    """Print rows in the chosen output format."""
    found = services(ctx)
    render(found.out, rows, columns, found.output)


def show(ctx: typer.Context, item: Mapping[str, Any]) -> None:
    """Print one object in the chosen output format."""
    found = services(ctx)
    render_one(found.out, item, found.output)


def say(ctx: typer.Context, message: str) -> None:
    """A plain progress or result line on standard output (not in JSON or YAML mode)."""
    found = services(ctx)
    if found.output.value == "table":
        found.out.print(message, markup=False, highlight=False)
