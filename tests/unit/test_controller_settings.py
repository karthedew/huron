"""Private operator configuration admits only the fixed managed application contract."""

import json
import os
from pathlib import Path
from uuid import UUID

import pytest

from huron.applications.lakectl.settings import (
    ControllerSettings,
    MaintenanceSettings,
    private_document,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def root_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Model root UID at filesystem boundaries; real Linux authority has integration coverage."""
    original_lstat = Path.lstat
    original_stat = Path.stat
    original_fstat = os.fstat

    def root_lstat(path: Path) -> os.stat_result:
        values = list(original_lstat(path))
        values[4] = 0
        if path in tmp_path.parents:
            values[0] &= ~0o022
        return os.stat_result(values)

    def root_fstat(descriptor: int) -> os.stat_result:
        values = list(original_fstat(descriptor))
        values[4] = 0
        return os.stat_result(values)

    def root_stat(path: Path, *, follow_symlinks: bool = True) -> os.stat_result:
        values = list(original_stat(path, follow_symlinks=follow_symlinks))
        values[4] = 0
        if path in tmp_path.parents:
            values[0] &= ~0o022
        return os.stat_result(values)

    monkeypatch.setattr(Path, "lstat", root_lstat)
    monkeypatch.setattr(Path, "stat", root_stat)
    monkeypatch.setattr(os, "fstat", root_fstat)
    monkeypatch.setattr(os, "geteuid", lambda: 0)


def composition() -> dict[str, object]:
    """Provide the resolved fixed deployment accepted by the production controller."""
    return {
        "name": "controlled",
        "services": {
            "api": {
                "image": "sha256:" + "a" * 64,
                "user": "1001",
                "command": ["uvicorn", "huron.applications.api.main:app"],
                "environment": {"HURON_RAW_ROOT": "/data"},
                "volumes": [{"type": "volume", "source": "raw", "target": "/data"}],
                "networks": ["isolated"],
            }
        },
    }


@pytest.fixture
def controller_settings(tmp_path: Path, root_metadata: None) -> ControllerSettings:
    """Create actual private configuration files with modeled administrator ownership."""
    compose_path = tmp_path / "compose.json"
    compose_path.write_text(json.dumps(composition()))
    compose_path.chmod(0o600)
    maintenance_path = tmp_path / "maintenance.json"
    maintenance_path.write_text('{"controller_socket":"controller.sock","database_url":"private"}')
    maintenance_path.chmod(0o600)
    return ControllerSettings(
        root_id=UUID(int=1),
        controller_id=UUID(int=2),
        engine_socket=tmp_path / "engine.sock",
        socket_path=tmp_path / "public/controller.sock",
        state_path=tmp_path / "private/state.json",
        compose_path=compose_path,
        maintenance_path=maintenance_path,
        volume_name="raw",
        owner_uid=1001,
        cutover_operators=(0, 1002),
        restart_operators=(1003,),
        old_roles=("old_app",),
        new_role="new_app",
    )


def test_private_settings_load_and_keep_connection_secrets_out_of_representations(
    controller_settings: ControllerSettings, tmp_path: Path
) -> None:
    """Settings load from private files and never expose database credentials through repr."""
    controller_file = tmp_path / "controller.json"
    controller_file.write_text(controller_settings.model_dump_json())
    controller_file.chmod(0o600)
    assert ControllerSettings.load(controller_file) == controller_settings
    maintenance_file = tmp_path / "maintenance.json"
    maintenance_file.write_text(
        json.dumps(
            {
                "controller_socket": str(controller_settings.socket_path),
                "database_url": "postgresql://cutover:private-secret@database/huron",
            }
        )
    )
    maintenance_file.chmod(0o600)
    settings = MaintenanceSettings.load(maintenance_file)
    assert "private-secret" not in repr(settings)
    assert settings.database_url.get_secret_value().endswith("@database/huron")


def test_compose_translation_fixes_image_authority_mounts_and_process_privileges(
    controller_settings: ControllerSettings,
) -> None:
    """The only admitted start is the configured immutable nonprivileged application."""
    specification = controller_settings.application_specification()
    assert specification["Image"] == "sha256:" + "a" * 64
    assert specification["User"] == "1001"
    assert specification["Env"] == ["HURON_RAW_ROOT=/data"]
    assert specification["HostConfig"] == {
        "NetworkMode": "isolated",
        "RestartPolicy": {"Name": "no"},
        "Mounts": [{"Type": "volume", "Source": "raw", "Target": "/data"}],
        "CapDrop": ["ALL"],
        "SecurityOpt": ["no-new-privileges"],
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("privileged", True),
        ("user", "0"),
        ("image", "app:latest"),
        ("image", "sha256:short"),
        ("volumes", []),
        ("networks", ["one", "two"]),
    ],
)
def test_unsafe_compose_configuration_is_refused(
    controller_settings: ControllerSettings, field: str, value: object
) -> None:
    """Caller-expandable privileges, images and storage contracts cannot become restart specs."""
    document = json.loads(controller_settings.compose_path.read_bytes())
    document["services"]["api"][field] = value
    controller_settings.compose_path.write_text(json.dumps(document))
    with pytest.raises(ValueError):
        controller_settings.application_specification()


@pytest.mark.parametrize("case", ["public", "ancestor", "oversized", "fifo", "symlink"])
def test_private_document_rejects_unsafe_files(
    controller_settings: ControllerSettings, case: str
) -> None:
    """Private configuration is bounded, regular, unfollowed and protected through its ancestry."""
    path = controller_settings.compose_path
    if case == "public":
        path.chmod(0o644)
    elif case == "ancestor":
        path.parent.chmod(0o777)
    elif case == "oversized":
        path.write_bytes(b"x" * 1048577)
    else:
        path.unlink()
        if case == "fifo":
            os.mkfifo(path, 0o600)
        else:
            path.symlink_to(path.parent / "missing")
    try:
        with pytest.raises((ValueError, OSError)):
            private_document(path)
    finally:
        path.parent.chmod(0o700)
        if case in {"fifo", "symlink"}:
            path.unlink()
