"""``huron acl apply``: bring directory ACLs in line with the catalog's current groups."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Annotated

import typer

from huron.applications.cli.commands.common import api, say, services
from huron.applications.cli.errors import StorageFailure
from huron.applications.cli.identifiers import qualify
from huron.applications.cli.inventory import take_inventory
from huron.applications.cli.mount import Mount
from huron.core.storage import DirectoryKind

__all__ = ["register"]

acl_app = typer.Typer(help="Directory ACLs.", no_args_is_help=True)


def register(app: typer.Typer) -> None:
    """Add ``huron acl``."""
    app.add_typer(acl_app, name="acl")


@acl_app.command("apply")
def acl_apply(
    ctx: typer.Context,
    identifier: Annotated[str, typer.Argument(help="catalog, catalog.namespace or a collection")],
    recursive: Annotated[
        bool, typer.Option("--recursive", help="Everything beneath it too.")
    ] = False,
) -> None:
    """Re-apply ACL plans to directories you own; exit 1 when some could not be changed."""
    found = services(ctx)
    target = qualify(identifier, found.catalog())
    catalog = target.split(".")[0]
    inventory = take_inventory(api(ctx), catalog, files=False)
    mount = Mount(found)
    storage = mount.require()
    selected = _selected(inventory.directories(), target, catalog, recursive)
    if not selected:
        raise StorageFailure(f"{target} has no directory to apply")
    skipped = 0
    for name, disk_path, kind in selected:
        path = mount.path(disk_path)
        if not storage.is_directory(path) or not storage.owned_by_me(path):
            found.err.print(f"skipped (not yours or missing): {path}", markup=False)
            skipped += 1
            continue
        changed = mount.apply(disk_path, kind, inventory.groups)
        say(ctx, f"{'changed' if changed else 'unchanged'}: {name}")
    if skipped:
        raise typer.Exit(1)


def _selected(
    directories: Iterable[tuple[str, str, DirectoryKind]],
    target: str,
    catalog: str,
    recursive: bool,
) -> list[tuple[str, str, DirectoryKind]]:
    def wanted(name: str) -> bool:
        if name == target:
            return True
        return recursive and (target == catalog or name.startswith(f"{target}."))

    return [item for item in directories if wanted(item[0])]
