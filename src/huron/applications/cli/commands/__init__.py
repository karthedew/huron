"""Command groups; ``register`` adds every one of them to the root app under its help panel."""

from __future__ import annotations

from typing import Any

import typer
from typer.core import TyperGroup

from huron.applications.cli.commands import (
    adm,
    change,
    context,
    create,
    delete,
    describe,
    explore,
    get,
    session,
    stage,
    status,
)

__all__ = ["LAYOUT", "PANELS", "PANEL_OF", "VERBS", "VerbGroup", "register"]

LAYOUT: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Catalog", ("org", "catalog", "get", "describe", "tree", "search", "checkout")),
    (
        "Collection",
        ("status", "add", "rm", "pull", "push", "edit", "validate", "publish", "activate"),
    ),
    ("Manage", ("create", "delete", "set", "unset")),
    ("Administration", ("adm",)),
    ("Settings", ("login", "logout", "whoami", "config")),
)
"""The root help: each panel's title and its verbs, in the order help lists them."""

PANELS = tuple(panel for panel, _ in LAYOUT)
VERBS = tuple(verb for _, verbs in LAYOUT for verb in verbs)
PANEL_OF = {verb: panel for panel, verbs in LAYOUT for verb in verbs}
"""The help panel of every verb."""


class VerbGroup(TyperGroup):
    """The root group: lists verbs in ``VERBS`` order, so help panels follow ``PANELS``."""

    def list_commands(self, ctx: Any) -> list[str]:
        """Every verb, in ``VERBS`` order; any other after them.

        ``ctx`` is Typer's vendored click context, which Typer does not export.
        """
        rank = {name: index for index, name in enumerate(VERBS)}
        return sorted(super().list_commands(ctx), key=lambda name: rank.get(name, len(rank)))


def register(app: typer.Typer) -> None:
    """Add every verb to ``app`` under its help panel in ``LAYOUT``."""
    get.register(app, PANEL_OF["get"])
    describe.register(app, PANEL_OF["describe"])
    explore.register(app, PANEL_OF["tree"])
    context.register(app, PANEL_OF)
    status.register(app, PANEL_OF["status"])
    stage.register(app, PANEL_OF)
    create.register(app, PANEL_OF["create"])
    delete.register(app, PANEL_OF["delete"])
    change.register(app, PANEL_OF)
    adm.register(app, PANEL_OF["adm"])
    session.register(app, PANEL_OF["login"])
