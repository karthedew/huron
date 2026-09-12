"""Actual historical HTTP writers cannot survive controlled deployment exclusion."""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

_LEGACY_COMMIT = "db5fc84cd7bfe049692ef2abb16fb32570ccf5a2"
_LEGACY_ARCHIVE_SHA256 = "b1ad409fb8c193be2c03fb10aa63b0be4d11722cd0f364b52ba0aaab135de4dd"


def test_actual_legacy_http_request_is_terminated_and_cannot_restart() -> None:
    """A held old HTTP upload survives SQL fencing but is stopped by the real controller."""
    checkout = Path(__file__).resolve().parents[2]
    cache = checkout / ".pytest_cache"
    cache.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="controlled-", dir=cache) as temporary:
        staging = Path(temporary)
        archive = subprocess.check_output(
            [
                "git",
                "archive",
                "--format=tar",
                _LEGACY_COMMIT,
                "src",
                "pyproject.toml",
                "uv.lock",
                "migrations",
                "alembic.ini",
                "Containerfile",
                "README.md",
            ],
            cwd=checkout,
        )
        assert hashlib.sha256(archive).hexdigest() == _LEGACY_ARCHIVE_SHA256
        legacy = staging / "legacy.tar"
        legacy.write_bytes(archive)
        requirements = staging / "requirements.txt"
        subprocess.run(
            [
                "uv",
                "export",
                "--locked",
                "--no-dev",
                "--no-emit-project",
                "--format",
                "requirements-txt",
                "--output-file",
                str(requirements),
            ],
            cwd=checkout,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        invocation = [
            "python3",
            str(checkout / "tests/controlled_deployment.py"),
            "provision",
            str(checkout),
            str(requirements),
            str(legacy),
        ]
        runtime_log = staging / "runtime.log"
        with runtime_log.open("w") as output_file:
            result = subprocess.run(
                _local_linux_invocation(invocation),
                stdout=output_file,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=900,
            )
        output = runtime_log.read_text()
        for secret in ("fixture-password", "replacement-password", "maintenance-password"):
            output = output.replace(secret, "<REDACTED>")
        print(output)
        assert result.returncode == 0
        assert "LEGACY_HTTP_UPLOAD_ADMITTED" in output
        assert "LEGACY_HTTP_WRITE_SURVIVED_SQL_FENCE" in output
        assert "LEGACY_WRITER_TERMINATED_RESTART_EXCLUDED" in output
        assert "LEGACY_REVOKED_IDENTITY_STARTUP_REFUSED" in output
        assert "AUTHENTICATED_WIRED_CUTOVER_RECORDED" in output
        assert "CONTROLLER_FOREIGN_GENERATION_UNREACHABLE_REFUSED" in output
        assert output.count("FOREIGN_DESCENDANT_WRITER_REFUSED") == 2
        assert "CLEANED" in output


def _local_linux_invocation(invocation: list[str]) -> list[str]:
    """Run inside the actual local Linux storage namespace, using the VM on macOS."""
    if sys.platform == "darwin":
        info = json.loads(subprocess.check_output(["podman", "machine", "inspect"]))[0]
        if info["State"] != "running":
            subprocess.run(["podman", "machine", "start"], check=True)
        return ["podman", "machine", "ssh", "sudo " + shlex.join(invocation)]
    assert sys.platform == "linux", "controlled deployment tests require Linux or its Podman VM"
    return invocation if os.geteuid() == 0 else ["sudo", "-n", *invocation]
