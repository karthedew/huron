"""One complete record is admissible only while its fence names the live, intact controller epoch."""

import asyncio
import os
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import UUID

import asyncpg
import httpx
import pytest

from huron.applications.lakectl import controller as controller_module
from huron.applications.lakectl.controller import ManagedComposeController
from huron.applications.lakectl.settings import ControllerSettings
from huron.core.integrity.cutover import CutoverService
from huron.core.integrity.models import (
    FenceEvidence,
    MaintenanceGrant,
    ProtocolInventory,
    ProtocolTransition,
)
from huron.pkg.metastore.maintenance import PostgresRoleExclusion
from huron.pkg.rawstore.maintenance import MaintenanceStore
from tests.unit.test_controller_settings import controller_settings as controller_settings
from tests.unit.test_controller_settings import root_metadata as root_metadata
from tests.unit.test_integrity_cutover import EmptyCatalog
from tests.unit.test_lakectl_wiring import EmptyDatabaseBoundary
from tests.unit.test_managed_controller import EngineBoundary, raising, writer
from tests.unit.test_managed_controller import database_boundary as database_boundary
from tests.unit.test_managed_controller import engine_boundary as engine_boundary
from tests.unit.test_managed_controller import generation_on_disk

pytestmark = pytest.mark.unit


@pytest.fixture
async def prepared(
    controller_settings: ControllerSettings,
    engine_boundary: EngineBoundary,
    database_boundary: EmptyDatabaseBoundary,
) -> tuple[ManagedComposeController, ProtocolTransition]:
    """Write real immutable evidence under a live epoch, substituting only engine and SQL I/O."""
    controller = ManagedComposeController(controller_settings)
    fence = await controller.establish(1002, UUID(int=3))
    inventory = ProtocolInventory(
        root_id=fence.root_id, run_id=UUID(int=3), fence=fence, revisions=(), generations=()
    )
    record = ProtocolTransition.bind(
        inventory, sequence=1, instant=datetime(2026, 1, 1, tzinfo=UTC), code_digest="b" * 64
    )
    store = MaintenanceStore(engine_boundary.volume, controller_settings.owner_uid)
    store.write_evidence(record.report_path, inventory.canonical)
    store.write_evidence("000001.json", record.canonical)
    await controller.validate(1002, record)
    return controller, record


@pytest.mark.parametrize("fault", ["peer", "operator", "run", "absent", "record", "report"])
async def test_mismatched_receipt_is_refused_without_ending_the_epoch(
    prepared: tuple[ManagedComposeController, ProtocolTransition],
    controller_settings: ControllerSettings,
    engine_boundary: EngineBoundary,
    fault: str,
) -> None:
    """A wrong argument is refused as itself, never mistaken for an ended epoch."""
    controller, record = prepared
    peer = 1002
    presented = record
    restore: tuple[Path, bytes] | None = None
    if fault == "peer":
        peer = 1003
        error: type[Exception] = PermissionError
        match = "maintenance grant"
    elif fault == "operator":
        peer = 0
        error, match = ValueError, "another maintenance operator"
    elif fault == "run":
        presented = record.model_copy(update={"run_id": UUID(int=4)})
        error, match = ValueError, "record run differs"
    elif fault == "absent":
        inventory = ProtocolInventory(
            root_id=record.fence.root_id,
            run_id=record.run_id,
            fence=record.fence,
            revisions=(),
            generations=(),
        )
        presented = ProtocolTransition.bind(
            inventory, sequence=2, instant=datetime(2026, 1, 1, tzinfo=UTC), code_digest="b" * 64
        )
        error, match = ValueError, "no stored evidence"
    elif fault == "record":
        path = engine_boundary.volume / "protocol/000001.json"
        restore = (path, path.read_bytes())
        path.chmod(0o600)
        path.write_bytes(record.model_copy(update={"code_digest": "c" * 64}).canonical)
        error, match = ValueError, "differs from presented receipt"
    else:
        path = engine_boundary.volume / "protocol" / record.report_path
        restore = (path, path.read_bytes())
        path.chmod(0o600)
        path.write_bytes(b"{}")
        error, match = ValueError, "validation error"
    with pytest.raises(error, match=match):
        await controller.validate(peer, presented)
    assert generation_on_disk(controller_settings) == record.fence.generation
    if restore is not None:
        target, original = restore
        target.chmod(0o600)
        target.write_bytes(original)
    await controller.validate(1002, record)


async def test_complete_record_validates_repeatedly_and_a_restarted_controller_refuses_it(
    prepared: tuple[ManagedComposeController, ProtocolTransition],
    controller_settings: ControllerSettings,
) -> None:
    """A stored record validates on every repeated call but never survives a controller restart."""
    controller, record = prepared
    await controller.validate(1002, record)
    assert generation_on_disk(controller_settings) == record.fence.generation
    restarted = ManagedComposeController(controller_settings)
    assert generation_on_disk(controller_settings) == record.fence.generation + 1
    with pytest.raises(ValueError, match="generation changed"):
        await restarted.validate(1002, record)
    with pytest.raises(ValueError, match="restart is excluded"):
        restarted.restart(1003)


async def test_abandon_ends_only_the_live_epoch(
    prepared: tuple[ManagedComposeController, ProtocolTransition],
    controller_settings: ControllerSettings,
) -> None:
    """Abandoning a stale receipt is a no-op; abandoning the live one ends its epoch alone."""
    controller, record = prepared
    with pytest.raises(PermissionError, match="maintenance grant"):
        controller.abandon(1003, record.fence)
    controller.abandon(1002, record.fence)
    assert generation_on_disk(controller_settings) == record.fence.generation + 1
    controller.abandon(1002, record.fence)
    assert generation_on_disk(controller_settings) == record.fence.generation + 1
    with pytest.raises(ValueError, match="generation changed"):
        await controller.validate(1002, record)
    with pytest.raises(ValueError, match="restart is excluded"):
        controller.restart(1003)


def observation_fault(
    fault: str,
    engine_boundary: EngineBoundary,
    database_boundary: EmptyDatabaseBoundary,
    patch: pytest.MonkeyPatch,
    stack: ExitStack,
    tmp_path: Path,
) -> tuple[type[BaseException], str | None]:
    """Inject one guarded observation fault and report the class and message it raises."""
    if fault == "engine_connect":
        patch.setattr(
            engine_boundary, "volume_path", raising(httpx.ConnectError("engine unavailable"))
        )
        return httpx.ConnectError, None
    if fault == "engine_inventory":
        patch.setattr(engine_boundary, "inventory", raising(httpx.ReadTimeout("engine slow")))
        return httpx.ReadTimeout, None
    if fault == "foreign_writer":
        patch.setattr(engine_boundary, "containers", (writer(engine_boundary),))
        return ValueError, "foreign writer"
    if fault == "volume_identity":
        replacement = tmp_path / "replacement"
        replacement.mkdir()
        patch.setattr(engine_boundary, "volume", replacement)
        return ValueError, "identity changed"
    if fault == "database_identity":
        patch.setattr(database_boundary, "identity", "1/16384/other")
        return ValueError, "database identity differs"
    if fault == "sql_error":
        patch.setattr(database_boundary, "failure", asyncpg.PostgresError("private"))
        return asyncpg.PostgresError, None
    if fault == "sql_pool":
        patch.setattr(
            controller_module.asyncpg, "create_pool", raising(OSError("database unavailable"))
        )
        return OSError, None
    if fault == "store_owner":
        stack.enter_context(MaintenanceStore(engine_boundary.volume, 1001).claim())
        return BlockingIOError, None
    patch.setattr(database_boundary, "failure", asyncio.CancelledError())
    return asyncio.CancelledError, None


@pytest.mark.parametrize(
    "fault",
    [
        "engine_connect",
        "engine_inventory",
        "foreign_writer",
        "volume_identity",
        "database_identity",
        "sql_error",
        "sql_pool",
        "store_owner",
        "cancelled",
    ],
)
async def test_failed_observation_ends_the_epoch_before_the_refusal(
    prepared: tuple[ManagedComposeController, ProtocolTransition],
    controller_settings: ControllerSettings,
    engine_boundary: EngineBoundary,
    database_boundary: EmptyDatabaseBoundary,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fault: str,
) -> None:
    """Every guarded observation ends the epoch on disk before its own class is reported."""
    controller, record = prepared
    with ExitStack() as stack, monkeypatch.context() as patch:
        error, match = observation_fault(
            fault, engine_boundary, database_boundary, patch, stack, tmp_path
        )
        with pytest.raises(error, match=match):
            await controller.validate(1002, record)
    assert generation_on_disk(controller_settings) == record.fence.generation + 1
    with pytest.raises(ValueError, match="generation changed"):
        await controller.validate(1002, record)
    assert generation_on_disk(controller_settings) == record.fence.generation + 1
    assert controller.describe(1002).root_id == controller_settings.root_id


class LocalControllerTransport:
    """Forward the authenticated peer's port calls to the real controller in-process."""

    def __init__(self, controller: ManagedComposeController) -> None:
        self.controller = controller

    async def authenticate(self) -> MaintenanceGrant:
        """Authenticate peer 1002 through the real grant table."""
        return self.controller.authenticate(1002)

    async def establish(self, grant: MaintenanceGrant, run_id: UUID) -> FenceEvidence:
        """Mint through the real controller."""
        return await self.controller.establish(1002, run_id)

    async def check(self, evidence: FenceEvidence) -> None:
        """Observe through the real controller."""
        self.controller.check(1002, evidence)

    async def abandon(self, evidence: FenceEvidence) -> None:
        """Declare loss through the real controller."""
        self.controller.abandon(1002, evidence)

    async def validate(self, transition: ProtocolTransition) -> None:
        """Admit through the real controller."""
        await self.controller.validate(1002, transition)


@pytest.fixture
def composed(
    controller_settings: ControllerSettings,
    engine_boundary: EngineBoundary,
    database_boundary: EmptyDatabaseBoundary,
) -> tuple[ManagedComposeController, CutoverService]:
    """Compose the real coordinator over the real controller with only engine and SQL doubled."""
    controller = ManagedComposeController(controller_settings)
    transport = LocalControllerTransport(controller)
    service = CutoverService(
        transport,
        transport,
        PostgresRoleExclusion(database_boundary),
        EmptyCatalog(),
        MaintenanceStore(engine_boundary.volume, controller_settings.owner_uid),
        root_id=controller_settings.root_id,
        catalog_root=PurePosixPath("/data"),
        code_digest="b" * 64,
        now=lambda: datetime(2026, 1, 1, tzinfo=UTC),
    )
    return controller, service


@pytest.mark.parametrize("fault", ["post_install_fsync", "release_fence_loss"])
async def test_interrupted_prepare_ends_the_real_controllers_epoch(
    composed: tuple[ManagedComposeController, CutoverService],
    controller_settings: ControllerSettings,
    engine_boundary: EngineBoundary,
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    """A failure observed during a complete scan ends the epoch by exactly one true mechanism."""
    _, service = composed
    volume = engine_boundary.volume
    marker = volume / "protocol/000001.json"
    real_fsync = os.fsync
    real_close = os.close

    def faulting_fsync(descriptor: int) -> None:
        real_fsync(descriptor)
        protocol = volume / "protocol"
        if protocol.is_dir() and os.fstat(descriptor).st_ino == protocol.stat().st_ino and marker.exists():
            raise OSError("post-install fsync acknowledgement lost")

    def faulting_close(descriptor: int) -> None:
        info = os.fstat(descriptor)
        real_close(descriptor)
        lock = volume / "protocol/.maintenance.lock"
        if lock.exists() and info.st_ino == lock.stat().st_ino and marker.exists():
            engine_boundary.containers = (writer(engine_boundary),)

    with monkeypatch.context() as patch:
        if fault == "post_install_fsync":
            patch.setattr(os, "fsync", faulting_fsync)
            with pytest.raises(ExceptionGroup) as caught:
                await service.prepare(UUID(int=4))
            assert caught.group_contains(OSError)
        else:
            patch.setattr(os, "close", faulting_close)
            with pytest.raises(ValueError, match="foreign writer"):
                await service.prepare(UUID(int=4))
    assert generation_on_disk(controller_settings) == 3
    record = ProtocolTransition.decode(marker.read_bytes())
    engine_boundary.containers = ()
    with pytest.raises(ValueError, match="generation changed"):
        await service.validate(record)
    result = await service.prepare(UUID(int=5))
    assert result.sequence == 2
    assert result.fence.generation == 4
    assert marker.read_bytes() == record.canonical


async def test_lost_return_after_release_keeps_the_record_admissible(
    composed: tuple[ManagedComposeController, CutoverService],
    controller_settings: ControllerSettings,
    engine_boundary: EngineBoundary,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A lost close acknowledgement after a complete scan leaves the record validatable."""
    _, service = composed
    volume = engine_boundary.volume
    marker = volume / "protocol/000001.json"
    lock = volume / "protocol/.maintenance.lock"
    real_close = os.close

    def faulting_close(descriptor: int) -> None:
        info = os.fstat(descriptor)
        real_close(descriptor)
        if lock.exists() and info.st_ino == lock.stat().st_ino and marker.exists():
            raise OSError("close acknowledgement lost after release")

    with monkeypatch.context() as patch:
        patch.setattr(os, "close", faulting_close)
        with pytest.raises(OSError, match="close acknowledgement lost"):
            await service.prepare(UUID(int=4))
    assert generation_on_disk(controller_settings) == 2
    record = ProtocolTransition.decode(marker.read_bytes())
    await service.validate(record)
