"""Independent failure probes for final evidence ownership."""
import os
from uuid import UUID
import pytest
from tests.unit.test_integrity_cutover import DeploymentBoundary, service

pytestmark=pytest.mark.unit

async def test_failed_pending_directory_fsync_must_not_leave_record_usable(tmp_path,monkeypatch):
    boundary=DeploymentBoundary()
    record=tmp_path/'protocol/000001.json'
    pending=tmp_path/'protocol/pending'/f'{UUID(int=2)}.json'
    original=os.fsync
    def fsync(descriptor):
        if record.exists() and not pending.exists() and os.fstat(descriptor).st_ino==pending.parent.stat().st_ino:
            raise OSError('pending directory fsync failed after unlink')
        original(descriptor)
    with monkeypatch.context() as patch:
        patch.setattr(os,'fsync',fsync)
        with pytest.raises(ExceptionGroup):
            await service(tmp_path,boundary).prepare(UUID(int=2))
    assert record.exists()
    assert pending.exists(), 'Failed finalization left installed record with no pending invalidator'

async def test_fence_loss_during_pending_clear_must_not_return_success(tmp_path,monkeypatch):
    boundary=DeploymentBoundary()
    record=tmp_path/'protocol/000001.json'
    original=os.unlink
    def unlink(path,**options):
        if path==f'{UUID(int=2)}.json' and record.exists():
            boundary.valid=False
        original(path,**options)
    monkeypatch.setattr(os,'unlink',unlink)
    with pytest.raises(ExceptionGroup):
        await service(tmp_path,boundary).prepare(UUID(int=2))

async def test_concurrent_same_run_cannot_clear_another_live_installation(tmp_path,monkeypatch):
    import asyncio
    import threading
    from tests.unit.test_integrity_cutover import EmptyCatalog
    from huron.pkg.rawstore.maintenance import MaintenanceStore
    boundary=DeploymentBoundary()
    arrivals=0
    both=asyncio.Event()
    async def records(*args):
        nonlocal arrivals
        arrivals+=1
        if arrivals==2: both.set()
        await both.wait()
        return ()
    monkeypatch.setattr(EmptyCatalog,'generation_records',records)
    original=MaintenanceStore.write_evidence
    calls=0
    lock=threading.Lock()
    release=threading.Event()
    entered=asyncio.Event()
    loop=asyncio.get_running_loop()
    def write(store,path,payload):
        nonlocal calls
        if path.startswith('reports/'):
            with lock:
                calls+=1
                number=calls
            if number==2:
                loop.call_soon_threadsafe(entered.set)
                assert release.wait(5)
        original(store,path,payload)
    monkeypatch.setattr(MaintenanceStore,'write_evidence',write)
    tasks=[asyncio.create_task(service(tmp_path,boundary).prepare(UUID(int=2))) for _ in range(2)]
    try:
        await asyncio.wait_for(entered.wait(),5)
        done,_=await asyncio.wait(tasks,timeout=5,return_when=asyncio.FIRST_COMPLETED)
        assert done
        assert any(task.exception() is None for task in done), [repr(task.exception()) for task in done]
        assert (tmp_path/"protocol/000001.json").exists()
        assert (tmp_path/'protocol/pending'/f'{UUID(int=2)}.json').exists(), 'One invocation cleared ownership while another writer remained live'
    finally:
        release.set()
        await asyncio.gather(*tasks,return_exceptions=True)
