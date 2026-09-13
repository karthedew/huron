"""Prepared evidence becomes usable only through complete live controller validation."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from huron.applications.lakectl import controller as controller_module
from huron.applications.lakectl.controller import ManagedComposeController
from huron.applications.lakectl.settings import ControllerSettings
from huron.core.integrity.models import ProtocolInventory, ProtocolTransition
from huron.pkg.rawstore.maintenance import MaintenanceStore
from tests.unit.test_controller_settings import controller_settings as controller_settings
from tests.unit.test_controller_settings import root_metadata as root_metadata
from tests.unit.test_lakectl_wiring import EmptyDatabaseBoundary
from tests.unit.test_managed_controller import EngineBoundary, engine_boundary as engine_boundary
from tests.unit.test_managed_controller import writer

pytestmark = pytest.mark.unit


@pytest.fixture
def prepared(controller_settings: ControllerSettings, engine_boundary: EngineBoundary,
             monkeypatch: pytest.MonkeyPatch) -> tuple[ManagedComposeController, ProtocolTransition]:
    """Write real immutable evidence and substitute only engine and SQL observations."""
    monkeypatch.setattr(controller_module.asyncpg, "create_pool", lambda url: EmptyDatabaseBoundary())
    controller = ManagedComposeController(controller_settings)
    fence = controller.establish(1002, UUID(int=3))
    inventory = ProtocolInventory(root_id=fence.root_id, run_id=UUID(int=3), fence=fence,
                                  revisions=(), generations=())
    record = ProtocolTransition.bind(inventory, sequence=1,
                                    instant=datetime(2026, 1, 1, tzinfo=UTC), code_digest="b" * 64)
    store = MaintenanceStore(engine_boundary.volume, controller_settings.owner_uid)
    store.write_evidence(record.report_path, inventory.canonical)
    store.write_evidence("000001.json", record.canonical)
    return controller, record


async def test_prepared_files_require_endorsement_and_restart_requires_reverification(
    prepared: tuple[ManagedComposeController, ProtocolTransition], controller_settings: ControllerSettings,
    engine_boundary: EngineBoundary,
) -> None:
    """Complete files alone never imply success, and a new authority cannot inherit endorsement."""
    controller, record = prepared
    with pytest.raises(ValueError, match="no current controller endorsement"):
        await controller.validate_certificate(1002, record)
    await controller.certify(1002, record)
    await controller.validate_certificate(1002, record)
    restarted = ManagedComposeController(controller_settings)
    with pytest.raises(ValueError, match="no current controller endorsement"):
        await restarted.validate_certificate(1002, record)
    with pytest.raises(ValueError, match="generation changed"):
        await restarted.certify(1002, record)


async def test_observed_writer_loss_permanently_revokes_endorsement(
    prepared: tuple[ManagedComposeController, ProtocolTransition], engine_boundary: EngineBoundary,
) -> None:
    """Restoring external observations does not revive a certificate rejected by its authority."""
    controller, record = prepared
    await controller.certify(1002, record)
    engine_boundary.containers = (writer(engine_boundary),)
    with pytest.raises(ValueError, match="foreign writer"):
        await controller.validate_certificate(1002, record)
    engine_boundary.containers = ()
    with pytest.raises(ValueError, match="no current controller endorsement"):
        await controller.validate_certificate(1002, record)


async def test_live_storage_owner_prevents_endorsement_and_consumer_admission(
    prepared: tuple[ManagedComposeController, ProtocolTransition], engine_boundary: EngineBoundary,
) -> None:
    """Another maintenance instance cannot certify while an owner can still write."""
    controller, record = prepared
    store = MaintenanceStore(engine_boundary.volume, 1001)
    with store.claim():
        with pytest.raises(BlockingIOError):
            await controller.certify(1002, record)
    with pytest.raises(ValueError, match="no current controller endorsement"):
        await controller.validate_certificate(1002, record)
    await controller.certify(1002, record)
    with store.claim():
        with pytest.raises(BlockingIOError):
            await controller.validate_certificate(1002, record)
    with pytest.raises(ValueError, match="no current controller endorsement"):
        await controller.validate_certificate(1002, record)


@pytest.mark.parametrize("fault", ["record", "report", "sql", "release", "run", "peer"])
async def test_failed_finalization_never_endorses_prepared_history(
    prepared: tuple[ManagedComposeController, ProtocolTransition], engine_boundary: EngineBoundary,
    monkeypatch: pytest.MonkeyPatch, fault: str,
) -> None:
    """Every storage, SQL, ownership and authority failure leaves consumer admission closed."""
    import os

    controller, record = prepared
    original_close = os.close
    lock_inode = None
    if fault == "record":
        path = engine_boundary.volume / "protocol/000001.json"
        path.chmod(0o600)
        path.write_bytes(record.model_copy(update={"code_digest": "c" * 64}).canonical)
    elif fault == "report":
        path = engine_boundary.volume / "protocol" / record.report_path
        path.chmod(0o600)
        path.write_bytes(b"{}")
    elif fault == "sql":
        def unavailable(url: str) -> None:
            raise OSError("database unavailable")
        monkeypatch.setattr(controller_module.asyncpg, "create_pool", unavailable)
    elif fault == "release":
        with MaintenanceStore(engine_boundary.volume, 1001).claim():
            lock_inode = (engine_boundary.volume / "protocol/.maintenance.lock").stat().st_ino

        def close(descriptor: int) -> None:
            inode = os.fstat(descriptor).st_ino
            original_close(descriptor)
            if inode == lock_inode:
                raise OSError("close acknowledgement failed after releasing ownership")
        monkeypatch.setattr(os, "close", close)
    elif fault == "run":
        record = record.model_copy(update={"run_id": UUID(int=4)})
    with pytest.raises((ValueError, OSError, PermissionError)):
        await controller.certify(1003 if fault == "peer" else 1002, record)
    with pytest.raises(ValueError, match="no current controller endorsement"):
        await controller.validate_certificate(1002, record)
