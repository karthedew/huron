"""``huron status``: the checked-out collection's staged changes, or every working copy's."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated, Any

import typer

from huron.applications.cli.commands.common import say, services, show, show_list, table_mode
from huron.applications.cli.commands.context import (
    CHOOSE_CATALOG,
    checked_out,
    context_report,
    organization_in_view,
    share_files,
)
from huron.applications.cli.localstate import WorkingState
from huron.applications.cli.output import Column, human_size

__all__ = ["STAGED_COLUMNS", "CopyStatus", "register", "staged_rows", "status"]

STAGED_COLUMNS = [
    Column("STAGED", lambda row: row["action"]),
    Column("PATH", lambda row: row["rel_path"]),
    Column("SIZE", lambda row: None if row["size"] is None else human_size(row["size"])),
    Column("UPLOAD", lambda row: row["upload"]),
    Column("FROM", lambda row: row["source"], overflow="fold"),
]
"""The table of staged changes; ``-`` stands for what a remove has not, and for the upload state
of an add before its upload starts.

A long source path wraps rather than losing its end, the file name that tells rows apart.
"""

NOTHING_STAGED = "Nothing is staged. To stage files, run `huron add <file>`"
PUSH_HINT = 'To push, run `huron push -m "<message>"`. To unstage a path, run `huron rm <path>`'
NOTHING_ANYWHERE = "Nothing is staged in any working copy"


@dataclass(frozen=True, slots=True)
class CopyStatus:
    """One working copy's status: its state and, for the checked-out copy, the service's view.

    ``collection`` is the service's view of the checked-out copy; ``None`` for the other working
    copies, which are read from the state directory alone. ``organization`` is the collection's
    own: the service's for the checked-out copy, the first segment of the recorded path
    (``<organization>/<catalog>/…``) for the others. ``unrecorded`` is ``None`` when the share is
    not mounted here, and is only checked for the checked-out copy. ``unreadable`` are the
    entries of the collection's directory that the CLI cannot read there.
    """

    working: WorkingState
    collection: dict[str, Any] | None = None
    organization: str | None = None
    unrecorded: list[str] | None = None
    unreadable: list[str] = field(default_factory=list)

    @property
    def current(self) -> bool:
        """Whether this is the checked-out copy (the only one the service was asked about)."""
        return self.collection is not None

    @property
    def catalog(self) -> str:
        """The catalog the collection belongs to."""
        if self.collection is not None:
            return str(self.collection["catalog"])
        return self.working.identifier.split(".")[0]

    @property
    def behind(self) -> bool | None:
        """Whether the service holds a newer version; ``None`` when it was not asked."""
        if self.collection is None:
            return None
        return int(self.collection["version"]) != self.working.base_version

    def header(self) -> str:
        """``On collection … (version N, up to date) in catalog c, organization o``."""
        version = f"version {self.working.base_version}"
        if self.collection is not None:
            service = int(self.collection["version"])
            behind = f", behind the service's version {service}"
            version += behind if self.behind else ", up to date"
        where = f" in catalog {self.catalog}"
        if self.organization is not None:
            where += f", organization {self.organization}"
        return f"On collection {self.working.identifier} ({version}){where}"

    def report(self, organization: str | None, catalog: str | None) -> dict[str, object]:
        """The machine-readable status, with ``organization`` and ``catalog`` of the context.

        ``pending_commit`` is the request ID of the commit whose result the CLI did not get.
        """
        view, pending = self.collection, self.working.pending_commit
        return {
            "organization": organization,
            "catalog": catalog,
            "collection": self.working.identifier,
            "state": None if view is None else view["state"],
            "your_version": self.working.base_version,
            "service_version": None if view is None else view["version"],
            "behind": self.behind,
            "adds": [add.rel_path for add in self.working.adds],
            "removes": list(self.working.removes),
            "unrecorded": self.unrecorded,
            "unreadable": self.unreadable,
            "staged": staged_rows(self.working),
            "pending_commit": None if pending is None else pending.request_id,
        }


def register(app: typer.Typer, panel: str) -> None:
    """Add ``huron status`` under the help panel ``panel``."""
    app.command("status", rich_help_panel=panel)(status)


def staged_rows(stage: WorkingState) -> list[dict[str, object]]:
    """The staged adds then removes, as ``{action, rel_path, size, upload, source}`` rows.

    ``upload`` is the last state of the add's upload attempt that the CLI read on the service,
    ``None`` before its upload starts and for a remove.
    """
    adds: list[dict[str, object]] = [
        {
            "action": "add",
            "rel_path": add.rel_path,
            "size": add.size,
            "upload": add.attempt_state,
            "source": add.source,
        }
        for add in stage.adds
    ]
    removes: list[dict[str, object]] = [
        {"action": "remove", "rel_path": path, "size": None, "upload": None, "source": None}
        for path in stage.removes
    ]
    return adds + removes


def status(
    ctx: typer.Context,
    every: Annotated[
        bool,
        typer.Option(
            "--all", help="Show all working copies on this machine, not only the current one."
        ),
    ] = False,
) -> None:
    """Show where you are, and the staged changes and drift of the current collection.

    The UPLOAD column gives the last state of the upload of each staged file. When the CLI did
    not get the result of the last commit, the status gives the ID of that commit request.

    With `--all`, show all working copies on this machine that hold staged changes. A `*` marks
    the current collection. The CLI compares only the current collection with the service and
    the share. Each entry names the catalog and the organization of its collection.
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
            say(ctx, f"There is no current catalog. {CHOOSE_CATALOG}")
        else:
            say(ctx, "There is no current collection. To choose one, run `huron checkout`")
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
        _checked_out_status(ctx, working)
        if working.collection_id == selected
        else _offline_status(working)
        for working in found.state.working_copies()
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
    staged = [item for item in statuses if not item.working.empty]
    shown = staged or [item for item in statuses if item.current]
    for index, item in enumerate(shown):
        if index:
            say(ctx, "")
        _section(ctx, item, alone=False)
    if not statuses:
        say(
            ctx,
            "There are no working copies on this machine."
            " To make one, run `huron checkout <identifier>`",
        )
    if not staged:
        say(ctx, NOTHING_ANYWHERE)


def _checked_out_status(ctx: typer.Context, working: WorkingState) -> CopyStatus:
    found = services(ctx)
    collection: dict[str, Any] = found.api().get(f"/api/v1/collections/{working.collection_id}")
    files = share_files(ctx, collection)
    if files is None:
        return CopyStatus(working, collection, collection.get("organization"))
    return CopyStatus(
        working, collection, collection.get("organization"), files.unrecorded, files.unreadable
    )


def _offline_status(working: WorkingState) -> CopyStatus:
    """A copy other than the checked-out one, from its ``working.json`` alone."""
    organization = None if not working.path else working.path.split("/")[0]
    return CopyStatus(working, organization=organization)


def _section(ctx: typer.Context, item: CopyStatus, *, alone: bool) -> None:
    """One copy in table mode; ``alone`` when it is the only one shown (plain ``status``)."""
    marker = "* " if item.current and not alone else ""
    say(ctx, marker + item.header())
    rows = staged_rows(item.working)
    if rows:
        show_list(ctx, rows, STAGED_COLUMNS)
    if item.current:
        _drift(ctx, item)
    pending = item.working.pending_commit
    if pending is not None:
        say(
            ctx,
            f"The CLI did not get the result of the commit request {pending.request_id}."
            " To get the result, run `huron push`",
        )
    elif not rows:
        if alone:
            say(ctx, NOTHING_STAGED)
    elif item.current:
        say(ctx, PUSH_HINT)
    else:
        say(
            ctx,
            "To push or unstage these changes,"
            f" run `huron checkout {item.working.identifier}` first",
        )


def _drift(ctx: typer.Context, item: CopyStatus) -> None:
    if item.unrecorded is None:
        say(
            ctx,
            "The share is not mounted on this machine. The CLI did not check for unrecorded files",
        )
    elif item.unrecorded:
        say(ctx, f"Unrecorded files on the share: {', '.join(item.unrecorded)}")
    if item.unreadable:
        say(ctx, f"The CLI cannot read these entries on the share: {', '.join(item.unreadable)}")
    if item.behind:
        say(ctx, "Your working copy is behind the service. Run `huron pull`")
