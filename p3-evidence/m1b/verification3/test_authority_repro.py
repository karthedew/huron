"""Independent consumer-authority regressions at external I/O boundaries."""
import json
import httpx
import pytest
from tests.unit.test_controller_certificates import prepared as prepared
from tests.unit.test_controller_settings import controller_settings as controller_settings
from tests.unit.test_controller_settings import root_metadata as root_metadata
from tests.unit.test_managed_controller import engine_boundary as engine_boundary, writer

pytestmark = pytest.mark.unit

async def test_observed_unreachable_engine_permanently_revokes_receipt(prepared, engine_boundary, monkeypatch):
    controller, record = prepared
    await controller.certify(1002, record)
    def unavailable(name):
        raise httpx.ConnectError('engine unavailable')
    with monkeypatch.context() as patch:
        patch.setattr(engine_boundary, 'volume_path', unavailable)
        with pytest.raises(httpx.ConnectError):
            controller.check(1002, record.fence)
    with pytest.raises(ValueError, match='endorsement'):
        await controller.validate_certificate(1002, record)

async def test_changed_maintenance_database_configuration_invalidates_receipt(prepared, controller_settings):
    controller, record = prepared
    await controller.certify(1002, record)
    path = controller_settings.maintenance_path
    changed = json.loads(path.read_bytes())
    changed['database_url'] = 'postgresql://cutover@different-database/unrelated'
    path.write_text(json.dumps(changed))
    with pytest.raises(ValueError):
        await controller.validate_certificate(1002, record)

async def test_revoked_receipt_cannot_be_reendorsed_without_full_reverification(prepared, engine_boundary):
    controller, record = prepared
    await controller.certify(1002, record)
    engine_boundary.containers = (writer(engine_boundary),)
    with pytest.raises(ValueError):
        await controller.validate_certificate(1002, record)
    engine_boundary.containers = ()
    with pytest.raises(ValueError):
        await controller.certify(1002, record)
