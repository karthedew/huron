import json
from pathlib import Path
from uuid import UUID
import pytest
from huron.applications.lakectl.controller import ManagedComposeController
from huron.applications.lakectl.engine import Container
from tests.unit.test_managed_controller import engine_boundary, writer
from tests.unit.test_controller_settings import controller_settings, root_metadata
pytestmark=pytest.mark.unit

def test_foreign_descendant_mount_must_block(controller_settings,engine_boundary):
    item=writer(engine_boundary).model_dump(by_alias=True)
    item['Image']='sha256:'+'c'*64
    item['Mounts']=[{'Type':'bind','Source':str(engine_boundary.volume/'organization'),'Destination':'/foreign','RW':True}]
    engine_boundary.containers=(Container.model_validate(item),)
    controller=ManagedComposeController(controller_settings)
    with pytest.raises(ValueError):
        controller.establish(1002,UUID(int=3))

def test_changed_live_compose_must_invalidate(controller_settings,engine_boundary):
    controller=ManagedComposeController(controller_settings)
    evidence=controller.establish(1002,UUID(int=3))
    document=json.loads(controller_settings.compose_path.read_bytes())
    document['services']['api']['command']=['a-different-application-command']
    controller_settings.compose_path.write_text(json.dumps(document))
    with pytest.raises(ValueError):
        controller.check(1002,evidence)
from tests.unit.test_integrity_cutover import DeploymentBoundary,EmptyCatalog,service
from huron.pkg.rawstore.maintenance import MaintenanceStore

async def test_lost_fence_during_database_resolution_must_not_publish_report(tmp_path,monkeypatch):
    boundary=DeploymentBoundary()
    async def resolve(*args):
        boundary.valid=False
    monkeypatch.setattr(EmptyCatalog,'resolve',resolve)
    with pytest.raises(ExceptionGroup):
        await service(tmp_path,boundary).prepare(UUID(int=2))
    assert not (tmp_path/'protocol/reports'/f'{UUID(int=2)}.json').exists()

async def test_lost_fence_during_record_installation_must_not_return_success(tmp_path,monkeypatch):
    boundary=DeploymentBoundary()
    original=MaintenanceStore.write_evidence
    def write(store,path,payload):
        if path=='000001.json': boundary.valid=False
        original(store,path,payload)
    monkeypatch.setattr(MaintenanceStore,'write_evidence',write)
    with pytest.raises(ExceptionGroup):
        await service(tmp_path,boundary).prepare(UUID(int=2))
