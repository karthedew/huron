"""Persistent restart admission binds real storage identity to authenticated exclusion."""

import json
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

import httpx
import pytest

from huron.applications.lakectl import controller as controller_module
from huron.applications.lakectl.controller import managed_controller
from huron.applications.lakectl.engine import Container
from huron.applications.lakectl.settings import ControllerSettings
from huron.core.integrity.models import ControllerState, FenceEvidence
from tests.unit.test_controller_settings import controller_settings as controller_settings
from tests.unit.test_controller_settings import root_metadata as root_metadata
from tests.unit.test_lakectl_wiring import IDENTITY, EmptyDatabaseBoundary

pytestmark = pytest.mark.unit
IMAGE = "sha256:" + "a" * 64
WRITER = "b" * 64


class EngineBoundary:
    """Model engine observations; actual process termination has separate Linux coverage."""

    def __init__(self, volume: Path, state_path: Path) -> None:
        self.volume = volume
        self.state_path = state_path
        self.containers: tuple[Container, ...] = ()
        self.survives = False
        self.observed_durable_fence = False

    def image_identity(self, reference: str) -> str:
        """Return the immutable image resolved by the engine boundary."""
        return IMAGE

    def volume_path(self, name: str) -> Path:
        """Return the engine's current backing directory."""
        return self.volume

    def inventory(self) -> tuple[Container, ...]:
        """Return the full external engine observation."""
        return self.containers

    def start(self, specification: dict[str, object]) -> str:
        """Return a newly admitted identity from the engine boundary."""
        return WRITER

    def terminate(self, identifier: str) -> None:
        """Observe persisted admission state at the destructive I/O boundary."""
        state = ControllerState.model_validate_json(self.state_path.read_bytes())
        self.observed_durable_fence = state.run_id is not None
        if not self.survives:
            self.containers = tuple(
                item for item in self.containers if item.identifier != identifier
            )


@pytest.fixture
def database_boundary(monkeypatch: pytest.MonkeyPatch) -> EmptyDatabaseBoundary:
    """Substitute the maintenance database's SQL boundary before any controller is built."""
    database = EmptyDatabaseBoundary()
    monkeypatch.setattr(controller_module.asyncpg, "create_pool", lambda url: database)
    return database


@pytest.fixture
def engine_boundary(
    controller_settings: ControllerSettings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> EngineBoundary:
    """Supply external engine observations around actual persisted controller state."""
    volume = tmp_path / "volume"
    volume.mkdir()
    engine = EngineBoundary(volume, controller_settings.state_path)
    monkeypatch.setattr(controller_module, "LocalEngine", lambda socket: engine)
    return engine


def writer(engine: EngineBoundary, **changes: object) -> Container:
    """Construct an engine response for one application volume holder."""
    document = {
        "Id": WRITER,
        "Image": IMAGE,
        "Mounts": [
            {
                "Type": "volume",
                "Name": "raw",
                "Source": str(engine.volume),
                "Destination": "/data",
                "RW": True,
            }
        ],
        "HostConfig": {
            "Privileged": False,
            "PidMode": "",
            "IpcMode": "private",
            "NetworkMode": "isolated",
        },
    }
    document.update(changes)
    return Container.model_validate(document)


def raising(error: BaseException) -> Callable[..., object]:
    """Build an engine or SQL observation that fails with the given fault."""

    def fail(*arguments: object) -> object:
        raise error

    return fail


def generation_on_disk(settings: ControllerSettings) -> int:
    """Read the durable epoch exactly as a restarted controller would."""
    return ControllerState.model_validate_json(settings.state_path.read_bytes()).generation


async def test_controller_persists_exclusion_before_termination_and_refuses_restart(
    controller_settings: ControllerSettings,
    engine_boundary: EngineBoundary,
    database_boundary: EmptyDatabaseBoundary,
) -> None:
    """Authenticated cutover stops all observed writers only after durable admission closes."""
    controller = managed_controller(controller_settings)
    assert controller.restart(1003) == WRITER
    root = controller.describe(1002)
    assert root.path == engine_boundary.volume
    assert root.root_id == controller_settings.root_id
    engine_boundary.containers = (writer(engine_boundary),)
    evidence = await controller.establish(1002, UUID(int=3))
    assert engine_boundary.observed_durable_fence
    assert evidence.terminated_writers == (WRITER,)
    assert evidence.database == database_boundary.identity
    assert generation_on_disk(controller_settings) == evidence.generation
    controller.check(1002, evidence)
    again = await controller.establish(1002, UUID(int=3))
    assert again.generation == evidence.generation + 1 == generation_on_disk(controller_settings)
    assert again.terminated_writers == ()
    with pytest.raises(ValueError, match="generation changed"):
        controller.check(1002, evidence)
    with pytest.raises(ValueError, match="restart is excluded"):
        controller.restart(1003)
    with pytest.raises(ValueError, match="another maintenance operator"):
        controller.check(0, again)
    changed = await controller.establish(1002, UUID(int=4))
    assert changed.generation == again.generation + 1
    with pytest.raises(ValueError, match="generation changed"):
        controller.check(1002, again)
    restarted = managed_controller(controller_settings)
    with pytest.raises(ValueError, match="generation changed"):
        restarted.check(1002, changed)
    with pytest.raises(ValueError, match="restart is excluded"):
        restarted.restart(1003)


def test_controller_requires_separate_kernel_peer_grants(
    controller_settings: ControllerSettings,
    engine_boundary: EngineBoundary,
) -> None:
    """Restart-only users cannot obtain maintenance grants and maintenance users cannot start."""
    controller = managed_controller(controller_settings)
    with pytest.raises(PermissionError, match="maintenance grant"):
        controller.authenticate(1003)
    with pytest.raises(PermissionError, match="restart grant"):
        controller.restart(1002)


async def test_surviving_or_reappearing_writer_invalidates_exclusion(
    controller_settings: ControllerSettings,
    engine_boundary: EngineBoundary,
    database_boundary: EmptyDatabaseBoundary,
) -> None:
    """A persisted exclusion flag cannot admit a daemon that retains or recreates a writer."""
    controller = managed_controller(controller_settings)
    engine_boundary.containers = (writer(engine_boundary),)
    engine_boundary.survives = True
    with pytest.raises(ValueError, match="foreign writer"):
        await controller.establish(1002, UUID(int=3))
    with pytest.raises(ValueError, match="restart is excluded"):
        controller.restart(1003)
    engine_boundary.survives = False
    evidence = await controller.establish(1002, UUID(int=3))
    engine_boundary.containers = (writer(engine_boundary),)
    with pytest.raises(ValueError, match="foreign writer"):
        controller.check(1002, evidence)


@pytest.mark.parametrize(
    "case", ["image", "source", "ancestor", "directory", "file", "alias", "socket", "privileged", "host", "unrelated"]
)
async def test_complete_inventory_refuses_unmanaged_storage_and_host_authority(
    controller_settings: ControllerSettings,
    engine_boundary: EngineBoundary,
    database_boundary: EmptyDatabaseBoundary,
    case: str,
) -> None:
    """Foreign storage and host privileges block certification independently of labels."""
    item = writer(engine_boundary).model_dump(by_alias=True)
    if case == "image":
        item["Image"] = "sha256:" + "c" * 64
    elif case == "source":
        item["Mounts"][0]["Source"] = "/different"
    elif case in {"ancestor", "directory", "file", "alias", "socket", "unrelated"}:
        source = {
            "ancestor": str(engine_boundary.volume.parent),
            "directory": str(engine_boundary.volume / "organization"),
            "file": str(engine_boundary.volume / "organization" / "payload"),
            "alias": str(engine_boundary.volume / "organization" / ".."),
            "socket": str(controller_settings.engine_socket),
            "unrelated": "/unrelated",
        }[case]
        item["Mounts"] = [
            {"Type": "bind", "Source": source, "Destination": "/mounted", "RW": False}
        ]
    elif case == "privileged":
        item["HostConfig"]["Privileged"] = True
    else:
        item["HostConfig"]["PidMode"] = "host"
    engine_boundary.containers = (Container.model_validate(item),)
    controller = managed_controller(controller_settings)
    if case == "unrelated":
        assert (await controller.establish(1002, UUID(int=3))).terminated_writers == ()
    else:
        with pytest.raises(ValueError):
            await controller.establish(1002, UUID(int=3))


def test_storage_replacement_and_deployment_change_invalidate_controller_state(
    controller_settings: ControllerSettings,
    engine_boundary: EngineBoundary,
    tmp_path: Path,
) -> None:
    """State from another root inode or deployment identity cannot be reused for certification."""
    controller = managed_controller(controller_settings)
    replacement = tmp_path / "replacement"
    replacement.mkdir()
    engine_boundary.volume = replacement
    with pytest.raises(ValueError, match="identity changed"):
        controller.describe(1002)
    with pytest.raises(ValueError, match="identity changed"):
        managed_controller(controller_settings)


def test_storage_replacement_during_first_start_cannot_bind_another_inspection_root(
    controller_settings: ControllerSettings,
    engine_boundary: EngineBoundary,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The initial state binds the actual inspection adapter's root before fresh engine comparison."""
    replacement = tmp_path / "replacement"
    replacement.mkdir()
    original = engine_boundary.volume

    def moving_volume(name: str) -> Path:
        path = engine_boundary.volume
        engine_boundary.volume = replacement
        return path

    monkeypatch.setattr(engine_boundary, "volume_path", moving_volume)
    with pytest.raises(ValueError, match="identity changed"):
        managed_controller(controller_settings)
    assert original.stat().st_ino != replacement.stat().st_ino
    assert not controller_settings.state_path.exists()


def test_public_state_directory_is_refused(
    controller_settings: ControllerSettings,
    engine_boundary: EngineBoundary,
) -> None:
    """A writable or accessible state directory cannot own persistent restart authority."""
    controller_settings.state_path.parent.mkdir(mode=0o755)
    with pytest.raises(ValueError, match="private root-owned directory"):
        managed_controller(controller_settings)


@pytest.mark.parametrize("operation", ["check", "describe", "establish", "restart"])
async def test_live_deployment_change_invalidates_admission_without_controller_restart(
    controller_settings: ControllerSettings,
    engine_boundary: EngineBoundary,
    database_boundary: EmptyDatabaseBoundary,
    operation: str,
) -> None:
    """A changed trusted Compose file invalidates cached configuration and prior evidence."""
    controller = managed_controller(controller_settings)
    evidence = None if operation == "restart" else await controller.establish(1002, UUID(int=3))
    document = json.loads(controller_settings.compose_path.read_bytes())
    document["services"]["api"]["command"] = ["changed-command"]
    controller_settings.compose_path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="identity changed"):
        if operation == "check":
            controller.check(1002, evidence)
        elif operation == "describe":
            controller.describe(1002)
        elif operation == "establish":
            await controller.establish(1002, UUID(int=3))
        else:
            controller.restart(1003)


@pytest.mark.parametrize("alias", ["relative", "symlink"])
async def test_mount_inventory_refuses_ambiguous_backing_path_identity(
    controller_settings: ControllerSettings,
    engine_boundary: EngineBoundary,
    database_boundary: EmptyDatabaseBoundary,
    tmp_path: Path,
    alias: str,
) -> None:
    """Relative and replaceable symlink sources cannot stand in for actual mounted backing paths."""
    link = tmp_path / "alias"
    link.symlink_to(engine_boundary.volume, target_is_directory=True)
    source = "relative/path" if alias == "relative" else str(link)
    item = writer(engine_boundary).model_dump(by_alias=True)
    item["Mounts"] = [
        {"Type": "bind", "Source": source, "Destination": "/foreign", "RW": True}
    ]
    engine_boundary.containers = (Container.model_validate(item),)
    with pytest.raises(ValueError, match="trustworthy normalized"):
        await managed_controller(controller_settings).establish(1002, UUID(int=3))


async def test_establish_mints_before_terminating_and_a_survivor_ends_the_new_epoch(
    controller_settings: ControllerSettings,
    engine_boundary: EngineBoundary,
    database_boundary: EmptyDatabaseBoundary,
) -> None:
    """A minted epoch a survivor invalidates still ends once, then mints again on retry."""
    controller = managed_controller(controller_settings)
    assert generation_on_disk(controller_settings) == 1
    engine_boundary.containers = (writer(engine_boundary),)
    engine_boundary.survives = True
    with pytest.raises(ValueError, match="foreign writer"):
        await controller.establish(1002, UUID(int=3))
    assert generation_on_disk(controller_settings) == 3
    with pytest.raises(ValueError, match="restart is excluded"):
        controller.restart(1003)
    engine_boundary.survives = False
    evidence = await controller.establish(1002, UUID(int=3))
    assert evidence.generation == 4


@pytest.mark.parametrize("operation", ["describe", "restart"])
def test_engine_failure_during_describe_or_restart_ends_the_epoch(
    controller_settings: ControllerSettings,
    engine_boundary: EngineBoundary,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    """An unreachable engine during a live observation ends the epoch, not just the call."""
    controller = managed_controller(controller_settings)
    monkeypatch.setattr(
        engine_boundary, "volume_path", raising(httpx.ConnectError("engine unavailable"))
    )
    with pytest.raises(httpx.ConnectError):
        if operation == "describe":
            controller.describe(1002)
        else:
            controller.restart(1003)
    assert generation_on_disk(controller_settings) == 2


def test_check_and_abandon_refuse_before_any_epoch_is_established(
    controller_settings: ControllerSettings,
    engine_boundary: EngineBoundary,
) -> None:
    """A presented fence is refused, never mistaken live, before any establish ever ran."""
    controller = managed_controller(controller_settings)
    fence = FenceEvidence(
        controller_id=UUID(int=2),
        root_id=UUID(int=1),
        generation=1,
        operator="local:1002",
        terminated_writers=(),
        old_roles=("old_app",),
        new_role="new_app",
        database=IDENTITY,
    )
    with pytest.raises(ValueError, match="generation changed"):
        controller.check(1002, fence)
    controller.abandon(1002, fence)
    assert generation_on_disk(controller_settings) == 1
    with pytest.raises(PermissionError, match="maintenance grant"):
        controller.abandon(1003, fence)
