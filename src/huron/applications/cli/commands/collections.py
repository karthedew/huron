"""``huron collection`` reads, and the top-level ``files``, ``log`` and ``search`` verbs."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Annotated, Any

import typer

from huron.applications.cli.client import if_match
from huron.applications.cli.commands.common import api, say, services, show, show_list
from huron.applications.cli.commands.schemas import read_document
from huron.applications.cli.errors import CliError, ExitCode, UsageError
from huron.applications.cli.identifiers import resolve_collection, resolve_namespace
from huron.applications.cli.mount import Mount
from huron.applications.cli.output import Column
from huron.applications.cli.sync import checkout, recorded_files, write_sidecar
from huron.applications.cli.walkthrough import fill
from huron.core.storage import DirectoryKind, Storage, StorageError, is_reserved_entry
from huron.schema.naming import rel_path_key

__all__ = ["COLUMNS", "activate", "collection_app", "fetch_collection", "register"]

collection_app = typer.Typer(help="Collections.", no_args_is_help=True)

COLUMNS = [
    Column("COLLECTION", lambda c: c["identifier"]),
    Column("STATE", lambda c: c["state"]),
    Column("VERSION", lambda c: c["version"]),
    Column("FILES", lambda c: c["file_count"]),
    Column("TITLE", lambda c: c["metadata"].get("title")),
]


def register(app: typer.Typer) -> None:
    """Add ``huron collection``, ``files``, ``log`` and ``search``."""
    app.add_typer(collection_app, name="collection")
    app.command("files")(files)
    app.command("log")(log)
    app.command("search")(search)


def fetch_collection(ctx: typer.Context, identifier: str | None) -> dict[str, Any]:
    """A collection by identifier, or the checked-out one when none is given."""
    found = services(ctx)
    if identifier is None:
        current = found.config.current_collection
        if current is None:
            raise UsageError(
                "no collection is checked out", hint="run: huron checkout <identifier>"
            )
        collection: dict[str, Any] = api(ctx).get(f"/api/v1/collections/{current}")
        return collection
    parsed = resolve_collection(identifier, found.catalog())
    rest = ".".join((*parsed.namespace_path, str(parsed.name)))
    collection = api(ctx).get(f"/api/v1/catalogs/{parsed.catalog}/collections/{rest}")
    return collection


@collection_app.command("create")
def collection_create(
    ctx: typer.Context,
    identifier: Annotated[str, typer.Argument(help="catalog.namespace.name")],
    metadata: Annotated[
        Path | None, typer.Option("--metadata", help="JSON metadata instead of the walkthrough.")
    ] = None,
    draft: Annotated[bool, typer.Option("--draft", help="Stop before activation.")] = False,
) -> None:
    """Reserve a collection, fill its metadata, then create its directory and activate it."""
    found = services(ctx)
    parsed = resolve_collection(identifier, found.catalog())
    mount = Mount(found)
    if not draft:
        mount.require()
    document = read_document(metadata) if metadata else None
    base = f"/api/v1/catalogs/{parsed.catalog}/namespaces/{parsed.namespace}"
    collection = api(ctx).post(
        f"{base}/collections", json={"name": parsed.name, "metadata": document}
    )
    if document is None:
        schema = api(ctx).get(f"/api/v1/collections/{collection['id']}/schema")
        filled = fill(found.prompter, schema, collection["metadata"])
        collection = api(ctx).patch(
            f"/api/v1/collections/{collection['id']}",
            json={"metadata": filled},
            headers=if_match(collection["version"]),
        )
    if draft:
        checkout(found, collection)
        say(
            ctx,
            f"draft {collection['identifier']} reserved; activate with: huron collection activate",
        )
        return
    activated = activate(ctx, collection, mount)
    say(ctx, f"collection {activated['identifier']} is active at {activated['path']}")


@collection_app.command("activate")
def collection_activate(
    ctx: typer.Context, identifier: Annotated[str | None, typer.Argument()] = None
) -> None:
    """Create the directory of a draft and activate it."""
    collection = fetch_collection(ctx, identifier)
    activated = activate(ctx, collection, Mount(services(ctx)))
    say(ctx, f"collection {activated['identifier']} is active at {activated['path']}")


@collection_app.command("delete")
def collection_delete(
    ctx: typer.Context,
    identifier: str,
    yes: Annotated[bool, typer.Option("--yes", help="Do not ask for confirmation.")] = False,
) -> None:
    """Remove every file, the collection and its directory (its creator or a catalog admin)."""
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
        Mount(found).remove(str(collection["path"]))
    if found.config.current_collection == collection["id"]:
        found.save_config(replace(found.config, current_collection=None))
    say(ctx, f"collection {collection['identifier']} deleted")


@collection_app.command("list")
def collection_list(
    ctx: typer.Context, namespace: Annotated[str, typer.Argument(help="catalog.namespace")]
) -> None:
    """Collections directly in a namespace."""
    parsed = resolve_namespace(namespace, services(ctx).catalog())
    path = f"/api/v1/catalogs/{parsed.catalog}/namespaces/{parsed.namespace}/collections"
    show_list(ctx, api(ctx).pages(path), COLUMNS)


@collection_app.command("describe")
def collection_describe(
    ctx: typer.Context, identifier: Annotated[str | None, typer.Argument()] = None
) -> None:
    """One collection (the checked-out one by default)."""
    show(ctx, fetch_collection(ctx, identifier))


def files(ctx: typer.Context, identifier: Annotated[str | None, typer.Argument()] = None) -> None:
    """Files recorded in a collection."""
    collection = fetch_collection(ctx, identifier)
    rows = api(ctx).pages(f"/api/v1/collections/{collection['id']}/files")
    show_list(
        ctx,
        rows,
        [
            Column("PATH", lambda f: f["rel_path"]),
            Column("SIZE", lambda f: f["size"]),
            Column("SHA256", lambda f: f["sha256"][:12]),
            Column("RECORDED BY", lambda f: f["recorded_by"]),
        ],
    )


def log(ctx: typer.Context, identifier: Annotated[str | None, typer.Argument()] = None) -> None:
    """The audit log of a collection, newest first."""
    collection = fetch_collection(ctx, identifier)
    rows = api(ctx).pages(f"/api/v1/collections/{collection['id']}/log")
    show_list(
        ctx,
        rows,
        [
            Column("AT", lambda e: e["at"]),
            Column("ACTOR", lambda e: e["actor"]),
            Column("ACTION", lambda e: e["action"]),
            Column("DETAIL", lambda e: e["detail"]),
        ],
    )


def search(
    ctx: typer.Context,
    catalog: Annotated[str | None, typer.Argument()] = None,
    query: Annotated[str | None, typer.Option("-q", "--query", help="Free text.")] = None,
    label: Annotated[list[str] | None, typer.Option("-l", "--label", help="key=value")] = None,
    state: Annotated[list[str] | None, typer.Option("--state")] = None,
) -> None:
    """Search a catalog by text, labels and state."""
    target = catalog or services(ctx).require_catalog()
    params: dict[str, object] = {}
    if query:
        params["q"] = query
    if label:
        params["label"] = label
    if state:
        params["state"] = state
    show_list(ctx, api(ctx).pages(f"/api/v1/catalogs/{target}/search", params), COLUMNS)


def activate(ctx: typer.Context, collection: dict[str, Any], mount: Mount) -> dict[str, Any]:
    """Create the collection's directory, activate it, write ``metadata.json`` and check it out."""
    found = services(ctx)
    namespace = api(ctx).get(
        f"/api/v1/catalogs/{collection['catalog']}/namespaces/{collection['namespace']}"
    )
    relative = f"{namespace['disk_path']}/{collection['name']}"
    mount.ensure(
        relative, DirectoryKind.COLLECTION, mount.catalog_groups(str(collection["catalog"]))
    )
    activated: dict[str, Any] = api(ctx).post(
        f"/api/v1/collections/{collection['id']}/activate",
        headers=if_match(int(collection["version"])),
    )
    write_sidecar(found, mount, activated)
    checkout(found, activated)
    return activated


def _empty_directory(ctx: typer.Context, collection: dict[str, Any]) -> int:
    found = services(ctx)
    mount = Mount(found)
    storage = mount.require()
    directory = mount.path(str(collection["path"]))
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
            hint="move or remove them, then run the delete again",
        )
