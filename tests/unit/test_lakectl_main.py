"""Operator commands expose receipts and safe failures without accepting actor assertions."""

import asyncio
import runpy
import sys
from pathlib import Path
from uuid import UUID
from types import SimpleNamespace

import asyncpg
import httpx
import pytest

from huron.applications.lakectl import main as cli, wiring
from huron.applications.lakectl.settings import ControllerSettings, MaintenanceSettings
from huron.core.integrity.models import ProtocolTransition
from tests.unit.test_controller_settings import controller_settings as controller_settings
from tests.unit.test_controller_settings import root_metadata as root_metadata
from tests.unit.test_lakectl_wiring import ControllerBoundary, EmptyDatabaseBoundary
from tests.unit.test_managed_controller import raising

pytestmark = pytest.mark.unit


def test_controller_command_loads_administrator_configuration(
    controller_settings: ControllerSettings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The controller command passes only validated private settings to its service entry point."""
    path = tmp_path / "controller.json"
    path.write_text(controller_settings.model_dump_json())
    path.chmod(0o600)
    served = []
    monkeypatch.setattr(cli, "serve", served.append)
    monkeypatch.setattr(sys, "argv", ["lakectl", "controller", "--config", str(path)])
    cli.main()
    assert served == [controller_settings]


def test_restart_command_prints_only_the_controller_result(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The restart command forwards the socket endpoint and prints its admitted identity."""

    class ControllerBoundary:
        def __init__(self, path: Path) -> None:
            assert path == Path("controller.sock")

        async def restart(self) -> str:
            return "a" * 64

    monkeypatch.setattr(cli, "ControllerClient", ControllerBoundary)
    monkeypatch.setattr(sys, "argv", ["lakectl", "restart", "--socket", "controller.sock"])
    cli.main()
    assert capsys.readouterr().out == "a" * 64 + "\n"


def test_cutover_command_prints_the_exact_canonical_transition(
    tmp_path: Path,
    root_metadata: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A preparatory cutover reports its immutable receipt without activation or credentials."""
    path = tmp_path / "maintenance.json"
    path.write_text('{"controller_socket":"controller.sock","database_url":"private"}')
    path.chmod(0o600)
    controller = ControllerBoundary(tmp_path)
    database = EmptyDatabaseBoundary()
    monkeypatch.setattr(wiring, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(wiring, "ControllerClient", lambda socket: controller)
    monkeypatch.setattr(wiring.asyncpg, "create_pool", lambda url: database)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "lakectl",
            "protocol",
            "cutover",
            "--prepare",
            "--config",
            str(path),
            "--run-id",
            str(UUID(int=2)),
        ],
    )
    cli.main()
    stored = (tmp_path / "protocol/000001.json").read_bytes()
    receipt = ProtocolTransition.decode(stored)
    assert receipt.run_id == UUID(int=2)
    assert receipt.root_id == UUID(int=1)
    assert database.closed
    assert capsys.readouterr().out == stored.decode() + "\n"


def test_validate_command_prints_the_admitted_record_and_refuses_an_absent_sequence(
    tmp_path: Path,
    root_metadata: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A validated stored record prints the same bytes a lost prepare reply would have."""
    path = tmp_path / "maintenance.json"
    path.write_text('{"controller_socket":"controller.sock","database_url":"private"}')
    path.chmod(0o600)
    controller = ControllerBoundary(tmp_path)
    database = EmptyDatabaseBoundary()
    monkeypatch.setattr(wiring, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(wiring, "ControllerClient", lambda socket: controller)
    monkeypatch.setattr(wiring.asyncpg, "create_pool", lambda url: database)
    asyncio.run(wiring.prepare(MaintenanceSettings.load(path), UUID(int=2)))
    database.closed = False
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "lakectl",
            "protocol",
            "cutover",
            "--validate",
            "--config",
            str(path),
            "--sequence",
            "1",
        ],
    )
    cli.main()
    stored = (tmp_path / "protocol/000001.json").read_bytes()
    assert capsys.readouterr().out == stored.decode() + "\n"
    assert database.closed
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "lakectl",
            "protocol",
            "cutover",
            "--validate",
            "--config",
            str(path),
            "--sequence",
            "2",
        ],
    )
    with pytest.raises(SystemExit) as stopped:
        cli.main()
    assert stopped.value.code == 1
    output = capsys.readouterr()
    assert not output.out
    assert "refused the operation" in output.err
    assert "000002" not in output.err


@pytest.mark.parametrize(
    "case",
    [
        ["--prepare"],
        ["--validate"],
        ["--prepare", "--run-id", str(UUID(int=1)), "--sequence", "1"],
        ["--validate", "--sequence", "1", "--run-id", str(UUID(int=1))],
        ["--prepare", "--validate", "--run-id", str(UUID(int=1)), "--sequence", "1"],
        [],
        ["--validate", "--sequence", "0"],
        ["--validate", "--sequence", "1000000"],
    ],
)
def test_cutover_usage_errors_exit_two(
    case: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Every unsupported cutover argument combination is refused before any composition runs."""
    monkeypatch.setattr(cli, "prepare", raising(AssertionError("prepare ran")))
    monkeypatch.setattr(cli, "validate", raising(AssertionError("validate ran")))
    monkeypatch.setattr(
        sys,
        "argv",
        ["lakectl", "protocol", "cutover", "--config", "maintenance.json", *case],
    )
    with pytest.raises(SystemExit) as stopped:
        cli.main()
    assert stopped.value.code == 2
    assert "usage:" in capsys.readouterr().err


@pytest.mark.parametrize(
    "failure",
    [
        ValueError("credential-secret"),
        OSError("credential-secret"),
        asyncpg.PostgresError("credential-secret"),
        httpx.ConnectError("credential-secret"),
        ExceptionGroup("credential-secret", [ValueError("credential-secret")]),
    ],
)
def test_command_failures_do_not_echo_connection_material(
    controller_settings: ControllerSettings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure: Exception,
) -> None:
    """Refusals across database, controller and concurrent workflow boundaries expose no secrets."""
    path = tmp_path / "controller.json"
    path.write_text(controller_settings.model_dump_json())
    path.chmod(0o600)

    def fail(settings: ControllerSettings) -> None:
        raise failure

    monkeypatch.setattr(cli, "serve", fail)
    monkeypatch.setattr(sys, "argv", ["lakectl", "controller", "--config", str(path)])
    with pytest.raises(SystemExit) as result:
        cli.main()
    assert result.value.code == 1
    output = capsys.readouterr()
    assert not output.out
    assert "credential-secret" not in output.err
    assert "refused the operation" in output.err


def test_module_entry_point_exposes_the_same_command_parser(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Direct module execution enters the supported lakectl parser."""
    monkeypatch.setattr(sys, "argv", ["lakectl", "--help"])
    monkeypatch.delitem(sys.modules, "huron.applications.lakectl.main")
    with pytest.raises(SystemExit) as result:
        runpy.run_module("huron.applications.lakectl.main", run_name="__main__")
    assert result.value.code == 0
    assert "controller,restart,protocol" in capsys.readouterr().out
