"""``checkout``, ``add``, ``rm``, ``pull`` and ``push``: the working copy of one collection."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Annotated

import typer

from huron.applications.cli.commands.common import (
    api,
    fetch_collection,
    say,
    services,
    table_mode,
    tree_command,
)
from huron.applications.cli.errors import UsageError
from huron.applications.cli.picker import CollectionPicker
from huron.applications.cli.sync import (
    checkout as record_checkout,
)
from huron.applications.cli.sync import (
    current,
    pull,
    push,
    stage_paths,
    unstage_or_remove,
)

__all__ = ["register"]


def register(app: typer.Typer, panels: Mapping[str, str]) -> None:
    """Add the working-copy verbs, each under its help panel in ``panels`` (verb to panel)."""
    for verb in (checkout, add, rm, pull_command, push_command):
        name = verb.__name__.removesuffix("_command")
        app.command(name, rich_help_panel=panels[name])(verb)


def checkout(
    ctx: typer.Context,
    identifier: Annotated[
        str | None,
        typer.Argument(
            help="`catalog.namespace.name`. With no argument, the CLI asks you to choose one."
        ),
    ] = None,
) -> None:
    """Make a collection the current working copy. Other working copies keep their stage."""
    if identifier is None:
        identifier = _pick(ctx)
    collection = fetch_collection(ctx, identifier)
    working = record_checkout(services(ctx), collection)
    say(
        ctx,
        f"The current collection is now {working.identifier} at version {working.base_version}",
    )


def add(
    ctx: typer.Context,
    paths: Annotated[list[Path], typer.Argument(help="Local files or directories to stage.")],
    rename: Annotated[
        str | None, typer.Option("--as", help="The path of the file in the collection.")
    ] = None,
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
    """Unstage an add or a removal, or stage the removal of a recorded file."""
    done = unstage_or_remove(services(ctx), current(services(ctx)), rel_paths)
    for action, rel_path in done:
        say(ctx, f"{action} {rel_path}")


def pull_command(ctx: typer.Context) -> None:
    """Update the working copy to the version on the service."""
    found = services(ctx)
    working, dropped = pull(found, current(found))
    for rel_path in dropped:
        found.err.print(
            f"warning: the service no longer records {rel_path}, so the CLI unstaged its removal",
            markup=False,
        )
    say(ctx, f"{working.identifier} at version {working.base_version}")


def push_command(
    ctx: typer.Context,
    message: Annotated[
        str | None, typer.Option("-m", "--message", help="The commit message.")
    ] = None,
) -> None:
    """Upload the staged files and commit them."""
    found = services(ctx)
    working = current(found)
    if working.empty:
        say(ctx, "Nothing is staged. There is nothing to push")
        return
    result = push(found, working, message)
    say(ctx, f"version {result.before} → {result.after}, +{result.adds} −{result.removes} files")


def _pick(ctx: typer.Context) -> str:
    found = services(ctx)
    if not table_mode(ctx) or not found.prompter.interactive:
        raise UsageError(
            "`huron checkout` needs a collection identifier when it cannot ask you to choose one",
            hint=(
                f"to see the collections, run `{tree_command(ctx)}`."
                " Then run `huron checkout <identifier>`"
            ),
        )
    return CollectionPicker(api(ctx), found.prompter).pick(found.require_catalog())
