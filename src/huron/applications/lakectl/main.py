"""Operator entry points for managed restart and fenced legacy verification."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from uuid import UUID

import asyncpg
import httpx

from huron.core.integrity.models import CertificationIndeterminateError

from .exclusion import ControllerClient
from .server import serve
from .settings import ControllerSettings, MaintenanceSettings
from .wiring import prepare


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
    cutover.add_argument("--prepare", action="store_true", required=True)
    cutover.add_argument("--config", type=Path, required=True)
    cutover.add_argument("--run-id", type=UUID, required=True)
    arguments = parser.parse_args()
    try:
        if arguments.command == "controller":
            serve(ControllerSettings.load(arguments.config))
        elif arguments.command == "restart":
            print(asyncio.run(ControllerClient(arguments.socket).restart()))
        else:
            result = asyncio.run(
                prepare(MaintenanceSettings.load(arguments.config), arguments.run_id)
            )
            print(result.canonical.decode())
    except CertificationIndeterminateError:
        print(
            "lakectl certificate acknowledgement is indeterminate; validate the receipt before use",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    except (ValueError, OSError, ExceptionGroup, asyncpg.PostgresError, httpx.HTTPError):
        print(
            "lakectl refused the operation; application activation was not performed",
            file=sys.stderr,
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
