"""The root ``huron`` command, its global options and the error boundary."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated

import typer

from huron.applications.cli import commands
from huron.applications.cli.errors import CliError, ExitCode, exit_code_for
from huron.applications.cli.output import OutputFormat
from huron.applications.cli.services import Services
from huron.pkg.errors import HuronError

__all__ = ["app", "run"]

app = typer.Typer(
    name="huron",
    cls=commands.VerbGroup,
    no_args_is_help=True,
    add_completion=False,
    help="Record raw scientific data in catalogs, organize it and push it to the Huron share.",
    pretty_exceptions_enable=False,
)


@app.callback()
def main_options(
    ctx: typer.Context,
    output: Annotated[
        OutputFormat,
        typer.Option("--output", "-o", help="The output format: `table`, `json` or `yaml`."),
    ] = OutputFormat.TABLE,
    api_url: Annotated[
        str | None, typer.Option(help="Use this API URL instead of the configured one.")
    ] = None,
    catalog: Annotated[
        str | None, typer.Option(help="Resolve identifiers against this catalog.")
    ] = None,
) -> None:
    """Options for every command."""
    services: Services = ctx.obj
    services.output = output
    services.catalog_override = catalog
    if api_url:
        services.config = services.config.set("api_url", api_url)


commands.register(app)


def run(services: Services, argv: Sequence[str]) -> int:
    """Run the CLI with ``argv``; returns the exit code and never raises for user errors."""
    try:
        result = app(args=list(argv), obj=services, standalone_mode=False, prog_name="huron")
    except Exception as error:
        return _failure(services, error)
    return int(result) if isinstance(result, int) else int(ExitCode.OK)


def _report(services: Services, error: CliError) -> None:
    code = f" [{error.code}]" if error.code else ""
    services.err.print(f"error: {error.message}{code}", markup=False, highlight=False)
    if error.problem and error.problem.get("context", {}).get("problems"):
        for problem in error.problem["context"]["problems"][:20]:
            services.err.print(
                f"  {problem.get('path')}: {problem.get('message')}", markup=False, highlight=False
            )
    if error.hint:
        services.err.print(f"hint: {error.hint}", markup=False, highlight=False)


def _failure(services: Services, error: Exception) -> int:
    if type(error).__name__ == "NoArgsIsHelpError":
        # A verb typed without its noun: Typer printed the help already and the error has no
        # message. Typer does not export the class, so match it by name as its rich_utils does.
        return int(ExitCode.USAGE)
    failure = _as_cli_error(error)
    if failure is not None:
        _report(services, failure)
        return int(failure.exit_code)
    if services.environ.get("HURON_DEBUG") == "1":
        raise error
    services.err.print(
        f"error: unexpected failure: {error!r}\nhint: to see the traceback, set `HURON_DEBUG=1`",
        markup=False,
    )
    return int(ExitCode.FAILED)


def _as_cli_error(error: Exception) -> CliError | None:
    if isinstance(error, CliError):
        return error
    if isinstance(error, HuronError):
        exit_code = exit_code_for(error.code, error.status)
        return CliError(error.message, exit_code, code=error.code, problem=error.problem())
    if isinstance(error, typer.Abort):
        return CliError("cancelled", ExitCode.INTERRUPTED)
    if isinstance(error, typer.TyperException):
        formatter = getattr(error, "format_message", None)
        return CliError(formatter() if callable(formatter) else str(error), ExitCode.USAGE)
    return None
