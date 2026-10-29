"""``huron org``: organizations and their administrators."""

from __future__ import annotations

from typing import Annotated, Any

import typer

from huron.applications.cli.commands.common import api, say, services, show, show_list
from huron.applications.cli.errors import ApiError
from huron.applications.cli.mount import Mount
from huron.applications.cli.output import Column
from huron.core.storage import DirectoryKind

__all__ = ["register", "set_groups"]

org_app = typer.Typer(help="Organizations.", no_args_is_help=True)

COLUMNS = [
    Column("NAME", lambda o: o["name"]),
    Column("DISPLAY NAME", lambda o: o["display_name"]),
    Column("CATALOGS", lambda o: o["catalog_count"]),
    Column("CREATED BY", lambda o: o["created_by"]),
]


def register(app: typer.Typer) -> None:
    """Add ``huron org``."""
    app.add_typer(org_app, name="org")


@org_app.command("list")
def org_list(ctx: typer.Context) -> None:
    """Organizations you can see."""
    show_list(ctx, api(ctx).pages("/api/v1/organizations"), COLUMNS)


@org_app.command("create")
def org_create(
    ctx: typer.Context,
    name: str,
    display_name: Annotated[str, typer.Option(help="Human-readable name.")] = "",
    description: Annotated[str, typer.Option(help="What the organization is.")] = "",
) -> None:
    """Create an organization and its directory on the share (Platform Admin)."""
    mount = Mount(services(ctx))
    mount.require()
    body = {"name": name, "display_name": display_name, "description": description}
    try:
        api(ctx).post("/api/v1/organizations", json=body)
    except ApiError as error:
        if error.code != "NAME_TAKEN":
            raise
        api(ctx).get(f"/api/v1/organizations/{name}")
    mount.ensure(name, DirectoryKind.ORGANIZATION, mount.organization_groups(name))
    say(ctx, f"organization {name} ready")


@org_app.command("delete")
def org_delete(ctx: typer.Context, name: str) -> None:
    """Delete an organization without catalogs, and its empty directory."""
    mount = Mount(services(ctx))
    mount.require()
    api(ctx).delete(f"/api/v1/organizations/{name}")
    mount.remove(name)
    say(ctx, f"organization {name} deleted")


@org_app.command("describe")
def org_describe(ctx: typer.Context, name: str) -> None:
    """One organization."""
    show(ctx, api(ctx).get(f"/api/v1/organizations/{name}"))


@org_app.command("grants")
def org_grants(ctx: typer.Context, name: str) -> None:
    """The LDAP groups holding Org Admin."""
    show(ctx, api(ctx).get(f"/api/v1/organizations/{name}/grants"))


@org_app.command("grant")
def org_grant(
    ctx: typer.Context,
    name: str,
    group: Annotated[str, typer.Argument(help="LDAP group to make Org Admin.")],
) -> None:
    """Make an LDAP group an Org Admin of the organization."""
    path = f"/api/v1/organizations/{name}/grants"
    current = api(ctx).get(path)["ldap_groups"]
    set_groups(ctx, f"{path}/org_admin", sorted({*current, group}))


@org_app.command("revoke")
def org_revoke(ctx: typer.Context, name: str, group: str) -> None:
    """Remove an LDAP group from the organization's Org Admins."""
    path = f"/api/v1/organizations/{name}/grants"
    current = api(ctx).get(path)["ldap_groups"]
    set_groups(ctx, f"{path}/org_admin", [g for g in current if g != group])


def set_groups(ctx: typer.Context, path: str, groups: list[str]) -> dict[str, Any]:
    """Replace a role's groups and report what changed."""
    change: dict[str, Any] = api(ctx).put(path, json={"ldap_groups": groups})
    added = ", ".join(change["added"]) or "-"
    removed = ", ".join(change["removed"]) or "-"
    say(ctx, f"{change['role']}: added {added}; removed {removed}")
    return change
