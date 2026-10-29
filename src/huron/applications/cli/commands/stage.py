"""``checkout``, ``add``, ``rm``, ``status``, ``pull`` and ``push``."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer

from huron.applications.cli.commands.collections import fetch_collection
from huron.applications.cli.commands.common import say, services, show
from huron.applications.cli.errors import CliError
from huron.applications.cli.mount import Mount
from huron.applications.cli.sync import (
    checkout as record_checkout,
)
from huron.applications.cli.sync import (
    current,
    pull,
    push,
    recorded_files,
    stage_paths,
    unstage_or_remove,
)
from huron.core.storage import is_reserved_entry
from huron.schema.naming import rel_path_key

__all__ = ["register"]


def register(app: typer.Typer) -> None:
    """Add the working-copy verbs."""
    for verb in (checkout, add, rm, status, pull_command, push_command):
        name = verb.__name__.removesuffix("_command")
        app.command(name)(verb)


def checkout(ctx: typer.Context, identifier: str) -> None:
    """Make a collection the current working copy; other working copies keep their stage."""
    collection = fetch_collection(ctx, identifier)
    copy = record_checkout(services(ctx), collection)
    say(ctx, f"checked out {copy.identifier} at version {copy.version}")


def add(
    ctx: typer.Context,
    paths: Annotated[list[Path], typer.Argument(help="Local files or directories.")],
    rename: Annotated[str | None, typer.Option("--as", help="Path inside the collection.")] = None,
    recursive: Annotated[
        bool, typer.Option("--recursive", "-r", help="Stage directories.")
    ] = False,
) -> None:
    """Stage local files for the next push."""
    staged = stage_paths(services(ctx), current(services(ctx)), paths, rename, recursive)
    for item in staged:
        say(ctx, f"staged {item.rel_path} ({item.size} bytes)")


def rm(
    ctx: typer.Context,
    rel_paths: Annotated[list[str], typer.Argument(help="Paths inside the collection.")],
) -> None:
    """Unstage an add, or stage the removal of a recorded file."""
    removed = unstage_or_remove(services(ctx), current(services(ctx)), rel_paths)
    for rel_path in removed:
        say(ctx, f"staged removal of {rel_path}")


def status(ctx: typer.Context) -> None:
    """Staged changes, how far behind the copy is, and unrecorded files on the share."""
    found = services(ctx)
    copy = current(found)
    stage = found.state.read_stage(copy.collection_id)
    collection = found.api().get(f"/api/v1/collections/{copy.collection_id}")
    report: dict[str, object] = {
        "collection": copy.identifier,
        "state": collection["state"],
        "your_version": copy.version,
        "service_version": collection["version"],
        "behind": int(collection["version"]) != copy.version,
        "adds": [add.rel_path for add in stage.adds],
        "removes": list(stage.removes),
        "unrecorded": _unrecorded(ctx, collection),
    }
    show(ctx, report)
    if report["behind"]:
        say(ctx, "behind: run huron pull")


def pull_command(ctx: typer.Context) -> None:
    """Catch the working copy up with the service."""
    found = services(ctx)
    copy, dropped = pull(found, current(found))
    for rel_path in dropped:
        found.err.print(
            f"warning: {rel_path} is no longer recorded; dropped its removal", markup=False
        )
    say(ctx, f"{copy.identifier} at version {copy.version}")


def push_command(
    ctx: typer.Context,
    message: Annotated[str | None, typer.Option("-m", "--message", help="Commit message.")] = None,
) -> None:
    """Copy staged files onto the share and commit them."""
    found = services(ctx)
    copy = current(found)
    if found.state.read_stage(copy.collection_id).empty:
        say(ctx, "nothing to push")
        return
    result = push(found, copy, message)
    say(ctx, f"version {result.before} → {result.after}, +{result.adds} −{result.removes} files")


def _unrecorded(ctx: typer.Context, collection: dict[str, Any]) -> list[str] | None:
    if collection.get("path") is None:
        return []
    mount = Mount(services(ctx))
    try:
        storage = mount.require()
    except CliError:
        return None
    recorded = recorded_files(services(ctx).api(), str(collection["id"]))
    directory = mount.path(str(collection["path"]))
    return [
        entry.rel_path
        for entry in storage.walk(directory)
        if entry.kind == "file"
        and not is_reserved_entry(entry.rel_path)
        and rel_path_key(entry.rel_path) not in recorded
    ]
