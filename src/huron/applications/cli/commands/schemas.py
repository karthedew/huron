"""``huron schema``: the metadata schema registry."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from huron.applications.cli.commands.common import api, say, show, show_list
from huron.applications.cli.errors import UsageError
from huron.applications.cli.output import Column

__all__ = ["read_document", "register"]

schema_app = typer.Typer(help="Metadata schemas.", no_args_is_help=True)

COLUMNS = [
    Column("ID", lambda s: s["id"]),
    Column("NAME", lambda s: s["name"]),
    Column("VERSION", lambda s: s["version"]),
    Column("SCOPE", lambda s: s["scope"]),
    Column("EXTENDS", lambda s: s["extends_id"]),
]


def register(app: typer.Typer) -> None:
    """Add ``huron schema``."""
    app.add_typer(schema_app, name="schema")


@schema_app.command("list")
def schema_list(
    ctx: typer.Context, organization: Annotated[str | None, typer.Argument()] = None
) -> None:
    """Schemas of an organization, or the platform's when none is named."""
    path = (
        f"/api/v1/organizations/{organization}/schemas"
        if organization
        else "/api/v1/platform/schemas"
    )
    show_list(ctx, api(ctx).pages(path), COLUMNS)


@schema_app.command("show")
def schema_show(
    ctx: typer.Context,
    schema_id: str,
    resolved: Annotated[bool, typer.Option(help="Compose with everything it extends.")] = False,
) -> None:
    """One schema entry, or its resolved document."""
    suffix = "/resolved" if resolved else ""
    show(ctx, api(ctx).get(f"/api/v1/schemas/{schema_id}{suffix}"))


@schema_app.command("publish")
def schema_publish(
    ctx: typer.Context,
    organization: Annotated[str, typer.Argument(help="Organization, or 'platform'.")],
    name: str,
    file: Path,
    extends: Annotated[str | None, typer.Option("--extends", help="Schema id it extends.")] = None,
) -> None:
    """Publish the next version of a named schema from a JSON file."""
    document = read_document(file)
    body = {"name": name, "extends_id": extends, "document": document}
    path = (
        "/api/v1/platform/schemas"
        if organization == "platform"
        else f"/api/v1/organizations/{organization}/schemas"
    )
    entry = api(ctx).post(path, json=body)
    say(ctx, f"published {entry['name']} v{entry['version']} ({entry['id']})")


@schema_app.command("assign")
def schema_assign(ctx: typer.Context, catalog: str, schema_id: str) -> None:
    """Assign a schema to a catalog and re-validate its collections."""
    result = api(ctx).put(f"/api/v1/catalogs/{catalog}/schema", json={"schema_id": schema_id})
    counts = result["recompute"]
    say(
        ctx,
        f"{catalog} now uses {result['assigned']['schema']['name']}"
        f" v{result['assigned']['schema']['version']}:"
        f" {counts['active']} active, {counts['incomplete']} incomplete,"
        f" {counts['changed']} changed",
    )


def read_document(path: Path) -> dict[str, object]:
    """A JSON object from ``path``."""
    try:
        document = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise UsageError(f"cannot read {path}: {error}") from error
    if not isinstance(document, dict):
        raise UsageError(f"{path} must hold a JSON object")
    return document
