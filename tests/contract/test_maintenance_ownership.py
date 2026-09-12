"""Kernel ownership excludes independent processes and survives interrupted owners safely."""

import os
import selectors
import subprocess
import sys
from pathlib import Path

import pytest

from huron.pkg.rawstore.maintenance import MaintenanceStore

pytestmark = pytest.mark.contract

OWNER = """
import sys
from pathlib import Path
from huron.pkg.rawstore.maintenance import MaintenanceStore
root = Path(sys.argv[1])
store = MaintenanceStore(root, root.stat().st_uid)
with store.claim():
    store.write_evidence('history.json', b'immutable history')
    print('owned', flush=True)
    sys.stdin.readline()
"""
CONTENDER = """
import sys
from pathlib import Path
from huron.pkg.rawstore.maintenance import MaintenanceStore
root = Path(sys.argv[1])
try:
    with MaintenanceStore(root, root.stat().st_uid).claim():
        print('admitted')
except BlockingIOError:
    print('refused')
"""


@pytest.mark.parametrize("interrupt", [False, True])
def test_independent_processes_refuse_live_owner_and_recover_after_exit(
    tmp_path: Path, interrupt: bool
) -> None:
    """A competing process cannot share ownership; exit permits retry without deleting history."""
    owner = subprocess.Popen([sys.executable, "-c", OWNER, str(tmp_path)],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
    try:
        with selectors.DefaultSelector() as ready:
            ready.register(owner.stdout, selectors.EVENT_READ)
            assert ready.select(timeout=10), "owner did not publish readiness"
        assert owner.stdout.readline().strip() == "owned"
        contender = subprocess.run([sys.executable, "-c", CONTENDER, str(tmp_path)],
                                   capture_output=True, text=True, timeout=10, check=True)
        assert contender.stdout.strip() == "refused"
        if interrupt:
            owner.kill()
            owner.wait(timeout=10)
        else:
            owner.communicate("release\n", timeout=10)
            assert owner.returncode == 0
        contender = subprocess.run([sys.executable, "-c", CONTENDER, str(tmp_path)],
                                   capture_output=True, text=True, timeout=10, check=True)
        assert contender.stdout.strip() == "admitted"
        store = MaintenanceStore(tmp_path, os.geteuid())
        with store.claim():
            assert store.read_control("protocol", "history.json") == b"immutable history"
    finally:
        if owner.poll() is None:
            owner.kill()
        owner.communicate(timeout=10)
