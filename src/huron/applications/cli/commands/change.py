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
    kind_of,
    read_document,
    say,
    services,
)
from huron.applications.cli.errors import CliError, ExitCode, UsageError
from huron.applications.cli.sync import checkout, write_sidecar
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
edit_app = typer.Typer(help="Edit a collection's metadata draft.", no_args_is_help=True)
validate_app = typer.Typer(help="Check a metadata draft against its schema.", no_args_is_help=True)
publish_app = typer.Typer(help="Publish a metadata draft.", no_args_is_help=True)
set_app = typer.Typer(
    help="Set a collection's schema override or a namespace's settings.", no_args_is_help=True
)
unset_app = typer.Typer(help="Remove a collection's schema override.", no_args_is_help=True)


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
    """Create the directory of a draft and activate it."""
    collection = fetch_collection(ctx, identifier)
    activated = activate(ctx, collection, services(ctx).mount())
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
        typer.Option("--file", help="Take the draft from this JSON document instead of asking."),
    ] = None,
) -> None:
    """Walk through the schema, starting from the draft or the published metadata.

    With --file nothing is asked: the JSON document becomes the draft as it is.
    """
    if file is not None and from_scratch:
        raise UsageError("--file and --from-scratch cannot be combined")
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
    say(ctx, f"draft saved ({len(problems)} problems); publish with: huron publish meta")


@validate_app.command("meta")
def validate_meta(ctx: typer.Context, identifier: CollectionArgument = None) -> None:
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


@publish_app.command("meta")
def publish_meta(ctx: typer.Context, identifier: CollectionArgument = None) -> None:
    """Send the draft as a merge patch and rewrite ``metadata.json`` on the share."""
    collection = fetch_collection(ctx, identifier)
    draft = services(ctx).state.read_draft(str(collection["id"]))
    if draft is None:
        raise UsageError("there is no draft", hint="run: huron edit meta")
    updated = _patch(ctx, collection, {"metadata": merge_diff(collection["metadata"], draft)})
    services(ctx).state.delete_draft(str(collection["id"]))
    say(ctx, f"published {updated['identifier']} at version {updated['version']}")


@set_app.command("override")
def set_override(
    ctx: typer.Context,
    file: Annotated[Path, typer.Argument(help="A JSON Schema document.")],
    identifier: CollectionArgument = None,
) -> None:
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


@set_app.command("namespace")
def set_namespace(
    ctx: typer.Context,
    identifier: Annotated[str, typer.Argument(help="catalog.namespace[.child…]")],
    allow_collections: Annotated[
        bool,
        typer.Option("--allow-collections/--no-allow-collections", help="Allow collections here."),
    ],
) -> None:
    """Allow or forbid collections, and re-apply the directory's ACL plan."""
    mount = services(ctx).mount()
    parsed, before = fetch_namespace(ctx, identifier)
    mount.path(str(before["disk_path"]))  # refuse before any change when the share is not ours
    view = api(ctx).patch(
        f"/api/v1/catalogs/{parsed.catalog}/namespaces/{parsed.namespace}",
        json={"collections_allowed": allow_collections},
    )
    mount.apply(view["disk_path"], kind_of(view), mount.catalog_groups(parsed.catalog))
    state = "allows" if allow_collections else "does not allow"
    say(ctx, f"namespace {view['identifier']} {state} collections")


@unset_app.command("override")
def unset_override(ctx: typer.Context, identifier: CollectionArgument = None) -> None:
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
        write_sidecar(found, found.mount(), updated)
    copy = found.state.read_copy(str(collection["id"]))
    if copy is not None and copy.version == int(collection["version"]):
        checkout(found, updated)
    return updated
