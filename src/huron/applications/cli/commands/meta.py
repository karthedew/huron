"""``huron meta``: edit, validate and publish a collection's metadata and schema override."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer

from huron.applications.cli.client import if_match
from huron.applications.cli.commands.collections import fetch_collection
from huron.applications.cli.commands.common import api, say, services, show
from huron.applications.cli.commands.schemas import read_document
from huron.applications.cli.errors import CliError, ExitCode, UsageError
from huron.applications.cli.mount import Mount
from huron.applications.cli.sync import checkout, write_sidecar
from huron.applications.cli.walkthrough import fill, merge_diff, review
from huron.schema.validator import SchemaInvalid, check_schema_document

__all__ = ["register"]

meta_app = typer.Typer(help="Collection metadata.", no_args_is_help=True)
override_app = typer.Typer(help="A collection's schema override.", no_args_is_help=True)
meta_app.add_typer(override_app, name="override")

Identifier = Annotated[str | None, typer.Argument(help="Defaults to the checked-out collection.")]


def register(app: typer.Typer) -> None:
    """Add ``huron meta``."""
    app.add_typer(meta_app, name="meta")


@meta_app.command("show")
def meta_show(ctx: typer.Context, identifier: Identifier = None) -> None:
    """The collection's metadata, and the local draft when there is one."""
    collection = fetch_collection(ctx, identifier)
    draft = services(ctx).state.read_draft(str(collection["id"]))
    show(
        ctx,
        {
            "metadata": collection["metadata"],
            "draft": draft,
            "schema_override": collection["schema_override"],
        },
    )


@meta_app.command("edit")
def meta_edit(ctx: typer.Context, identifier: Identifier = None) -> None:
    """Walk through the schema, starting from the draft or the published metadata."""
    collection = fetch_collection(ctx, identifier)
    found = services(ctx)
    start = found.state.read_draft(str(collection["id"])) or collection["metadata"]
    schema = api(ctx).get(f"/api/v1/collections/{collection['id']}/schema")
    draft = fill(found.prompter, schema, start)
    found.state.write_draft(str(collection["id"]), draft)
    problems = review(schema, draft)
    say(ctx, f"draft saved ({len(problems)} problems); publish with: huron meta publish")


@meta_app.command("init")
def meta_init(ctx: typer.Context, identifier: Identifier = None) -> None:
    """Walk through the schema from an empty document."""
    collection = fetch_collection(ctx, identifier)
    found = services(ctx)
    schema = api(ctx).get(f"/api/v1/collections/{collection['id']}/schema")
    found.state.write_draft(str(collection["id"]), fill(found.prompter, schema, {}))
    say(ctx, "draft saved; publish with: huron meta publish")


@meta_app.command("validate")
def meta_validate(ctx: typer.Context, identifier: Identifier = None) -> None:
    """Check the draft (or the published metadata) against the collection's schema."""
    collection = fetch_collection(ctx, identifier)
    document = services(ctx).state.read_draft(str(collection["id"])) or collection["metadata"]
    schema = api(ctx).get(f"/api/v1/collections/{collection['id']}/schema")
    problems = review(schema, document)
    if problems:
        raise CliError(
            f"{len(problems)} problems",
            ExitCode.VALIDATION,
            problem={"context": {"problems": [p.as_dict() for p in problems]}},
        )
    say(ctx, "metadata is valid")


@meta_app.command("publish")
def meta_publish(ctx: typer.Context, identifier: Identifier = None) -> None:
    """Send the draft as a merge patch and rewrite ``metadata.json`` on the share."""
    collection = fetch_collection(ctx, identifier)
    draft = services(ctx).state.read_draft(str(collection["id"]))
    if draft is None:
        raise UsageError("there is no draft", hint="run: huron meta edit")
    updated = _patch(ctx, collection, {"metadata": merge_diff(collection["metadata"], draft)})
    services(ctx).state.delete_draft(str(collection["id"]))
    say(ctx, f"published {updated['identifier']} at version {updated['version']}")


@override_app.command("set")
def override_set(ctx: typer.Context, file: Path, identifier: Identifier = None) -> None:
    """Set the collection's schema override, together with the metadata draft if any."""
    document = read_document(file)
    try:
        check_schema_document(document)
    except SchemaInvalid as error:
        raise CliError(
            error.message, ExitCode.VALIDATION, code=error.code, problem=error.problem()
        ) from error
    collection = fetch_collection(ctx, identifier)
    body: dict[str, Any] = {"schema_override": document}
    draft = services(ctx).state.read_draft(str(collection["id"]))
    if draft is not None:
        body["metadata"] = merge_diff(collection["metadata"], draft)
    updated = _patch(ctx, collection, body)
    services(ctx).state.delete_draft(str(collection["id"]))
    say(ctx, f"override set on {updated['identifier']}")


@override_app.command("clear")
def override_clear(ctx: typer.Context, identifier: Identifier = None) -> None:
    """Remove the collection's schema override."""
    collection = fetch_collection(ctx, identifier)
    updated = _patch(ctx, collection, {"schema_override": None})
    say(ctx, f"override cleared on {updated['identifier']}")


def _patch(ctx: typer.Context, collection: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    found = services(ctx)
    updated: dict[str, Any] = api(ctx).patch(
        f"/api/v1/collections/{collection['id']}",
        json=body,
        headers=if_match(int(collection["version"])),
    )
    if updated.get("path") is not None:
        write_sidecar(found, Mount(found), updated)
    copy = found.state.read_copy(str(collection["id"]))
    if copy is not None and copy.version == int(collection["version"]):
        checkout(found, updated)
    return updated
