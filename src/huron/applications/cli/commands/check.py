"""``huron check``: where the share and the catalog disagree."""

from __future__ import annotations

from typing import Annotated

import typer

from huron.applications.cli.commands.common import api, services, show_list
from huron.applications.cli.inventory import CatalogInventory, take_inventory
from huron.applications.cli.mount import Mount
from huron.applications.cli.output import Column
from huron.core.storage import DirectoryKind, plan
from huron.core.storage.check import ExpectedCollection, ExpectedDirectory, Finding, check

__all__ = ["register"]

COLUMNS = [
    Column("SEVERITY", lambda f: f["severity"]),
    Column("CODE", lambda f: f["code"]),
    Column("IDENTIFIER", lambda f: f["identifier"]),
    Column("PATH", lambda f: f["path"]),
    Column("DETAIL", lambda f: f["detail"]),
]


def register(app: typer.Typer) -> None:
    """Add ``huron check``."""
    app.command("check")(check_command)


def check_command(
    ctx: typer.Context,
    catalog: Annotated[str | None, typer.Option("--catalog", help="Only this catalog.")] = None,
    hash_files: Annotated[bool, typer.Option("--hash", help="Also compare sha256.")] = False,
) -> None:
    """Report drift between the service and the share; exit 1 when anything is found."""
    found = services(ctx)
    mount = Mount(found)
    storage = mount.require()
    names = [catalog] if catalog else [c["name"] for c in api(ctx).pages("/api/v1/catalogs")]
    findings: list[Finding] = []
    for name in names:
        inventory = take_inventory(api(ctx), name, files=True)
        acls = found.config.acl_backend == "posix"
        findings += check(
            storage,
            mount.prefix,
            _directories(inventory, acls),
            _collections(inventory, acls),
            found.clock.now(),
            hash_files=hash_files,
        )
    show_list(ctx, [f.as_dict() for f in findings], COLUMNS)
    if findings:
        raise typer.Exit(1)


def _directories(inventory: CatalogInventory, acls: bool) -> list[ExpectedDirectory]:
    return [
        ExpectedDirectory(identifier, disk_path, plan(kind, inventory.groups) if acls else None)
        for identifier, disk_path, kind in inventory.directories()
        if kind is not DirectoryKind.COLLECTION
    ]


def _collections(inventory: CatalogInventory, acls: bool) -> list[ExpectedCollection]:
    collection_plan = plan(DirectoryKind.COLLECTION, inventory.groups) if acls else None
    return [
        ExpectedCollection(
            identifier=c["identifier"],
            state=c["state"],
            created_at=c["created"],
            disk_path=c.get("path"),
            plan=collection_plan,
            files=c.get("files", {}),
            sidecar=c.get("sidecar"),
        )
        for c in inventory.collections
    ]
