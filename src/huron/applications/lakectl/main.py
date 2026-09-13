"""Operator entry points for managed restart and fenced legacy verification."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from uuid import UUID

import asyncpg
import httpx

from .exclusion import ControllerClient
from .server import serve
from .settings import ControllerSettings, MaintenanceSettings
from .wiring import prepare, validate


def main() -> None:
    """Parse operator commands and print only resulting identities or evidence.

    Raises:
        SystemExit: If maintenance is refused, without exposing connection material.
    """
    parser = argparse.ArgumentParser(prog="lakectl")
    commands = parser.add_subparsers(dest="command", required=True)
    controller = commands.add_parser("controller")
    controller.add_argument("--config", type=Path, required=True)
    restart = commands.add_parser("restart")
    restart.add_argument("--socket", type=Path, required=True)
    protocol = commands.add_parser("protocol")
    operations = protocol.add_subparsers(dest="operation", required=True)
    cutover = operations.add_parser("cutover")
    action = cutover.add_mutually_exclusive_group(required=True)
    action.add_argument("--prepare", action="store_true")
    action.add_argument("--validate", action="store_true")
    cutover.add_argument("--config", type=Path, required=True)
    cutover.add_argument("--run-id", type=UUID)
    cutover.add_argument("--sequence", type=_sequence)
    arguments = parser.parse_args()
    if arguments.command == "protocol" and (
        arguments.prepare != (arguments.run_id is not None)
        or arguments.validate != (arguments.sequence is not None)
    ):
        cutover.error("--prepare takes --run-id and --validate takes --sequence")
    try:
        if arguments.command == "controller":
            serve(ControllerSettings.load(arguments.config))
        elif arguments.command == "restart":
            print(asyncio.run(ControllerClient(arguments.socket).restart()))
        elif arguments.prepare:
            settings = MaintenanceSettings.load(arguments.config)
            print(asyncio.run(prepare(settings, arguments.run_id)).canonical.decode())
        else:
            settings = MaintenanceSettings.load(arguments.config)
            print(asyncio.run(validate(settings, arguments.sequence)).canonical.decode())
    except (ValueError, OSError, ExceptionGroup, asyncpg.PostgresError, httpx.HTTPError):
        print(
            "lakectl refused the operation; application activation was not performed",
            file=sys.stderr,
        )
        raise SystemExit(1) from None


def _sequence(text: str) -> int:
    """Parse and bound an operator-supplied stored-record number.

    Args:
        text: Raw ``--sequence`` argument text.

    Returns:
        The parsed sequence number.

    Raises:
        argparse.ArgumentTypeError: If the value is outside the storable record range.
    """
    value = int(text)
    if not 1 <= value <= 999_999:
        raise argparse.ArgumentTypeError("sequence must be between 1 and 999999")
    return value


if __name__ == "__main__":
    main()
