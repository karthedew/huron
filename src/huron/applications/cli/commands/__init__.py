"""Command groups; ``register`` adds every one of them to the root app."""

from __future__ import annotations

import typer

from huron.applications.cli.commands import (
    acl,
    catalogs,
    check,
    collections,
    meta,
    namespaces,
    organizations,
    platform,
    schemas,
    session,
    stage,
)

__all__ = ["register"]


def register(app: typer.Typer) -> None:
    """Add every command group and top-level verb to ``app``."""
    modules = (
        session,
        organizations,
        catalogs,
        schemas,
        namespaces,
        collections,
        stage,
        meta,
        platform,
        check,
        acl,
    )
    for module in modules:
        module.register(app)
