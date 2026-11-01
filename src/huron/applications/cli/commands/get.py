"""``huron get <noun>``: list organizations, catalogs, namespaces, collections and more."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Annotated, Any

import typer

from huron.applications.cli.commands.common import (
    CATALOG_COLUMNS,
    COLLECTION_COLUMNS,
    NAMESPACE_COLUMNS,
    CollectionArgument,
    api,
    catalog_rows,
    current_column,
    empty_organization,
    fetch_collection,
    fetch_namespace,
    grant_sources,
    locate,
    organization_columns,
    say,
    services,
    show,
    show_list,
    table_mode,
)
from huron.applications.cli.errors import UsageError
from huron.applications.cli.identifiers import parent_candidates
from huron.applications.cli.output import Column
from huron.schema.naming import Identifier

__all__ = ["ALL_STATES", "ORGANIZATION_ROLES", "get_app", "noun", "register"]

get_app = typer.Typer(
    help="List resources: get orgs, catalogs, namespaces, collections and more.",
    no_args_is_help=True,
)

ALL_STATES = ("draft", "active", "incomplete")

SCHEMA_COLUMNS = [
    Column("ID", lambda s: s["id"]),
    Column("NAME", lambda s: s["name"]),
    Column("VERSION", lambda s: s["version"]),
    Column("SCOPE", lambda s: s["scope"]),
    Column("EXTENDS", lambda s: s["extends_id"]),
]
FILE_COLUMNS = [
    Column("PATH", lambda f: f["rel_path"]),
    Column("SIZE", lambda f: f["size"]),
    Column("SHA256", lambda f: f["sha256"][:12]),
    Column("RECORDED BY", lambda f: f["recorded_by"]),
]
LOG_COLUMNS = [
    Column("AT", lambda e: e["at"]),
    Column("ACTOR", lambda e: e["actor"]),
    Column("ACTION", lambda e: e["action"]),
    Column("DETAIL", lambda e: e["detail"]),
]
GRANT_COLUMNS = [Column("ROLE", lambda r: r["role"]), Column("GROUPS", lambda r: r["groups"])]
#: The roles an organization grants: org_admin, and the catalog roles all its catalogs inherit.
ORGANIZATION_ROLES = ("org_admin", "catalog_admin", "contributor", "reader")


def register(app: typer.Typer, panel: str) -> None:
    """Add ``huron get`` under the help panel ``panel``."""
    app.add_typer(get_app, name="get", rich_help_panel=panel)


def noun(plural: str, singular: str | None) -> Callable[[Callable[..., None]], Callable[..., None]]:
    """Register a ``get`` noun under its plural, and its singular as a hidden alias."""

    def decorate(command: Callable[..., None]) -> Callable[..., None]:
        get_app.command(plural)(command)
        if singular is not None:
            get_app.command(singular, hidden=True)(command)
        return command

    return decorate


@noun("orgs", "org")
def get_orgs(ctx: typer.Context) -> None:
    """Organizations you can see, with where each one's directory is."""
    show_list(ctx, api(ctx).pages("/api/v1/organizations"), organization_columns(ctx))


@noun("catalogs", "catalog")
def get_catalogs(
    ctx: typer.Context,
    organization: Annotated[
        str | None,
        typer.Option("--org", help="Only this organization instead of the current one."),
    ] = None,
    all_organizations: Annotated[
        bool, typer.Option("--all-orgs", "-A", help="Every organization you can see.")
    ] = False,
) -> None:
    """Catalogs of the current organization, or every one with -A; * marks the current one."""
    if organization and all_organizations:
        raise UsageError("--org and --all-orgs cannot be combined")
    found = services(ctx)
    scope = None if all_organizations else organization or found.organization()
    columns = [current_column(found.catalog()), *CATALOG_COLUMNS]
    rows = catalog_rows(ctx, scope)
    show_list(ctx, rows, columns)
    if not rows and organization is None and scope is not None:
        say(ctx, empty_organization(scope))


@noun("namespaces", "namespace")
def get_namespaces(
    ctx: typer.Context,
    parent: Annotated[str | None, typer.Argument(help="catalog or catalog.namespace")] = None,
) -> None:
    """Children of a namespace, or the top level of the current catalog."""
    found = services(ctx)
    if parent is None:
        target = Identifier(found.require_catalog())
    else:
        candidates = parent_candidates(parent, found.catalog())
        target, _ = locate(ctx, "catalog or namespace", candidates, lambda each: _view(ctx, each))
    path = f"/api/v1/catalogs/{target.catalog}/namespaces"
    rows = list(api(ctx).pages(path, {"parent": target.namespace}))
    show_list(ctx, rows, NAMESPACE_COLUMNS)
    if rows:
        say(
            ctx,
            "list the collections in one with: huron get collections <namespace>;"
            " see the whole tree with: huron tree",
        )
    else:
        say(ctx, "no namespaces here; create one with: huron create namespace <identifier>")


@noun("collections", "collection")
def get_collections(
    ctx: typer.Context,
    namespace: Annotated[
        str | None,
        typer.Argument(help="catalog.namespace; every collection of the catalog when omitted."),
    ] = None,
) -> None:
    """Collections directly in a namespace, or every collection of the current catalog."""
    found = services(ctx)
    if namespace is None:
        catalog = found.require_catalog()
        rows = api(ctx).pages(f"/api/v1/catalogs/{catalog}/search", {"state": list(ALL_STATES)})
    else:
        parsed, _ = fetch_namespace(ctx, namespace)
        path = f"/api/v1/catalogs/{parsed.catalog}/namespaces/{parsed.namespace}/collections"
        rows = api(ctx).pages(path)
    listed = list(rows)
    show_list(ctx, listed, COLLECTION_COLUMNS)
    if listed:
        say(ctx, "check out one with: huron checkout <COLLECTION>")
    else:
        say(
            ctx,
            "no collections here; see the whole catalog with: huron tree,"
            " or create one with: huron create collection <identifier>",
        )


@noun("files", "file")
def get_files(ctx: typer.Context, identifier: CollectionArgument = None) -> None:
    """Files recorded in a collection."""
    collection = fetch_collection(ctx, identifier)
    rows = api(ctx).pages(f"/api/v1/collections/{collection['id']}/files")
    show_list(ctx, rows, FILE_COLUMNS)


@noun("log", None)
def get_log(ctx: typer.Context, identifier: CollectionArgument = None) -> None:
    """The audit log of a collection, newest first."""
    collection = fetch_collection(ctx, identifier)
    rows = api(ctx).pages(f"/api/v1/collections/{collection['id']}/log")
    show_list(ctx, rows, LOG_COLUMNS)


@noun("schemas", "schema")
def get_schemas(
    ctx: typer.Context,
    organization: Annotated[
        str | None, typer.Argument(help="Organization; the platform's when omitted.")
    ] = None,
) -> None:
    """Schemas of an organization, or the platform's when none is named."""
    path = (
        f"/api/v1/organizations/{organization}/schemas"
        if organization
        else "/api/v1/platform/schemas"
    )
    show_list(ctx, api(ctx).pages(path), SCHEMA_COLUMNS)


@noun("grants", "grant")
def get_grants(
    ctx: typer.Context,
    organization: Annotated[
        str | None,
        typer.Option("--org", help="The organization-wide groups of this organization."),
    ] = None,
    catalog: Annotated[
        str | None, typer.Option("--catalog", help="This catalog instead of the current one.")
    ] = None,
) -> None:
    """Who holds each role on a catalog (the current one) and why, or an organization's groups.

    For a catalog, one row per role and group with its SOURCE: platform, organization <name>
    (inherited by every catalog of the organization) or catalog (granted on this catalog). With
    --org, the groups of org_admin and of the catalog roles every catalog of it inherits.
    """
    if organization and catalog:
        raise UsageError("--org and --catalog cannot be combined")
    if organization:
        groups: dict[str, Any] = api(ctx).get(f"/api/v1/organizations/{organization}/grants")
        if not table_mode(ctx):
            show(ctx, groups)
            return
        rows = [
            {"role": role, "groups": ", ".join(groups.get(role, [])) or "-"}
            for role in ORGANIZATION_ROLES
        ]
        show_list(ctx, rows, GRANT_COLUMNS)
        return
    target = catalog or services(ctx).require_catalog()
    sources = grant_sources(ctx, target)
    owner = _owner(ctx, target, sources) if table_mode(ctx) else None
    show_list(ctx, sources, _source_columns(owner))


@get_app.command("meta")
def get_meta(ctx: typer.Context, identifier: CollectionArgument = None) -> None:
    """A collection's metadata, its local draft and its schema override."""
    collection = fetch_collection(ctx, identifier)
    draft = services(ctx).state.read_draft(str(collection["id"]))
    show(
        ctx,
        {
            "metadata": collection["metadata"],
            "draft": draft,
            "schema_override": collection["schema_override"],
        },
    )


def _view(ctx: typer.Context, target: Identifier) -> dict[str, Any]:
    nested = f"/namespaces/{target.namespace}" if target.namespace else ""
    view: dict[str, Any] = api(ctx).get(f"/api/v1/catalogs/{target.catalog}{nested}")
    return view


def _owner(ctx: typer.Context, catalog: str, sources: list[dict[str, Any]]) -> str | None:
    """The catalog's organization, looked up only when some group is inherited from it."""
    if not any(source["scope"] == "organization" for source in sources):
        return None
    return str(api(ctx).get(f"/api/v1/catalogs/{catalog}")["organization"])


def _source_columns(owner: str | None) -> list[Column]:
    def source(row: Mapping[str, Any]) -> str:
        scope = str(row["scope"])
        return f"organization {owner}" if scope == "organization" and owner else scope

    return [
        Column("ROLE", lambda r: r["role"]),
        Column("GROUP", lambda r: r["group"]),
        Column("SOURCE", source),
    ]
