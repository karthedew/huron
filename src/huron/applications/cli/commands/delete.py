"""``huron delete <noun>``: organizations, catalogs, namespaces, collections and directories."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
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
from huron.applications.cli.mount import Mount
from huron.applications.cli.sync import recorded_files
from huron.core.storage import (
    MarkerState,
    OrganizationPlace,
    Storage,
    StorageError,
    is_reserved_entry,
)
from huron.schema.naming import rel_path_key

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
    """Delete an organization that has no catalogs, and its empty directory.

    The service refuses to delete a declared organization. Instead, delete it from the service
    configuration. The CLI leaves the directory of an organization with a configured root to
    its storage admin. An organization that the managed configuration no longer declares has
    no known root. The CLI deletes its directory only when the mount prefix is its share.
    Otherwise, the CLI leaves the directory to its owner.
    """
    found = services(ctx)
    mount = found.mount()
    place = mount.place(name)
    directory = _organization_directory(mount, place)
    if directory == "remove":
        mount.verify(name)
    try:
        api(ctx).delete(f"/api/v1/organizations/{name}")
    except ApiError as error:
        if error.code == "ORGANIZATION_DECLARED":
            error.hint = DECLARED_HINT
        raise
    if directory == "remove":
        mount.remove(name)
        say(ctx, f"organization {name} deleted")
    else:
        for line in _KEPT[directory]:
            say(ctx, line.format(name=name, directory=place.directory))
    if found.organization() == name:
        found.save_config(replace(found.config, current_organization=None))
        say(
            ctx,
            "There is no current organization now. To select one, run `huron org <name>`",
        )


@delete_app.command("catalog")
def delete_catalog(ctx: typer.Context, name: str) -> None:
    """Delete a catalog that has no namespaces, and its empty directory."""
    mount = services(ctx).mount()
    catalog = fetch_catalog(ctx, name)
    relative = f"{catalog['organization']}/{name}"
    mount.path(relative)  # refuse before any change when the share is not ours
    api(ctx).delete(f"/api/v1/catalogs/{name}")
    mount.remove(relative)
    say(ctx, f"catalog {name} deleted")


@delete_app.command("namespace")
def delete_namespace(ctx: typer.Context, identifier: str) -> None:
    """Delete an empty namespace and its directory."""
    mount = services(ctx).mount()
    parsed, view = fetch_namespace(ctx, identifier)
    mount.path(view["disk_path"])  # refuse before any change when the share is not ours
    api(ctx).delete(f"/api/v1/catalogs/{parsed.catalog}/namespaces/{parsed.namespace}")
    mount.remove(view["disk_path"])
    say(ctx, f"namespace {view['identifier']} deleted")


@delete_app.command("collection")
def delete_collection(
    ctx: typer.Context,
    identifier: str,
    yes: Annotated[bool, typer.Option("--yes", help="Do not ask for confirmation.")] = False,
) -> None:
    """Delete all files of a collection, the collection and its directory.

    This needs the creator of the collection or a catalog admin.
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
        version = _empty_directory(ctx, collection)
    api(ctx).delete(path, headers=if_match(version))
    if collection.get("path") is not None:
        found.mount().remove(str(collection["path"]))
    if found.config.current_collection == collection["id"]:
        found.save_config(replace(found.config, current_collection=None))
    say(ctx, f"collection {collection['identifier']} deleted")


def _empty_directory(ctx: typer.Context, collection: dict[str, Any]) -> int:
    found = services(ctx)
    mount = found.mount()
    directory = mount.path(str(collection["path"]))
    storage = mount.storage
    recorded = recorded_files(api(ctx), str(collection["id"]))
    _refuse_unrecorded(storage, directory, recorded)
    version = int(collection["version"])
    if recorded:
        removes = [item["rel_path"] for item in recorded.values()]
        body = {"base_version": version, "adds": [], "removes": removes, "host": found.hostname}
        version = int(
            api(ctx).post(f"/api/v1/collections/{collection['id']}/commits", json=body)["version"]
        )
        for rel_path in removes:
            storage.remove_file(directory.joinpath(*rel_path.split("/")))
    storage.remove_file(directory / "metadata.json")
    for entry in sorted(storage.walk(directory), key=lambda e: e.rel_path, reverse=True):
        try:
            storage.remove_directory(directory.joinpath(*entry.rel_path.split("/")))
        except StorageError as error:
            raise CliError(error.message, ExitCode.STORAGE, code=error.code) from error
    return version


def _refuse_unrecorded(storage: Storage, directory: Path, recorded: dict[str, Any]) -> None:
    leftovers = [
        entry.rel_path
        for entry in storage.walk(directory)
        if entry.kind != "dir"
        and not is_reserved_entry(entry.rel_path)
        and rel_path_key(entry.rel_path) not in recorded
    ]
    if leftovers:
        raise CliError(
            f"{len(leftovers)} unrecorded files remain in {directory}: {', '.join(leftovers[:20])}",
            ExitCode.CONFLICT,
            hint="move or delete them. Then run `huron delete collection` again",
        )


_KEPT = {
    "keep": (
        "Organization {name} deleted. Its directory {directory} stays",
        "Its storage admin deletes the directory when it is no longer necessary",
    ),
    "lost": (
        "Organization {name} deleted. The CLI did not look for its directory",
        "The service configuration does not declare it, so its root is unknown."
        " If its directory still exists, delete it manually where it is",
    ),
}


def _organization_directory(mount: Mount, place: OrganizationPlace) -> str:
    """What ``delete org`` does with the directory: keep (rooted or declared), lost or remove."""
    if place.rooted or place.declared:
        return "keep"
    if mount.undeclared(place) and mount.prefix_state() is not MarkerState.OK:
        return "lost"
    return "remove"
