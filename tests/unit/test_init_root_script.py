"""``scripts/init-root.sh`` prepares a share root."""

import grp
import json
import os
import stat
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "init-root.sh"


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, check=False)


def test_prepares_the_root_and_writes_the_marker(tmp_path: Path) -> None:
    group = grp.getgrgid(os.getgid()).gr_name
    done = run(str(tmp_path), group, "http://huron", "id-1")
    assert done.returncode == 0, done.stderr
    assert stat.S_IMODE(os.lstat(tmp_path).st_mode) == 0o2771
    marker = json.loads((tmp_path / ".huron").read_text())
    assert marker == {"api_url": "http://huron", "huron": 1, "instance_id": "id-1"}


def test_unknown_groups_and_bad_arguments(tmp_path: Path) -> None:
    done = run(str(tmp_path), "no-such-group-xyz", "http://huron", "id-1")
    assert done.returncode == 0 and "unknown" in done.stderr
    assert run(str(tmp_path / "missing"), "g", "u", "i").returncode == 1
    assert run("only-one").returncode == 2
