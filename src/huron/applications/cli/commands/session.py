"""``login``, ``logout``, ``whoami`` and ``config``."""

from __future__ import annotations

from typing import Annotated

import typer

from huron.applications.cli.commands.common import api, say, services, show, show_list
from huron.applications.cli.config import CONFIG_KEYS
from huron.applications.cli.output import Column

__all__ = ["register"]

config_app = typer.Typer(help="Show or change the CLI configuration.", no_args_is_help=True)


def register(app: typer.Typer) -> None:
    """Add the session verbs."""
    app.command()(login)
    app.command()(logout)
    app.command()(whoami)
    app.add_typer(config_app, name="config")


def login(
    ctx: typer.Context,
    device: Annotated[bool, typer.Option("--device", help="Use the device code flow.")] = False,
    browser: Annotated[
        bool, typer.Option("--browser", help="Use a browser on this machine.")
    ] = False,
) -> None:
    """Log in with the institutional identity provider."""
    found = services(ctx)
    oidc = found.oidc()
    use_browser = browser or (not device and bool(found.environ.get("DISPLAY")))
    if use_browser:
        tokens = oidc.loopback_flow(found.open_browser)
    else:

        def announce(url: str, code: str) -> None:
            found.err.print(f"Open {url} and enter the code {code}", markup=False, highlight=False)

        tokens = oidc.device_flow(announce, found.sleep)
    stored = found.session().login(tokens)
    say(ctx, f"logged in as {stored.subject}")


def logout(ctx: typer.Context) -> None:
    """Forget the stored tokens."""
    removed = services(ctx).session().logout()
    say(ctx, "logged out" if removed else "not logged in")


def whoami(ctx: typer.Context) -> None:
    """Who you are, your LDAP groups and the roles they hold."""
    me = api(ctx).get("/api/v1/auth/whoami")
    if services(ctx).output.value != "table":
        show(ctx, me)
        return
    show(ctx, {"subject": me["subject"], "name": me["name"], "groups": ", ".join(me["groups"])})
    show_list(
        ctx,
        me["roles"],
        [
            Column("SCOPE", lambda r: r["scope"]),
            Column("SCOPE ID", lambda r: r["scope_id"]),
            Column("ROLE", lambda r: r["role"]),
        ],
    )


@config_app.command("show")
def config_show(ctx: typer.Context) -> None:
    """Print the configuration."""
    found = services(ctx)
    show(ctx, {"path": str(found.config_path), **found.config.as_dict()})


@config_app.command("set")
def config_set(
    ctx: typer.Context,
    key: Annotated[str, typer.Argument(help=", ".join(CONFIG_KEYS))],
    value: str,
) -> None:
    """Set one configuration value."""
    found = services(ctx)
    found.save_config(found.config.set(key, value))
    say(ctx, f"{key} = {value}")
