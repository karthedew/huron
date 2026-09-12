"""Independent finalization checks across real core, controller and filesystem behavior."""
from datetime import UTC, datetime
from pathlib import PurePosixPath
from uuid import UUID
import os
import pytest
from huron.applications.lakectl.controller import ManagedComposeController
from huron.applications.lakectl import controller as controller_module
from huron.core.integrity.cutover import CutoverService
from huron.core.integrity.models import ProtocolTransition
from huron.pkg.metastore.maintenance import PostgresRoleExclusion
from huron.pkg.rawstore.maintenance import MaintenanceStore
from tests.unit.test_controller_settings import controller_settings as controller_settings
from tests.unit.test_controller_settings import root_metadata as root_metadata
from tests.unit.test_managed_controller import engine_boundary as engine_boundary, writer
from tests.unit.test_lakectl_wiring import EmptyDatabaseBoundary
from tests.unit.test_integrity_cutover import EmptyCatalog

pytestmark = pytest.mark.unit

class LocalControllerTransport:
    """Forward the authenticated test peer through the actual authority implementation."""
    def __init__(self, authority):
        self.authority = authority
    async def authenticate(self):
        return self.authority.authenticate(1002)
    async def establish(self, grant, run_id):
        return self.authority.establish(1002, run_id)
    async def check(self, evidence):
        self.authority.check(1002, evidence)
    async def certify(self, record):
        await self.authority.certify(1002, record)
    async def validate_certificate(self, record):
        await self.authority.validate_certificate(1002, record)

@pytest.mark.parametrize('fault', ['post_install_fsync', 'post_release_close', 'release_fence_loss'])
async def test_failed_finalization_leaves_actual_consumer_closed(controller_settings, engine_boundary, monkeypatch, fault):
    monkeypatch.setattr(controller_module.asyncpg, 'create_pool', lambda url: EmptyDatabaseBoundary())
    authority = ManagedComposeController(controller_settings)
    transport = LocalControllerTransport(authority)
    root = engine_boundary.volume
    service = CutoverService(transport, transport, PostgresRoleExclusion(EmptyDatabaseBoundary()),
        EmptyCatalog(), MaintenanceStore(root, 1001), root_id=controller_settings.root_id,
        catalog_root=PurePosixPath('/data'), code_digest='b'*64,
        now=lambda: datetime(2026,1,1,tzinfo=UTC))
    path = root/'protocol/000001.json'
    original_sync, original_close = os.fsync, os.close
    def sync(fd):
        original_sync(fd)
        if path.exists():
            raise OSError('post-install fsync acknowledgement lost')
    def close(fd):
        final = path.exists() and os.fstat(fd).st_ino == (root/'protocol/.maintenance.lock').stat().st_ino
        original_close(fd)
        if final:
            if fault == 'post_release_close':
                raise OSError('close acknowledgement lost after actual release')
            engine_boundary.containers = (writer(engine_boundary),)
    with monkeypatch.context() as patch:
        patch.setattr(os, 'fsync' if fault == 'post_install_fsync' else 'close', sync if fault == 'post_install_fsync' else close)
        with pytest.raises((OSError, ValueError, ExceptionGroup)):
            await service.prepare(UUID(int=4))
    record = ProtocolTransition.decode(path.read_bytes())
    engine_boundary.containers = ()
    with pytest.raises(ValueError, match='endorsement'):
        await service.validate(record)
    result = await service.prepare(UUID(int=4))
    assert result == record
    await service.validate(result)
