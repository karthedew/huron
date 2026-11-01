"""``huron tree`` and ``huron search``: find collections in the current catalog."""

from __future__ import annotations

from typing import Annotated

import typer

from huron.applications.cli.commands.common import (
    COLLECTION_COLUMNS,
    api,
    fetch_namespace,
    say,
    services,
    show,
    show_list,
    table_mode,
)
from huron.applications.cli.tree import build_tree, render_tree

__all__ = ["register", "search", "tree"]


def register(app: typer.Typer, panel: str) -> None:
    """Add ``huron tree`` and ``huron search`` under the help panel ``panel``."""
    app.command("tree", rich_help_panel=panel)(tree)
    app.command("search", rich_help_panel=panel)(search)


def tree(
    ctx: typer.Context,
    namespace: Annotated[
        str | None, typer.Argument(help="Show only the subtree below this namespace.")
    ] = None,
) -> None:
    """Show the namespace tree of the current catalog, with its collections as leaves."""
    found = services(ctx)
    if namespace is None:
        built = build_tree(api(ctx), found.require_catalog())
    else:
        parsed, view = fetch_namespace(ctx, namespace)
        built = build_tree(api(ctx), parsed.catalog, view)
    if not table_mode(ctx):
        show(ctx, built)
        return
    found.out.print(render_tree(built), highlight=False)
    if not built["namespaces"] and not built["collections"]:
        say(
            ctx,
            "There is nothing here yet."
            " To create a namespace, run `huron create namespace <identifier>`",
        )
    else:
        say(ctx, "To select a collection, run `huron checkout <COLLECTION>`")


def search(
    ctx: typer.Context,
    query: Annotated[
        str | None, typer.Option("-q", "--query", help="Search for this text.")
    ] = None,
    label: Annotated[
        list[str] | None, typer.Option("-l", "--label", help="A label, as `key=value`.")
    ] = None,
    state: Annotated[
        list[str] | None,
        typer.Option("--state", help="A collection state: `draft`, `active` or `incomplete`."),
    ] = None,
) -> None:
    """Search the current catalog by text, labels and state."""
    target = services(ctx).require_catalog()
    params: dict[str, object] = {}
    if query:
        params["q"] = query
    if label:
        params["label"] = label
    if state:
        params["state"] = state
    show_list(ctx, api(ctx).pages(f"/api/v1/catalogs/{target}/search", params), COLLECTION_COLUMNS)
