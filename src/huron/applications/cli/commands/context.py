"""``huron org`` and ``huron catalog``: where you are, like ``oc project``."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Annotated, Any

import typer

from huron.applications.cli.commands.common import (
    CATALOG_COLUMNS,
    api,
    catalog_rows,
    current_column,
    empty_organization,
    organization_columns,
    say,
    services,
    show,
    show_list,
    table_mode,
)
from huron.applications.cli.errors import CliError, ExitCode
from huron.applications.cli.output import Column
from huron.applications.cli.services import Services
from huron.applications.cli.state import WorkingCopy
from huron.applications.cli.sync import recorded_files
from huron.core.storage import is_reserved_entry
from huron.schema.naming import rel_path_key

__all__ = [
    "CHOOSE_CATALOG",
    "catalog",
    "checked_out",
    "context_report",
    "organization",
    "organization_in_view",
    "register",
    "unrecorded_files",
]

CHOOSE_CATALOG = "list them with: huron catalog; then run: huron catalog <name>"
SWITCH_ORGANIZATION = "switch with: huron org <name>"
SWITCH_CATALOG = "switch with: huron catalog <name>"


def register(app: typer.Typer, panels: Mapping[str, str]) -> None:
    """Add ``huron org`` and ``huron catalog``, each under its help panel in ``panels``."""
    app.command("org", rich_help_panel=panels["org"])(organization)
    app.command("catalog", rich_help_panel=panels["catalog"])(catalog)


def checked_out(found: Services) -> WorkingCopy | None:
    """The checked-out working copy, if any."""
    collection_id = found.config.current_collection
    return None if collection_id is None else found.state.read_copy(collection_id)


def organization(
    ctx: typer.Context,
    name: Annotated[
        str | None,
        typer.Argument(
            help="Switch to this organization; list them and the current one if omitted."
        ),
    ] = None,
) -> None:
    """List the organizations you can see and mark the current one, or switch to another."""
    found = services(ctx)
    if name is not None:
        _switch_organization(ctx, name)
        if table_mode(ctx):
            return
    rows = list(api(ctx).pages("/api/v1/organizations"))
    current = found.organization()
    url = found.config.api_url
    if not table_mode(ctx):
        show(ctx, {"organization": current, "api_url": url, "organizations": rows})
        return
    _listing(ctx, rows, organization_columns(ctx), current, "You can see no organizations.")
    if any(row["name"] == current for row in rows):
        say(ctx, f"Using organization {current} on {url}")
        return
    if current is None:
        say(ctx, f"No organization is selected on {url}.")
    else:
        say(ctx, f"The current organization {current} no longer exists or is hidden from you.")
    say(ctx, SWITCH_ORGANIZATION)


def catalog(
    ctx: typer.Context,
    name: Annotated[
        str | None,
        typer.Argument(help="Switch to this catalog; list them and the current one if omitted."),
    ] = None,
) -> None:
    """List the catalogs of the current organization and mark the current one, or switch."""
    found = services(ctx)
    if name is not None:
        _switch_catalog(ctx, name)
    current = name or found.catalog()
    copy = checked_out(found)
    if name is not None and table_mode(ctx):
        _report_copy(ctx, current, copy)
        return
    scope = organization_in_view(ctx, current)
    rows = catalog_rows(ctx, scope)
    if not table_mode(ctx):
        show(ctx, {**context_report(found, scope, current, copy), "catalogs": rows})
        return
    _show_catalogs(ctx, rows, scope, current)
    _report_copy(ctx, current, copy)


def organization_in_view(ctx: typer.Context, current: str | None) -> str | None:
    """The organization in view: the saved one, or the owner of a ``--catalog`` override."""
    found = services(ctx)
    if current is None or current == found.config.current_catalog:
        return found.organization()
    return _owner(ctx, current)


def context_report(
    found: Services, organization: str | None, current: str | None, copy: WorkingCopy | None
) -> dict[str, object]:
    """Where you are: the organization and catalog in view, the API and the checked-out copy."""
    return {
        "organization": organization,
        "catalog": current,
        "api_url": found.config.api_url,
        "collection": None if copy is None else copy.identifier,
    }


def unrecorded_files(ctx: typer.Context, collection: dict[str, Any]) -> list[str] | None:
    """Files in the collection's directory that are not recorded; ``None`` when not mounted here.

    A draft has no directory, so nothing in it is unrecorded.
    """
    if collection.get("path") is None:
        return []
    mount = services(ctx).mount()
    try:
        directory = mount.path(str(collection["path"]))
    except CliError:
        return None
    storage = mount.storage
    recorded = recorded_files(services(ctx).api(), str(collection["id"]))
    return [
        entry.rel_path
        for entry in storage.walk(directory)
        if entry.kind == "file"
        and not is_reserved_entry(entry.rel_path)
        and rel_path_key(entry.rel_path) not in recorded
    ]


def _switch_organization(ctx: typer.Context, name: str) -> None:
    found = services(ctx)
    api(ctx).get(f"/api/v1/organizations/{name}")
    selected = found.config.current_catalog
    owner = None if selected is None else _owner(ctx, selected)
    kept = selected if owner == name else None
    found.save_config(replace(found.config, current_organization=name, current_catalog=kept))
    say(ctx, f"Now using organization {name} on {found.config.api_url}")
    if selected is not None and kept is None:
        reason = "you cannot see it" if owner is None else f"it belongs to {owner}"
        say(ctx, f"Cleared catalog {selected} ({reason}); pick one with: huron catalog")


def _switch_catalog(ctx: typer.Context, name: str) -> None:
    found = services(ctx)
    view = api(ctx).get(f"/api/v1/catalogs/{name}")
    owner = str(view["organization"])
    changed = owner != found.organization()
    found.save_config(replace(found.config, current_catalog=name, current_organization=owner))
    say(ctx, f"Now using catalog {name} on {found.config.api_url}")
    if changed:
        say(ctx, f"Switched organization to {owner}")


def _owner(ctx: typer.Context, catalog_name: str) -> str | None:
    """The organization of ``catalog_name``, or ``None`` when it cannot be found."""
    try:
        view = api(ctx).get(f"/api/v1/catalogs/{catalog_name}")
    except CliError as error:
        if error.exit_code is not ExitCode.NOT_FOUND:
            raise
        return None
    return str(view["organization"])


def _listing(
    ctx: typer.Context,
    rows: Sequence[dict[str, Any]],
    columns: Sequence[Column],
    current: str | None,
    empty: str,
) -> None:
    if rows:
        show_list(ctx, rows, [current_column(current), *columns])
    else:
        say(ctx, empty)


def _show_catalogs(
    ctx: typer.Context,
    rows: Sequence[dict[str, Any]],
    scope: str | None,
    current: str | None,
) -> None:
    url = services(ctx).config.api_url
    empty = "You can see no catalogs." if scope is None else empty_organization(scope)
    _listing(ctx, rows, CATALOG_COLUMNS, current, empty)
    if current is None:
        say(ctx, f"No catalog is selected on {url}.")
        say(ctx, SWITCH_CATALOG)
        return
    owner = next((row["organization"] for row in rows if row["name"] == current), None)
    where = "" if owner is None else f" in organization {owner}"
    say(ctx, f"Using catalog {current}{where} on {url}")


def _report_copy(ctx: typer.Context, current: str | None, copy: WorkingCopy | None) -> None:
    if copy is None:
        if current is not None:
            say(ctx, "No collection is checked out; pick one with: huron checkout")
        return
    owner = copy.identifier.split(".")[0]
    checked = f"Checked out: {copy.identifier} (version {copy.version})"
    if owner == current:
        say(ctx, checked)
    elif current is None:
        say(ctx, f"{checked}, in catalog {owner}")
    else:
        say(ctx, f"{checked}, in catalog {owner}; pick one here with: huron checkout")
