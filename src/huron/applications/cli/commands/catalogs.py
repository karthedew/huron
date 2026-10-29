"""``huron catalog``: catalogs, the current catalog and catalog roles."""

from __future__ import annotations

from dataclasses import replace
from typing import Annotated, Literal

import typer

from huron.applications.cli.commands.common import api, say, services, show, show_list
from huron.applications.cli.commands.organizations import set_groups
from huron.applications.cli.errors import ApiError
from huron.applications.cli.mount import Mount
from huron.applications.cli.output import Column
from huron.core.storage import DirectoryKind

__all__ = ["register"]

catalog_app = typer.Typer(help="Catalogs.", no_args_is_help=True)

COLUMNS = [
    Column("NAME", lambda c: c["name"]),
    Column("ORGANIZATION", lambda c: c["organization"]),
    Column("SCHEMA", lambda c: f"{c['schema']['name']} v{c['schema']['version']}"),
    Column("NAMESPACES", lambda c: c["namespace_count"]),
]

CatalogRole = Literal["catalog_admin", "contributor", "reader"]


def register(app: typer.Typer) -> None:
    """Add ``huron catalog``."""
    app.add_typer(catalog_app, name="catalog")


@catalog_app.command("list")
def catalog_list(
    ctx: typer.Context,
    organization: Annotated[
        str | None, typer.Option("--org", help="Only this organization.")
    ] = None,
) -> None:
    """Catalogs you can see."""
    params = {"organization": organization} if organization else None
    show_list(ctx, api(ctx).pages("/api/v1/catalogs", params), COLUMNS)


@catalog_app.command("create")
def catalog_create(
    ctx: typer.Context,
    organization: str,
    name: str,
    schema: Annotated[str | None, typer.Option("--schema", help="Schema id to assign.")] = None,
    display_name: Annotated[str, typer.Option(help="Human-readable name.")] = "",
    description: Annotated[str, typer.Option(help="What the catalog holds.")] = "",
) -> None:
    """Create a catalog and its directory (Org Admin); re-running repairs a missing directory."""
    mount = Mount(services(ctx))
    mount.require()
    body = {
        "name": name,
        "schema_id": schema,
        "display_name": display_name,
        "description": description,
    }
    try:
        catalog = api(ctx).post(f"/api/v1/organizations/{organization}/catalogs", json=body)
    except ApiError as error:
        if error.code != "NAME_TAKEN":
            raise
        catalog = api(ctx).get(f"/api/v1/catalogs/{name}")
    relative = f"{catalog['organization']}/{name}"
    mount.ensure(relative, DirectoryKind.CATALOG, mount.catalog_groups(name))
    say(ctx, f"catalog {name} ready")


@catalog_app.command("delete")
def catalog_delete(ctx: typer.Context, name: str) -> None:
    """Delete a catalog without namespaces, and its empty directory."""
    mount = Mount(services(ctx))
    mount.require()
    catalog = api(ctx).get(f"/api/v1/catalogs/{name}")
    api(ctx).delete(f"/api/v1/catalogs/{name}")
    mount.remove(f"{catalog['organization']}/{name}")
    say(ctx, f"catalog {name} deleted")


@catalog_app.command("use")
def catalog_use(ctx: typer.Context, name: str) -> None:
    """Make ``name`` the catalog relative identifiers resolve against."""
    api(ctx).get(f"/api/v1/catalogs/{name}")
    found = services(ctx)
    found.save_config(replace(found.config, current_catalog=name))
    say(ctx, f"using catalog {name}")


@catalog_app.command("describe")
def catalog_describe(
    ctx: typer.Context, name: Annotated[str | None, typer.Argument()] = None
) -> None:
    """One catalog (the current one by default)."""
    target = name or services(ctx).require_catalog()
    show(ctx, api(ctx).get(f"/api/v1/catalogs/{target}"))


@catalog_app.command("grants")
def catalog_grants(
    ctx: typer.Context, name: Annotated[str | None, typer.Argument()] = None
) -> None:
    """Effective LDAP groups per role, inherited ones included."""
    target = name or services(ctx).require_catalog()
    groups = api(ctx).get(f"/api/v1/catalogs/{target}/grants")
    if services(ctx).output.value != "table":
        show(ctx, groups)
        return
    rows = [{"role": role, "groups": ", ".join(members) or "-"} for role, members in groups.items()]
    show_list(
        ctx, rows, [Column("ROLE", lambda r: r["role"]), Column("GROUPS", lambda r: r["groups"])]
    )


@catalog_app.command("grant")
def catalog_grant(ctx: typer.Context, catalog: str, role: CatalogRole, group: str) -> None:
    """Grant a catalog role to an LDAP group."""
    current = api(ctx).get(f"/api/v1/catalogs/{catalog}/grants")[role]
    set_groups(ctx, f"/api/v1/catalogs/{catalog}/grants/{role}", sorted({*current, group}))
    _remind(ctx, catalog)


@catalog_app.command("revoke")
def catalog_revoke(ctx: typer.Context, catalog: str, role: CatalogRole, group: str) -> None:
    """Remove a catalog role from an LDAP group."""
    current = api(ctx).get(f"/api/v1/catalogs/{catalog}/grants")[role]
    set_groups(ctx, f"/api/v1/catalogs/{catalog}/grants/{role}", [g for g in current if g != group])
    _remind(ctx, catalog)


def _remind(ctx: typer.Context, catalog: str) -> None:
    say(ctx, f"directory ACLs follow the new groups after: huron acl apply {catalog} --recursive")
