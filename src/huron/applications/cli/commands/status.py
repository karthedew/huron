"""``huron status``: the checked-out collection's staged changes, or every working copy's."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any

import typer

from huron.applications.cli.commands.common import say, services, show, show_list, table_mode
from huron.applications.cli.commands.context import (
    CHOOSE_CATALOG,
    checked_out,
    context_report,
    organization_in_view,
    unrecorded_files,
)
from huron.applications.cli.output import Column, human_size
from huron.applications.cli.state import Stage, WorkingCopy

__all__ = ["STAGED_COLUMNS", "CopyStatus", "register", "staged_rows", "status"]

STAGED_COLUMNS = [
    Column("STAGED", lambda row: row["action"]),
    Column("PATH", lambda row: row["rel_path"]),
    Column("SIZE", lambda row: None if row["size"] is None else human_size(row["size"])),
    Column("FROM", lambda row: row["source"], overflow="fold"),
]
"""The table of staged changes; ``-`` stands for what a remove has not.

A long source path wraps rather than losing its end, the file name that tells rows apart.
"""

NOTHING_STAGED = "nothing staged; stage files with: huron add <file>"
PUSH_HINT = 'push with: huron push -m "<message>" · unstage with: huron rm <path>'
NOTHING_ANYWHERE = "nothing staged in any working copy"


@dataclass(frozen=True, slots=True)
class CopyStatus:
    """One working copy's status: its stage and, for the checked-out copy, the service's view.

    ``collection`` is the service's view of the checked-out copy; ``None`` for the other working
    copies, which are read from the state directory alone. ``organization`` is the collection's
    own: the service's for the checked-out copy, the first segment of the recorded path
    (``<organization>/<catalog>/…``) for the others. ``unrecorded`` is ``None`` when the share is
    not mounted here, and is only checked for the checked-out copy.
    """

    copy: WorkingCopy
    stage: Stage
    collection: dict[str, Any] | None = None
    organization: str | None = None
    unrecorded: list[str] | None = None

    @property
    def current(self) -> bool:
        """Whether this is the checked-out copy (the only one the service was asked about)."""
        return self.collection is not None

    @property
    def catalog(self) -> str:
        """The catalog the collection belongs to."""
        if self.collection is not None:
            return str(self.collection["catalog"])
        return self.copy.identifier.split(".")[0]

    @property
    def behind(self) -> bool | None:
        """Whether the service holds a newer version; ``None`` when it was not asked."""
        if self.collection is None:
            return None
        return int(self.collection["version"]) != self.copy.version

    def header(self) -> str:
        """``On collection … (version N, up to date) in catalog c, organization o``."""
        version = f"version {self.copy.version}"
        if self.collection is not None:
            service = int(self.collection["version"])
            behind = f", behind the service's version {service}"
            version += behind if self.behind else ", up to date"
        where = f" in catalog {self.catalog}"
        if self.organization is not None:
            where += f", organization {self.organization}"
        return f"On collection {self.copy.identifier} ({version}){where}"

    def report(self, organization: str | None, catalog: str | None) -> dict[str, object]:
        """The machine-readable status, with ``organization`` and ``catalog`` of the context."""
        view = self.collection
        return {
            "organization": organization,
            "catalog": catalog,
            "collection": self.copy.identifier,
            "state": None if view is None else view["state"],
            "your_version": self.copy.version,
            "service_version": None if view is None else view["version"],
            "behind": self.behind,
            "adds": [add.rel_path for add in self.stage.adds],
            "removes": list(self.stage.removes),
            "unrecorded": self.unrecorded,
            "staged": staged_rows(self.stage),
        }


def register(app: typer.Typer, panel: str) -> None:
    """Add ``huron status`` under the help panel ``panel``."""
    app.command("status", rich_help_panel=panel)(status)


def staged_rows(stage: Stage) -> list[dict[str, object]]:
    """The staged adds then removes, as ``{action, rel_path, size, source}`` rows."""
    adds: list[dict[str, object]] = [
        {"action": "add", "rel_path": add.rel_path, "size": add.size, "source": add.source}
        for add in stage.adds
    ]
    removes: list[dict[str, object]] = [
        {"action": "remove", "rel_path": path, "size": None, "source": None}
        for path in stage.removes
    ]
    return adds + removes


def status(
    ctx: typer.Context,
    every: Annotated[
        bool,
        typer.Option("--all", help="Every working copy on this machine, not only the current one."),
    ] = False,
) -> None:
    """Where you are, and the checked-out collection's staged changes and drift.

    With --all: every working copy on this machine that has something staged, the checked-out
    one marked *. Only the checked-out one is compared with the service and the share. Each
    entry names its collection's own catalog and organization.
    """
    if every:
        _every_copy(ctx)
        return
    found = services(ctx)
    copy = checked_out(found)
    current = found.catalog()
    scope = organization_in_view(ctx, current)
    if copy is None:
        show(ctx, context_report(found, scope, current, None))
        if current is None:
            say(ctx, f"no catalog is selected; {CHOOSE_CATALOG}")
        else:
            say(ctx, "no collection is checked out; pick one with: huron checkout")
        return
    checked = _checked_out_status(ctx, copy)
    if not table_mode(ctx):
        show(ctx, checked.report(scope, current))
        return
    _section(ctx, checked, alone=True)


def _every_copy(ctx: typer.Context) -> None:
    found = services(ctx)
    selected = found.config.current_collection
    statuses = [
        _checked_out_status(ctx, copy)
        if copy.collection_id == selected
        else _offline_status(ctx, copy)
        for copy in found.state.working_copies()
    ]
    if table_mode(ctx):
        _show_every(ctx, statuses)
        return
    reports = [
        {**item.report(item.organization, item.catalog), "current": item.current}
        for item in statuses
    ]
    show_list(ctx, reports, [])


def _show_every(ctx: typer.Context, statuses: list[CopyStatus]) -> None:
    """Sections of the copies with something staged; of the checked-out copy alone when none has."""
    staged = [item for item in statuses if not item.stage.empty]
    shown = staged or [item for item in statuses if item.current]
    for index, item in enumerate(shown):
        if index:
            say(ctx, "")
        _section(ctx, item, alone=False)
    if not statuses:
        say(ctx, "no working copies here; check one out with: huron checkout <identifier>")
    if not staged:
        say(ctx, NOTHING_ANYWHERE)


def _checked_out_status(ctx: typer.Context, copy: WorkingCopy) -> CopyStatus:
    found = services(ctx)
    collection: dict[str, Any] = found.api().get(f"/api/v1/collections/{copy.collection_id}")
    return CopyStatus(
        copy,
        found.state.read_stage(copy.collection_id),
        collection,
        collection.get("organization"),
        unrecorded_files(ctx, collection),
    )


def _offline_status(ctx: typer.Context, copy: WorkingCopy) -> CopyStatus:
    """A copy other than the checked-out one, from ``copy.json`` and ``stage.json`` alone."""
    found = services(ctx)
    organization = None if not copy.path else copy.path.split("/")[0]
    return CopyStatus(copy, found.state.read_stage(copy.collection_id), organization=organization)


def _section(ctx: typer.Context, item: CopyStatus, *, alone: bool) -> None:
    """One copy in table mode; ``alone`` when it is the only one shown (plain ``status``)."""
    marker = "* " if item.current and not alone else ""
    say(ctx, marker + item.header())
    rows = staged_rows(item.stage)
    if rows:
        show_list(ctx, rows, STAGED_COLUMNS)
    if item.current:
        _drift(ctx, item)
    if not rows:
        if alone:
            say(ctx, NOTHING_STAGED)
    elif item.current:
        say(ctx, PUSH_HINT)
    else:
        say(ctx, f"check it out to push or unstage: huron checkout {item.copy.identifier}")


def _drift(ctx: typer.Context, item: CopyStatus) -> None:
    if item.unrecorded is None:
        say(ctx, "share not mounted here; unrecorded files are not checked")
    elif item.unrecorded:
        say(ctx, f"Unrecorded on the share: {', '.join(item.unrecorded)}")
    if item.behind:
        say(ctx, "behind: run huron pull")
