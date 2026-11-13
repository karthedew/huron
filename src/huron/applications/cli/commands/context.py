"""``huron org`` and ``huron catalog``: where you are, like ``oc project``."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Annotated, Any

import typer

from huron.applications.cli.commands.common import (
    CATALOG_COLUMNS,
    api,
    catalog_rows,
    current_column,
    empty_organization,
    fetch_catalog,
    organization_columns,
    say,
    services,
    show,
    show_list,
    table_mode,
)
from huron.applications.cli.errors import CliError, ExitCode
from huron.applications.cli.localstate import WorkingState
from huron.applications.cli.output import Column
from huron.applications.cli.services import Services
from huron.applications.cli.sync import recorded_files
from huron.core.storage import (
    Entry,
    LakePath,
    LakeUnavailable,
    ShareReader,
    StorageError,
    SymlinkInLake,
    is_ignored_entry,
)
from huron.schema.naming import rel_path_key

__all__ = [
    "CHOOSE_CATALOG",
    "ShareFiles",
    "catalog",
    "checked_out",
    "context_report",
    "organization",
    "organization_in_view",
    "register",
    "share_files",
]

CHOOSE_CATALOG = "To list the catalogs, run `huron catalog`. Then run `huron catalog <name>`"
SWITCH_ORGANIZATION = "To select an organization, run `huron org <name>`"
SWITCH_CATALOG = "To select a catalog, run `huron catalog <name>`"


def register(app: typer.Typer, panels: Mapping[str, str]) -> None:
    """Add ``huron org`` and ``huron catalog``, each under its help panel in ``panels``."""
    app.command("org", rich_help_panel=panels["org"])(organization)
    app.command("catalog", rich_help_panel=panels["catalog"])(catalog)


def checked_out(found: Services) -> WorkingState | None:
    """The checked-out working copy, if any."""
    collection_id = found.config.current_collection
    return None if collection_id is None else found.state.working(collection_id)


def organization(
    ctx: typer.Context,
    name: Annotated[
        str | None,
        typer.Argument(
            help=(
                "Select this organization. With no argument, list the organizations"
                " and mark the current one."
            )
        ),
    ] = None,
) -> None:
    """List the organizations that you can see and mark the current one, or select one."""
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
    _listing(ctx, rows, organization_columns(ctx), current, "You can see no organizations")
    if any(row["name"] == current for row in rows):
        say(ctx, f"The current organization is {current} on {url}")
        return
    if current is None:
        say(ctx, f"There is no current organization on {url}")
    else:
        say(ctx, f"The current organization {current} no longer exists, or you cannot see it")
    say(ctx, SWITCH_ORGANIZATION)


def catalog(
    ctx: typer.Context,
    name: Annotated[
        str | None,
        typer.Argument(
            help=(
                "Select this catalog. With no argument, list the catalogs and mark the current one."
            )
        ),
    ] = None,
) -> None:
    """List the catalogs of the current organization and mark the current one, or select one."""
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
    found: Services, organization: str | None, current: str | None, copy: WorkingState | None
) -> dict[str, object]:
    """Where you are: the organization and catalog in view, the API and the checked-out copy."""
    return {
        "organization": organization,
        "catalog": current,
        "api_url": found.config.api_url,
        "collection": None if copy is None else copy.identifier,
    }


@dataclass(frozen=True, slots=True)
class ShareFiles:
    """What the share holds in a collection's directory beyond its records.

    ``unrecorded`` are the files that no commit recorded, by their paths in the collection.
    ``unreadable`` are the entries that the CLI cannot stat or list, by their API paths.
    """

    unrecorded: list[str] = field(default_factory=list)
    unreadable: list[str] = field(default_factory=list)


def share_files(ctx: typer.Context, collection: dict[str, Any]) -> ShareFiles | None:
    """The unrecorded and unreadable entries of the collection's directory; ``None`` when the
    share is not mounted here.

    A draft has no directory, and a missing directory holds nothing. An entry that the CLI
    cannot stat or list is unreadable, as in ``huron adm check``, and never stops the command.
    """
    if collection.get("path") is None:
        return ShareFiles()
    try:
        storage, directory = services(ctx).mount().locate(str(collection["path"]))
    except CliError:
        return None
    entries = _collection_entries(storage, directory)
    if entries is None:
        return ShareFiles(unreadable=[str(directory)])
    unreadable = _unreadable(directory, entries)
    candidates = _unnamed(entries)
    if not candidates:
        return ShareFiles(unreadable=unreadable)
    recorded = recorded_files(services(ctx).api(), str(collection["id"]))
    unrecorded = [rel_path for rel_path in candidates if rel_path_key(rel_path) not in recorded]
    return ShareFiles(unrecorded, unreadable)


def _collection_entries(storage: ShareReader, directory: LakePath) -> list[Entry] | None:
    """The entries of a collection directory: none when it is missing, ``None`` when the CLI
    cannot stat or list it. A link and a lake that is not mounted are errors.
    """
    try:
        if storage.stat(directory) is None:
            return []
        return list(storage.walk(directory))
    except (LakeUnavailable, SymlinkInLake):
        raise
    except StorageError:
        return None


def _unreadable(directory: LakePath, entries: list[Entry]) -> list[str]:
    """The API paths of the entries that the CLI cannot stat or list."""
    return [str(directory.joinpath(*e.names)) for e in entries if e.kind == "unreadable"]


def _unnamed(entries: list[Entry]) -> list[str]:
    """The paths of the files in ``entries``, except Huron's own files and the ``.nfs*`` files
    of an NFS client (:func:`is_ignored_entry`). The path rules refuse these names, so no commit
    records them.
    """
    found = ("/".join(e.names) for e in entries if e.kind == "file")
    return [rel_path for rel_path in found if not is_ignored_entry(rel_path)]


def _switch_organization(ctx: typer.Context, name: str) -> None:
    found = services(ctx)
    api(ctx).get(f"/api/v1/organizations/{name}")
    selected = found.config.current_catalog
    owner = None if selected is None else _owner(ctx, selected)
    kept = selected if owner == name else None
    found.save_config(replace(found.config, current_organization=name, current_catalog=kept))
    say(ctx, f"The current organization is now {name} on {found.config.api_url}")
    if selected is not None and kept is None:
        reason = (
            f"you cannot see catalog {selected}"
            if owner is None
            else f"catalog {selected} belongs to {owner}"
        )
        say(
            ctx,
            f"There is no current catalog now, because {reason}."
            " To list the catalogs, run `huron catalog`",
        )


def _switch_catalog(ctx: typer.Context, name: str) -> None:
    found = services(ctx)
    view = fetch_catalog(ctx, name)
    owner = str(view["organization"])
    changed = owner != found.organization()
    found.save_config(replace(found.config, current_catalog=name, current_organization=owner))
    say(ctx, f"The current catalog is now {name} on {found.config.api_url}")
    if changed:
        say(ctx, f"The current organization is now {owner}")


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
    empty = "You can see no catalogs" if scope is None else empty_organization(scope)
    _listing(ctx, rows, CATALOG_COLUMNS, current, empty)
    if current is None:
        say(ctx, f"There is no current catalog on {url}")
        say(ctx, SWITCH_CATALOG)
        return
    owner = next((row["organization"] for row in rows if row["name"] == current), None)
    where = "" if owner is None else f" in organization {owner}"
    say(ctx, f"The current catalog is {current}{where} on {url}")


def _report_copy(ctx: typer.Context, current: str | None, copy: WorkingState | None) -> None:
    if copy is None:
        if current is not None:
            say(ctx, "There is no current collection. To choose one, run `huron checkout`")
        return
    owner = copy.identifier.split(".")[0]
    checked = f"Current collection: {copy.identifier} (version {copy.base_version})"
    if owner == current:
        say(ctx, checked)
    elif current is None:
        say(ctx, f"{checked}, in catalog {owner}")
    else:
        say(
            ctx,
            f"{checked}, in catalog {owner}. To choose one in this catalog, run `huron checkout`",
        )
