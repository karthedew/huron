"""``huron delete <noun>``: organizations, catalogs, namespaces and collections, through the API."""

from __future__ import annotations

from dataclasses import replace
from typing import Annotated, Any

import typer

from huron.applications.cli.client import if_match
from huron.applications.cli.commands.common import (
    api,
    fetch_catalog,
    fetch_collection,
    fetch_namespace,
    say,
    services,
)
from huron.applications.cli.errors import ApiError, CliError, ExitCode
from huron.applications.cli.sync import recorded_files

__all__ = ["DECLARED_HINT", "delete_app", "register"]

DECLARED_HINT = (
    "the service configuration declares this organization. First delete its entry from the"
    " service configuration. Then, when it has no catalogs, delete it here"
)

delete_app = typer.Typer(
    help="Delete an empty organization, catalog or namespace, or a collection and its files.",
    no_args_is_help=True,
)


def register(app: typer.Typer, panel: str) -> None:
    """Add ``huron delete`` under the help panel ``panel``."""
    app.add_typer(delete_app, name="delete", rich_help_panel=panel)


@delete_app.command("org")
def delete_org(ctx: typer.Context, name: str) -> None:
    """Delete an organization that has no catalogs. The API deletes its empty directory.

    The service refuses to delete a declared organization. Instead, delete it from the service
    configuration. The directory of an organization with a root stays for its storage admin.
    """
    found = services(ctx)
    directory = api(ctx).get(f"/api/v1/organizations/{name}").get("path")
    try:
        api(ctx).delete(f"/api/v1/organizations/{name}")
    except ApiError as error:
        if error.code == "ORGANIZATION_DECLARED":
            error.hint = DECLARED_HINT
        raise
    say(ctx, f"organization {name} deleted")
    if directory is not None:
        say(ctx, f"Its directory {directory} stays. Its storage admin deletes the directory")
    if found.organization() == name:
        found.save_config(replace(found.config, current_organization=None))
        say(
            ctx,
            "There is no current organization now. To select one, run `huron org <name>`",
        )


@delete_app.command("catalog")
def delete_catalog(ctx: typer.Context, name: str) -> None:
    """Delete a catalog that has no namespaces. The API deletes its empty directory."""
    fetch_catalog(ctx, name)
    api(ctx).delete(f"/api/v1/catalogs/{name}")
    say(ctx, f"catalog {name} deleted")


@delete_app.command("namespace")
def delete_namespace(ctx: typer.Context, identifier: str) -> None:
    """Delete an empty namespace. The API deletes its empty directory."""
    parsed, view = fetch_namespace(ctx, identifier)
    api(ctx).delete(f"/api/v1/catalogs/{parsed.catalog}/namespaces/{parsed.namespace}")
    say(ctx, f"namespace {view['identifier']} deleted")


@delete_app.command("collection")
def delete_collection(
    ctx: typer.Context,
    identifier: str,
    yes: Annotated[bool, typer.Option("--yes", help="Do not ask for confirmation.")] = False,
) -> None:
    """Delete all files of a collection, the collection and its directory.

    This needs the creator of the collection or a catalog admin. The API deletes only the files
    that it recorded or placed. Other files stay in the directory, and `huron adm check` reports
    them as `dir_unrecorded`.
    """
    found = services(ctx)
    collection = fetch_collection(ctx, identifier)
    if not yes and not found.prompter.confirm(
        f"Delete {collection['identifier']} and its {collection['file_count']} files?"
    ):
        raise CliError("cancelled", ExitCode.INTERRUPTED)
    version = int(str(collection["version"]))
    path = f"/api/v1/collections/{collection['id']}"
    api(ctx).delete(path, params={"dry_run": "true"}, headers=if_match(version))
    if collection.get("path") is not None:
        version = _remove_files(ctx, collection)
    api(ctx).delete(path, headers=if_match(version))
    if found.config.current_collection == collection["id"]:
        found.save_config(replace(found.config, current_collection=None))
    say(ctx, f"collection {collection['identifier']} deleted")


def _remove_files(ctx: typer.Context, collection: dict[str, Any]) -> int:
    """Commit the removal of every recorded file; the version of the collection after it."""
    version = int(collection["version"])
    recorded = recorded_files(api(ctx), str(collection["id"]))
    if not recorded:
        return version
    removes = [item["rel_path"] for item in recorded.values()]
    body = {
        "base_version": version,
        "adds": [],
        "removes": removes,
        "host": services(ctx).hostname,
    }
    commit = api(ctx).post(f"/api/v1/collections/{collection['id']}/commits", json=body)
    return int(commit["version"])
