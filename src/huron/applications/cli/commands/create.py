"""``huron create <noun>``: organizations, catalogs, namespaces and collections, through the API."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer

from huron.applications.cli.client import if_match
from huron.applications.cli.commands.common import (
    activate,
    api,
    explain_missing_organization,
    read_document,
    say,
    services,
)
from huron.applications.cli.errors import ApiError, UsageError
from huron.applications.cli.identifiers import resolve_collection, resolve_namespace
from huron.applications.cli.sync import checkout, refuse_pending
from huron.applications.cli.walkthrough import fill

__all__ = ["create_app", "register"]

create_app = typer.Typer(
    help="Create an organization, catalog, namespace or collection.",
    no_args_is_help=True,
)


def register(app: typer.Typer, panel: str) -> None:
    """Add ``huron create`` under the help panel ``panel``."""
    app.add_typer(create_app, name="create", rich_help_panel=panel)


@create_app.command("org")
def create_org(
    ctx: typer.Context,
    name: str,
    display_name: Annotated[str, typer.Option(help="A human-readable name.")] = "",
    description: Annotated[str, typer.Option(help="A description of the organization.")] = "",
) -> None:
    """Create an organization (Platform Admin). The API creates its directory on the share.

    The service refuses this command when its configuration declares the organizations. In that
    case, a storage admin prepares their directories with `huron adm provision-orgs`.
    """
    body = {"name": name, "display_name": display_name, "description": description}
    api(ctx).post("/api/v1/organizations", json=body)
    say(ctx, f"organization {name} ready")


@create_app.command("catalog")
def create_catalog(
    ctx: typer.Context,
    name: str,
    organization: Annotated[
        str | None,
        typer.Option(
            "--org",
            help="The organization of the catalog. The default is the current organization.",
        ),
    ] = None,
    schema: Annotated[
        str | None, typer.Option("--schema", help="The ID of the schema to assign.")
    ] = None,
    display_name: Annotated[str, typer.Option(help="A human-readable name.")] = "",
    description: Annotated[str, typer.Option(help="A description of what the catalog holds.")] = "",
) -> None:
    """Create a catalog (Org Admin). The API creates its directory on the share."""
    owner = organization or services(ctx).organization()
    if owner is None:
        raise UsageError(
            "there is no current organization",
            hint="use `--org <org>`, or run `huron org <name>`",
        )
    body = {
        "name": name,
        "schema_id": schema,
        "display_name": display_name,
        "description": description,
    }
    try:
        api(ctx).post(f"/api/v1/organizations/{owner}/catalogs", json=body)
    except ApiError as error:
        explain_missing_organization(ctx, owner, error)
        raise
    say(ctx, f"Catalog {name} is ready. To select it, run `huron catalog {name}`")


@create_app.command("namespace")
def create_namespace(
    ctx: typer.Context,
    identifier: Annotated[str, typer.Argument(help="`catalog.namespace[.child…]`.")],
    allow_collections: Annotated[
        bool,
        typer.Option(
            "--allow-collections", help="Contributors may create collections in this namespace."
        ),
    ] = False,
    parents: Annotated[
        bool, typer.Option("--parents", help="Create missing ancestor namespaces.")
    ] = False,
) -> None:
    """Create a namespace (Catalog Admin). The API creates its directory on the share."""
    parsed = resolve_namespace(identifier, services(ctx).catalog())
    segments = parsed.namespace_path
    for depth in range(1, len(segments)):
        ancestor = ".".join(segments[:depth])
        if parents:
            _create_ancestor(ctx, parsed.catalog, ancestor)
        else:
            api(ctx).get(f"/api/v1/catalogs/{parsed.catalog}/namespaces/{ancestor}")
    view = _create(ctx, parsed.catalog, parsed.namespace, allow_collections)
    say(ctx, f"namespace {view['identifier']} ready")


@create_app.command("collection")
def create_collection(
    ctx: typer.Context,
    identifier: Annotated[str, typer.Argument(help="`catalog.namespace.name`.")],
    metadata: Annotated[
        Path | None,
        typer.Option(
            "--metadata", help="Read the metadata from this JSON file. Do not ask for each field."
        ),
    ] = None,
    draft: Annotated[
        bool, typer.Option("--draft", help="Stop before the CLI activates the collection.")
    ] = False,
) -> None:
    """Reserve a collection, fill its metadata, then activate it.

    The API creates the directory of the collection and writes `metadata.json` in it.
    """
    found = services(ctx)
    parsed = resolve_collection(identifier, found.catalog())
    document = read_document(metadata) if metadata else None
    base = f"/api/v1/catalogs/{parsed.catalog}/namespaces/{parsed.namespace}"
    refuse_pending(found)
    collection = api(ctx).post(
        f"{base}/collections", json={"name": parsed.name, "metadata": document}
    )
    if document is None:
        collection = _walk_through(ctx, collection)
    if draft:
        checkout(found, collection)
        say(
            ctx,
            f"Draft {collection['identifier']} is reserved."
            " To activate it, run `huron activate collection`",
        )
        return
    activated = activate(ctx, collection)
    say(ctx, f"collection {activated['identifier']} is active at {activated['path']}")


def _walk_through(ctx: typer.Context, collection: dict[str, Any]) -> dict[str, Any]:
    schema = api(ctx).get(f"/api/v1/collections/{collection['id']}/schema")
    filled = fill(services(ctx).prompter, schema, collection["metadata"])
    updated: dict[str, Any] = api(ctx).patch(
        f"/api/v1/collections/{collection['id']}",
        json={"metadata": filled},
        headers=if_match(collection["version"]),
    )
    return updated


def _create(ctx: typer.Context, catalog: str, path: str, allow: bool) -> dict[str, object]:
    parent, _, name = path.rpartition(".")
    view: dict[str, object] = api(ctx).post(
        f"/api/v1/catalogs/{catalog}/namespaces",
        json={"parent": parent, "name": name, "collections_allowed": allow},
    )
    return view


def _create_ancestor(ctx: typer.Context, catalog: str, path: str) -> None:
    """Create the ancestor namespace ``path``, unless it exists."""
    try:
        _create(ctx, catalog, path, False)
    except ApiError as error:
        if error.code != "NAME_TAKEN":
            raise
