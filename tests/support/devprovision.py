"""Run ``scripts/dev-provision.py``, the lake preparation of the development stacks and of the
local cluster, with the CLI of this environment."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

__all__ = ["run_dev_provision"]

ROOT = Path(__file__).resolve().parents[2]


def run_dev_provision(config: Path) -> subprocess.CompletedProcess[str]:
    """Run the script on the service configuration ``config``, with the CLI of this environment
    on its PATH, and the home and the CLI directories next to ``config``.
    """
    environment = {
        "PATH": f"{Path(sys.executable).parent}{os.pathsep}{os.environ['PATH']}",
        "HOME": str(config.parent),
        "XDG_CONFIG_HOME": str(config.parent / "config"),
        "XDG_STATE_HOME": str(config.parent / "state"),
    }
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts/dev-provision.py"), "--config", str(config)],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )
