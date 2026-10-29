"""``huron platform``: checks of this machine's view of the share."""

from __future__ import annotations

import typer

from huron.applications.cli.commands.common import say, services
from huron.applications.cli.mount import Mount

__all__ = ["register"]

platform_app = typer.Typer(help="Platform checks.", no_args_is_help=True)


def register(app: typer.Typer) -> None:
    """Add ``huron platform``."""
    app.add_typer(platform_app, name="platform")


@platform_app.command("verify-root")
def verify_root(ctx: typer.Context) -> None:
    """Check the share is mounted, marked, and belongs to the configured service."""
    mount = Mount(services(ctx))
    mount.require()
    assert mount.marker is not None
    say(ctx, f"{mount.prefix}: Huron share of {mount.marker.api_url} ({mount.marker.instance_id})")
