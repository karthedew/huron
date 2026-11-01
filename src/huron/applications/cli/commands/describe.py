"""``huron describe <noun>``: one organization, catalog, namespace, collection or schema."""

from __future__ import annotations

from typing import Annotated

import typer

from huron.applications.cli.commands.common import (
    CollectionArgument,
    api,
    fetch_catalog,
    fetch_collection,
    fetch_namespace,
    services,
    show,
)

__all__ = ["describe_app", "register"]

describe_app = typer.Typer(
    help="Show the details of one organization, catalog, namespace, collection or schema.",
    no_args_is_help=True,
)


def register(app: typer.Typer, panel: str) -> None:
    """Add ``huron describe`` under the help panel ``panel``."""
    app.add_typer(describe_app, name="describe", rich_help_panel=panel)


@describe_app.command("org")
def describe_org(ctx: typer.Context, name: str) -> None:
    """Show one organization."""
    show(ctx, api(ctx).get(f"/api/v1/organizations/{name}"))


@describe_app.command("catalog")
def describe_catalog(
    ctx: typer.Context,
    name: Annotated[str | None, typer.Argument(help="The default is the current catalog.")] = None,
) -> None:
    """Show one catalog. The default is the current catalog."""
    target = name or services(ctx).require_catalog()
    show(ctx, fetch_catalog(ctx, target))


@describe_app.command("namespace")
def describe_namespace(
    ctx: typer.Context,
    identifier: Annotated[str, typer.Argument(help="`catalog.namespace[.child…]`.")],
) -> None:
    """Show one namespace."""
    show(ctx, fetch_namespace(ctx, identifier)[1])


@describe_app.command("collection")
def describe_collection(ctx: typer.Context, identifier: CollectionArgument = None) -> None:
    """Show one collection. The default is the current collection."""
    show(ctx, fetch_collection(ctx, identifier))


@describe_app.command("schema")
def describe_schema(
    ctx: typer.Context,
    schema_id: str,
    resolved: Annotated[
        bool, typer.Option(help="Show the schema combined with all schemas that it extends.")
    ] = False,
) -> None:
    """Show one schema entry, or its resolved document."""
    suffix = "/resolved" if resolved else ""
    show(ctx, api(ctx).get(f"/api/v1/schemas/{schema_id}{suffix}"))
