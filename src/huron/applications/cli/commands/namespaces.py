"""``huron namespace``: the namespace tree of a catalog."""

from __future__ import annotations

from typing import Annotated

import typer

from huron.applications.cli.commands.common import api, say, services, show_list
from huron.applications.cli.errors import ApiError
from huron.applications.cli.identifiers import qualify, resolve_namespace
from huron.applications.cli.mount import Mount
from huron.applications.cli.output import Column
from huron.core.storage import DirectoryKind, EffectiveGroups

__all__ = ["COLUMNS", "kind_of", "namespace_app", "register"]

namespace_app = typer.Typer(help="Namespaces.", no_args_is_help=True)

COLUMNS = [
    Column("NAMESPACE", lambda n: n["identifier"]),
    Column("COLLECTIONS", lambda n: "allowed" if n["collections_allowed"] else "-"),
    Column("CHILDREN", lambda n: n["namespace_count"]),
    Column("COUNT", lambda n: n["collection_count"]),
]


def register(app: typer.Typer) -> None:
    """Add ``huron namespace``."""
    app.add_typer(namespace_app, name="namespace")


@namespace_app.command("list")
def namespace_list(
    ctx: typer.Context,
    parent: Annotated[str | None, typer.Argument(help="catalog or catalog.namespace")] = None,
) -> None:
    """Children of a namespace, or the top level of the current catalog."""
    target = qualify(parent or services(ctx).require_catalog(), services(ctx).catalog())
    catalog, _, path = target.partition(".")
    rows = api(ctx).pages(f"/api/v1/catalogs/{catalog}/namespaces", {"parent": path})
    show_list(ctx, rows, COLUMNS)


@namespace_app.command("create")
def namespace_create(
    ctx: typer.Context,
    identifier: Annotated[str, typer.Argument(help="catalog.namespace[.child…]")],
    allow_collections: Annotated[
        bool, typer.Option("--allow-collections", help="Contributors may create collections here.")
    ] = False,
    parents: Annotated[bool, typer.Option("--parents", help="Create missing ancestors.")] = False,
) -> None:
    """Create a namespace and its directory (Catalog Admin); re-running repairs the directory."""
    parsed = resolve_namespace(identifier, services(ctx).catalog())
    mount = Mount(services(ctx))
    mount.require()
    groups = mount.catalog_groups(parsed.catalog)
    segments = parsed.namespace_path
    for depth in range(1, len(segments)):
        ancestor = ".".join(segments[:depth])
        if parents:
            _ensure(ctx, mount, parsed.catalog, ancestor, False, groups)
        else:
            api(ctx).get(f"/api/v1/catalogs/{parsed.catalog}/namespaces/{ancestor}")
    view = _ensure(ctx, mount, parsed.catalog, parsed.namespace, allow_collections, groups)
    say(ctx, f"namespace {view['identifier']} ready")


@namespace_app.command("delete")
def namespace_delete(ctx: typer.Context, identifier: str) -> None:
    """Delete an empty namespace and its directory."""
    parsed = resolve_namespace(identifier, services(ctx).catalog())
    mount = Mount(services(ctx))
    mount.require()
    path = f"/api/v1/catalogs/{parsed.catalog}/namespaces/{parsed.namespace}"
    view = api(ctx).get(path)
    api(ctx).delete(path)
    mount.remove(view["disk_path"])
    say(ctx, f"namespace {view['identifier']} deleted")


@namespace_app.command("configure")
def namespace_configure(
    ctx: typer.Context,
    identifier: str,
    allow_collections: Annotated[
        bool,
        typer.Option("--allow-collections/--no-allow-collections", help="Allow collections here."),
    ],
) -> None:
    """Allow or forbid collections, and re-apply the directory's ACL plan."""
    parsed = resolve_namespace(identifier, services(ctx).catalog())
    mount = Mount(services(ctx))
    mount.require()
    view = api(ctx).patch(
        f"/api/v1/catalogs/{parsed.catalog}/namespaces/{parsed.namespace}",
        json={"collections_allowed": allow_collections},
    )
    mount.apply(view["disk_path"], kind_of(view), mount.catalog_groups(parsed.catalog))
    state = "allows" if allow_collections else "does not allow"
    say(ctx, f"namespace {view['identifier']} {state} collections")


def kind_of(view: dict[str, object]) -> DirectoryKind:
    """The directory kind of a namespace."""
    if view["collections_allowed"]:
        return DirectoryKind.NAMESPACE_WITH_COLLECTIONS
    return DirectoryKind.NAMESPACE


def _ensure(
    ctx: typer.Context,
    mount: Mount,
    catalog: str,
    path: str,
    allow: bool,
    groups: EffectiveGroups,
) -> dict[str, object]:
    parent, _, name = path.rpartition(".")
    base = f"/api/v1/catalogs/{catalog}/namespaces"
    try:
        view: dict[str, object] = api(ctx).post(
            base, json={"parent": parent, "name": name, "collections_allowed": allow}
        )
    except ApiError as error:
        if error.code != "NAME_TAKEN":
            raise
        view = api(ctx).get(f"{base}/{path}")
    mount.ensure(str(view["disk_path"]), kind_of(view), groups)
    return view
