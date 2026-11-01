"""``huron describe <noun>``: one organization, catalog, namespace, collection or schema."""

from __future__ import annotations

from typing import Annotated

import typer

from huron.applications.cli.commands.common import (
    CollectionArgument,
    api,
    fetch_collection,
    fetch_namespace,
    services,
    show,
)

__all__ = ["describe_app", "register"]

describe_app = typer.Typer(
    help="Show one resource in detail: describe org, catalog, namespace, collection or schema.",
    no_args_is_help=True,
)


def register(app: typer.Typer, panel: str) -> None:
    """Add ``huron describe`` under the help panel ``panel``."""
    app.add_typer(describe_app, name="describe", rich_help_panel=panel)


@describe_app.command("org")
def describe_org(ctx: typer.Context, name: str) -> None:
    """One organization."""
    show(ctx, api(ctx).get(f"/api/v1/organizations/{name}"))


@describe_app.command("catalog")
def describe_catalog(
    ctx: typer.Context,
    name: Annotated[str | None, typer.Argument(help="Defaults to the current catalog.")] = None,
) -> None:
    """One catalog (the current one by default)."""
    target = name or services(ctx).require_catalog()
    show(ctx, api(ctx).get(f"/api/v1/catalogs/{target}"))


@describe_app.command("namespace")
def describe_namespace(
    ctx: typer.Context,
    identifier: Annotated[str, typer.Argument(help="catalog.namespace[.child…]")],
) -> None:
    """One namespace."""
    show(ctx, fetch_namespace(ctx, identifier)[1])


@describe_app.command("collection")
def describe_collection(ctx: typer.Context, identifier: CollectionArgument = None) -> None:
    """One collection (the checked-out one by default)."""
    show(ctx, fetch_collection(ctx, identifier))


@describe_app.command("schema")
def describe_schema(
    ctx: typer.Context,
    schema_id: str,
    resolved: Annotated[bool, typer.Option(help="Compose with everything it extends.")] = False,
) -> None:
    """One schema entry, or its resolved document."""
    suffix = "/resolved" if resolved else ""
    show(ctx, api(ctx).get(f"/api/v1/schemas/{schema_id}{suffix}"))
