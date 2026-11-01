"""Helpers the command modules share: services, output, lookups and the collection lifecycle."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Annotated, Any

import typer

from huron.applications.cli.client import ApiClient, if_match
from huron.applications.cli.errors import CliError, ExitCode, UsageError
from huron.applications.cli.identifiers import collection_candidates, namespace_candidates
from huron.applications.cli.mount import Mount
from huron.applications.cli.output import Column, OutputFormat, render, render_one
from huron.applications.cli.services import Services
from huron.applications.cli.sync import checkout, write_sidecar
from huron.core.storage import DirectoryKind
from huron.schema.naming import Identifier

__all__ = [
    "CATALOG_COLUMNS",
    "COLLECTION_COLUMNS",
    "NAMESPACE_COLUMNS",
    "ORGANIZATION_COLUMNS",
    "CollectionArgument",
    "activate",
    "api",
    "catalog_rows",
    "current_column",
    "empty_organization",
    "explain_missing_organization",
    "fetch_collection",
    "fetch_namespace",
    "grant_sources",
    "kind_of",
    "locate",
    "organization_columns",
    "organization_path",
    "read_document",
    "say",
    "services",
    "set_groups",
    "show",
    "show_list",
    "table_mode",
]

CollectionArgument = Annotated[
    str | None, typer.Argument(help="Defaults to the checked-out collection.")
]

ORGANIZATION_COLUMNS = [
    Column("NAME", lambda o: o["name"]),
    Column("DISPLAY NAME", lambda o: o["display_name"]),
    Column("CATALOGS", lambda o: o["catalog_count"]),
    Column("CREATED BY", lambda o: o["created_by"]),
]

CATALOG_COLUMNS = [
    Column("NAME", lambda c: c["name"]),
    Column("ORGANIZATION", lambda c: c["organization"]),
    Column("SCHEMA", lambda c: f"{c['schema']['name']} v{c['schema']['version']}"),
    Column("NAMESPACES", lambda c: c["namespace_count"]),
]

COLLECTION_COLUMNS = [
    Column("COLLECTION", lambda c: c["identifier"]),
    Column("STATE", lambda c: c["state"]),
    Column("VERSION", lambda c: c["version"]),
    Column("FILES", lambda c: c["file_count"]),
    Column("TITLE", lambda c: c["metadata"].get("title")),
]

NAMESPACE_COLUMNS = [
    Column("NAMESPACE", lambda n: n["identifier"]),
    Column("COLLECTIONS", lambda n: "allowed" if n["collections_allowed"] else "-"),
    Column("CHILDREN", lambda n: n["namespace_count"]),
    Column("COUNT", lambda n: n["collection_count"]),
]


def services(ctx: typer.Context) -> Services:
    """The services the root command was given."""
    found: Services = ctx.obj
    return found


def api(ctx: typer.Context) -> ApiClient:
    """The authenticated API client."""
    return services(ctx).api()


def organization_path(ctx: typer.Context, organization: Mapping[str, Any]) -> str:
    """Where an organization's directory is: its configured ``path``, else under the prefix.

    Under the prefix it is marked ``(prefix)``, or ``(undeclared)`` for an organization the
    managed service configuration does not declare, whose real root is unknown.
    """
    path = organization.get("path")
    if path:
        return str(path)
    found = services(ctx)
    prefix = found.config.mount_prefix.rstrip("/")
    undeclared = not organization.get("declared") and found.mount().managed()
    return f"{prefix}/{organization['name']} ({'undeclared' if undeclared else 'prefix'})"


def organization_columns(ctx: typer.Context) -> list[Column]:
    """The organization table's columns, ending with its ``PATH``."""
    return [*ORGANIZATION_COLUMNS, Column("PATH", lambda o: organization_path(ctx, o))]


def current_column(current: str | None) -> Column:
    """A leading ``CURRENT`` column: ``*`` on the row named ``current``, blank elsewhere."""
    return Column("CURRENT", lambda row: "*" if row["name"] == current else "")


def catalog_rows(ctx: typer.Context, organization: str | None) -> list[dict[str, Any]]:
    """The catalogs the user can see, in ``organization`` only unless it is ``None``."""
    params = None if organization is None else {"organization": organization}
    try:
        return list(api(ctx).pages("/api/v1/catalogs", params))
    except CliError as error:
        explain_missing_organization(ctx, organization, error)
        raise


def explain_missing_organization(
    ctx: typer.Context, organization: str | None, error: CliError
) -> None:
    """Hint how to recover when ``error`` is the saved current organization not being found."""
    saved = services(ctx).organization()
    if error.exit_code is ExitCode.NOT_FOUND and organization is not None and organization == saved:
        error.hint = (
            f"the current organization {organization} no longer exists or is hidden from you;"
            " switch with: huron org <name>"
        )


def empty_organization(organization: str) -> str:
    """The line saying ``organization`` holds no catalogs the user can see."""
    return (
        f"Organization {organization} has no catalogs you can see;"
        " see every organization's with: huron get catalogs -A"
    )


def table_mode(ctx: typer.Context) -> bool:
    """Whether output is the human table format (not JSON or YAML)."""
    return services(ctx).output is OutputFormat.TABLE


def show_list(
    ctx: typer.Context, rows: Iterable[Mapping[str, Any]], columns: Sequence[Column]
) -> None:
    """Print rows in the chosen output format."""
    found = services(ctx)
    render(found.out, rows, columns, found.output)


def show(ctx: typer.Context, item: Mapping[str, Any]) -> None:
    """Print one object in the chosen output format."""
    found = services(ctx)
    render_one(found.out, item, found.output)


def say(ctx: typer.Context, message: str) -> None:
    """A plain progress or result line on standard output (not in JSON or YAML mode)."""
    if table_mode(ctx):
        services(ctx).out.print(message, markup=False, highlight=False)


def fetch_collection(ctx: typer.Context, identifier: str | None) -> dict[str, Any]:
    """A collection by identifier, or the checked-out one when none is given."""
    found = services(ctx)
    if identifier is None:
        current = found.config.current_collection
        if current is None:
            raise UsageError(
                "no collection is checked out",
                hint="run: huron checkout <identifier>, or huron checkout to pick one",
            )
        collection: dict[str, Any] = api(ctx).get(f"/api/v1/collections/{current}")
        return collection
    candidates = collection_candidates(identifier, found.catalog())
    return locate(
        ctx,
        "collection",
        candidates,
        lambda parsed: api(ctx).get(
            f"/api/v1/catalogs/{parsed.catalog}/collections/{parsed.namespace}.{parsed.name}"
        ),
    )[1]


def fetch_namespace(ctx: typer.Context, identifier: str) -> tuple[Identifier, dict[str, Any]]:
    """A namespace by identifier (relative to the current catalog, else as written) and its view."""
    candidates = namespace_candidates(identifier, services(ctx).catalog())
    return locate(
        ctx,
        "namespace",
        candidates,
        lambda parsed: api(ctx).get(
            f"/api/v1/catalogs/{parsed.catalog}/namespaces/{parsed.namespace}"
        ),
    )


def locate(
    ctx: typer.Context,
    kind: str,
    candidates: Sequence[Identifier],
    lookup: Callable[[Identifier], dict[str, Any]],
) -> tuple[Identifier, dict[str, Any]]:
    """The first of ``candidates`` the API knows, with what ``lookup`` fetched for it.

    Only a not-found answer moves on to the next candidate; when none is found, the error names
    every identifier tried, so a relative identifier's catalog prefix is visible.
    """
    for candidate in candidates:
        try:
            return candidate, lookup(candidate)
        except CliError as error:
            if error.exit_code is not ExitCode.NOT_FOUND:
                raise
    tried = " or ".join(str(candidate) for candidate in candidates)
    current = services(ctx).catalog()
    hint = (
        None
        if current is None
        else f"identifiers are relative to the current catalog {current}; see it with: huron tree"
    )
    raise CliError(f"{kind} {tried} not found", ExitCode.NOT_FOUND, code="NOT_FOUND", hint=hint)


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


def kind_of(view: Mapping[str, object]) -> DirectoryKind:
    """The directory kind of a namespace."""
    if view["collections_allowed"]:
        return DirectoryKind.NAMESPACE_WITH_COLLECTIONS
    return DirectoryKind.NAMESPACE


def grant_sources(ctx: typer.Context, catalog: str) -> list[dict[str, Any]]:
    """Every (role, group, scope) that gives a role on ``catalog``, sorted by role then group.

    ``scope`` is ``platform``, ``organization`` (inherited from the catalog's organization) or
    ``catalog`` (granted on the catalog itself).
    """
    items: list[dict[str, Any]] = api(ctx).get(f"/api/v1/catalogs/{catalog}/grants/sources")[
        "items"
    ]
    return items


def set_groups(ctx: typer.Context, path: str, groups: list[str]) -> dict[str, Any]:
    """Replace a role's groups and report what changed."""
    change: dict[str, Any] = api(ctx).put(path, json={"ldap_groups": groups})
    added = ", ".join(change["added"]) or "-"
    removed = ", ".join(change["removed"]) or "-"
    say(ctx, f"{change['role']}: added {added}; removed {removed}")
    return change


def read_document(path: Path) -> dict[str, object]:
    """A JSON object from ``path``."""
    try:
        document = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise UsageError(f"cannot read {path}: {error}") from error
    if not isinstance(document, dict):
        raise UsageError(f"{path} must hold a JSON object")
    return document
