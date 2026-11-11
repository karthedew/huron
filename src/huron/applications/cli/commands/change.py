"""``activate``, ``edit``, ``validate``, ``publish``, ``set`` and ``unset``: change what exists."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any

import typer

from huron.applications.cli.client import if_match
from huron.applications.cli.commands.common import (
    CollectionArgument,
    activate,
    api,
    fetch_collection,
    fetch_namespace,
    read_document,
    say,
    services,
)
from huron.applications.cli.errors import CliError, ExitCode, UsageError
from huron.applications.cli.sync import checkout
from huron.applications.cli.walkthrough import fill, merge_diff, review
from huron.schema.validator import SchemaInvalid, check_schema_document

__all__ = [
    "activate_app",
    "edit_app",
    "publish_app",
    "register",
    "set_app",
    "unset_app",
    "validate_app",
]

activate_app = typer.Typer(help="Activate a draft collection.", no_args_is_help=True)
edit_app = typer.Typer(help="Edit the metadata draft of a collection.", no_args_is_help=True)
validate_app = typer.Typer(help="Check a metadata draft against its schema.", no_args_is_help=True)
publish_app = typer.Typer(help="Publish a metadata draft.", no_args_is_help=True)
set_app = typer.Typer(
    help="Set the schema override of a collection, or the settings of a namespace.",
    no_args_is_help=True,
)
unset_app = typer.Typer(help="Clear the schema override of a collection.", no_args_is_help=True)


def register(app: typer.Typer, panels: Mapping[str, str]) -> None:
    """Add the change verbs, each under its help panel in ``panels`` (verb to panel)."""
    for name, verb in (
        ("activate", activate_app),
        ("edit", edit_app),
        ("validate", validate_app),
        ("publish", publish_app),
        ("set", set_app),
        ("unset", unset_app),
    ):
        app.add_typer(verb, name=name, rich_help_panel=panels[name])


@activate_app.command("collection")
def activate_collection(ctx: typer.Context, identifier: CollectionArgument = None) -> None:
    """Activate a draft collection. The API creates its directory and writes `metadata.json`."""
    collection = fetch_collection(ctx, identifier)
    activated = activate(ctx, collection)
    say(ctx, f"collection {activated['identifier']} is active at {activated['path']}")


@edit_app.command("meta")
def edit_meta(
    ctx: typer.Context,
    identifier: CollectionArgument = None,
    from_scratch: Annotated[
        bool,
        typer.Option("--from-scratch", help="Start from an empty document."),
    ] = False,
    file: Annotated[
        Path | None,
        typer.Option("--file", help="Use this JSON document as the draft. Do not ask questions."),
    ] = None,
) -> None:
    """Ask for each field of the schema. Start from the draft or the published metadata.

    With `--file`, the CLI asks no questions. The JSON document becomes the draft without
    changes.
    """
    if file is not None and from_scratch:
        raise UsageError("use `--file` or `--from-scratch`, not both")
    document = None if file is None else read_document(file)
    collection = fetch_collection(ctx, identifier)
    found = services(ctx)
    schema = api(ctx).get(f"/api/v1/collections/{collection['id']}/schema")
    if document is None:
        start = (
            {}
            if from_scratch
            else found.state.read_draft(str(collection["id"])) or collection["metadata"]
        )
        draft = fill(found.prompter, schema, start)
    else:
        draft = document
    found.state.write_draft(str(collection["id"]), draft)
    problems = review(schema, draft)
    say(
        ctx,
        f"Draft saved with {len(problems)} problems. To publish it, run `huron publish meta`",
    )


@validate_app.command("meta")
def validate_meta(ctx: typer.Context, identifier: CollectionArgument = None) -> None:
    """Check the draft against the schema of the collection.

    With no draft, check the published metadata.
    """
    collection = fetch_collection(ctx, identifier)
    draft = services(ctx).state.read_draft(str(collection["id"]))
    document = draft or collection["metadata"]
    checked = "the draft" if draft else "the published metadata"
    schema = api(ctx).get(f"/api/v1/collections/{collection['id']}/schema")
    problems = review(schema, document)
    if problems:
        raise CliError(
            f"{checked} has {len(problems)} problems",
            ExitCode.VALIDATION,
            problem={"context": {"problems": [p.as_dict() for p in problems]}},
        )
    say(ctx, "The metadata is valid")


@publish_app.command("meta")
def publish_meta(ctx: typer.Context, identifier: CollectionArgument = None) -> None:
    """Send the draft as a merge patch. The API writes `metadata.json` on the share."""
    collection = fetch_collection(ctx, identifier)
    draft = services(ctx).state.read_draft(str(collection["id"]))
    if draft is None:
        raise UsageError("there is no draft", hint="run `huron edit meta`")
    updated = _patch(ctx, collection, {"metadata": merge_diff(collection["metadata"], draft)})
    services(ctx).state.delete_draft(str(collection["id"]))
    say(ctx, f"published {updated['identifier']} at version {updated['version']}")


@set_app.command("override")
def set_override(
    ctx: typer.Context,
    file: Annotated[Path, typer.Argument(help="A JSON Schema document.")],
    identifier: CollectionArgument = None,
) -> None:
    """Set the schema override of the collection. Send the metadata draft too, if one exists."""
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
    say(ctx, f"schema override set on {updated['identifier']}")


@set_app.command("namespace")
def set_namespace(
    ctx: typer.Context,
    identifier: Annotated[str, typer.Argument(help="`catalog.namespace[.child…]`.")],
    allow_collections: Annotated[
        bool,
        typer.Option(
            "--allow-collections/--no-allow-collections",
            help="Allow or forbid collections in this namespace.",
        ),
    ],
) -> None:
    """Allow or forbid collections in a namespace. The mode of its directory stays the same."""
    parsed, _ = fetch_namespace(ctx, identifier)
    view = api(ctx).patch(
        f"/api/v1/catalogs/{parsed.catalog}/namespaces/{parsed.namespace}",
        json={"collections_allowed": allow_collections},
    )
    state = "allows" if allow_collections else "does not allow"
    say(ctx, f"namespace {view['identifier']} {state} collections")


@unset_app.command("override")
def unset_override(ctx: typer.Context, identifier: CollectionArgument = None) -> None:
    """Clear the schema override of the collection."""
    collection = fetch_collection(ctx, identifier)
    updated = _patch(ctx, collection, {"schema_override": None})
    say(ctx, f"schema override cleared on {updated['identifier']}")


def _patch(ctx: typer.Context, collection: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    found = services(ctx)
    updated: dict[str, Any] = api(ctx).patch(
        f"/api/v1/collections/{collection['id']}",
        json=body,
        headers=if_match(int(collection["version"])),
    )
    with found.state.locked():
        copy = found.state.working(str(collection["id"]))
        if copy is not None and copy.base_version == int(collection["version"]):
            checkout(found, updated)
    return updated
