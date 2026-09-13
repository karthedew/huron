import asyncio, sys, tempfile
from pathlib import Path
from uuid import UUID
sys.path.insert(0, ".")
from tests.unit.test_integrity_cutover import DeploymentBoundary, EmptyCatalog, service

class Counting(DeploymentBoundary):
    establishes = 0
    async def establish(self, grant, run_id):
        type(self).establishes += 1
        return await super().establish(grant, run_id)

async def main() -> None:
    tmp = Path(tempfile.mkdtemp())
    entered = asyncio.Event(); release = asyncio.Event()
    boundary = Counting()
    original = EmptyCatalog.generation_records
    async def records(*a):
        entered.set(); await release.wait(); return ()
    EmptyCatalog.generation_records = records
    first = asyncio.create_task(service(tmp, boundary).prepare(UUID(int=2)))
    await asyncio.wait_for(entered.wait(), 5)
    assert Counting.establishes == 1, Counting.establishes
    try:
        await service(tmp, boundary).prepare(UUID(int=2))
    except BlockingIOError:
        print("BlockingIOError raised; establish calls after second prepare:", Counting.establishes)
    else:
        print("NO BlockingIOError")
    release.set()
    await first
    EmptyCatalog.generation_records = original

asyncio.run(main())
