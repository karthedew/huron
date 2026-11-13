"""Prepare the lake of a development stack: `lake-init` of docker-compose.app.yml runs it before
the API starts.

    python scripts/dev-provision.py [--config <service configuration file>]

The script runs `huron adm provision-orgs --config <file>`, which sends no request to the API. The
CLI's provisioning code makes `.tus-uploads` and writes the marker at the lake path, and makes and
marks each declared organization directory with its object area. The script makes no directory
and writes no file itself.

The lake path is `lake_path` of the file. The service user and group are the user and group that
run the script. The marker names the API at HURON_API_URL, or http://127.0.0.1:8080 when that
variable is not set.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

import yaml

DEFAULT_API_URL = "http://127.0.0.1:8080"


def main(argv: list[str]) -> int:
    """Provision the lake path and the declared organizations; return the exit code of the CLI."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=Path("huron.dev.yaml"))
    arguments = parser.parse_args(argv)
    settings = yaml.safe_load(arguments.config.read_text(encoding="utf-8")) or {}
    lake_path = settings.get("lake_path") if isinstance(settings, dict) else None
    if not isinstance(lake_path, str):
        print(f"dev-provision: {arguments.config} sets no lake_path", file=sys.stderr)
        return 2
    environment = {
        **os.environ,
        "HURON_MOUNT_PREFIX": lake_path,
        "HURON_API_URL": os.environ.get("HURON_API_URL", DEFAULT_API_URL),
    }
    command = [
        "huron",
        "adm",
        "provision-orgs",
        "--config",
        str(arguments.config),
        "--uid",
        str(os.getuid()),
        "--gid",
        str(os.getgid()),
    ]
    return subprocess.run(command, env=environment, check=False).returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
