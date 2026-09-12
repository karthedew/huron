"""Core cutover enforces external authority and orders durable report certification."""

import asyncio
import hashlib
import json
import shutil
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import UUID

import pytest

from huron.core.integrity.cutover import CutoverService
from huron.core.integrity.models import FenceEvidence, MaintenanceGrant, ProtocolInventory, ProtocolTransition
from huron.pkg.catalog.documents import CommitRecord
from huron.pkg.catalog.manifest import canonical_bytes
from huron.pkg.catalog.models import RevisionRecord
from huron.pkg.rawstore.maintenance import MaintenanceStore
from tests.unit.test_legacy_verification import legacy as legacy
from tests.unit.test_legacy_verification import legacy_records, overwrite

pytestmark = pytest.mark.unit


class DeploymentBoundary:
    """Deterministic external authentication, controller and role-fence boundary."""

    def __init__(self) -> None:
        self.grant = MaintenanceGrant(
            root_id=UUID(int=1), operator="operator", operations={"cutover"}
        )
        self.evidence = FenceEvidence(
            root_id=UUID(int=1),
            operator="operator",
            controller_id=UUID(int=3),
            generation=1,
            terminated_writers=("terminated-process",),
            old_roles=("old",),
            new_role="new",
        )
        self.valid = True
        self.excluded = False
        self.certificate = None

    async def authenticate(self) -> MaintenanceGrant:
        """Supply the grant from the injected authentication boundary."""
        return self.grant

    async def establish(self, grant: MaintenanceGrant, run_id: UUID) -> FenceEvidence:
        """Supply the controller's independently established exclusion evidence."""
        self.certificate = None
        return self.evidence

    async def exclude(self, old_roles: tuple[str, ...], new_role: str) -> None:
        """Record exclusion at the database I/O boundary."""
        self.excluded = True

    async def check(self, *arguments: object) -> None:
        """Refuse when the external enforced fence has been invalidated."""
        if not self.valid:
            raise ValueError("external fence lost")

    async def certify(self, transition: ProtocolTransition) -> None:
        """Endorse only while the external authority still excludes writers."""
        await self.check()
        self.certificate = transition

    async def validate_certificate(self, transition: ProtocolTransition) -> None:
        """Refuse prepared evidence that was never endorsed by this authority."""
        await self.check()
        if self.certificate != transition:
            raise ValueError("no current endorsement")


class EmptyCatalog:
    """An empty legacy database observed through its persistence boundary."""

    async def generation_records(self) -> tuple[object, ...]:
        """Supply no hierarchy records for an empty catalog."""
        return ()

    async def revision_paths(self) -> tuple[str, ...]:
        """Supply an empty catalog population."""
        return ()

    async def lookup(self, identity: object) -> None:
        """Treat a structurally trusted final as an orphan absent from the catalog."""
        return None

    async def resolve(self, *arguments: object) -> None:
        """Accept complete empty-population maintenance."""


def service(
    root: Path, boundary: DeploymentBoundary, *, check_interval: float = 1
) -> CutoverService:
    """Compose actual core/storage behavior with deterministic external boundaries."""
    return CutoverService(
        boundary,
        boundary,
        boundary,
        EmptyCatalog(),
        MaintenanceStore(root, root.stat().st_uid),
        root_id=UUID(int=1),
        catalog_root=PurePosixPath("/data"),
        code_digest="b" * 64,
        now=lambda: datetime(2026, 1, 1, tzinfo=UTC),
        check_interval=check_interval,
    )


async def test_cutover_writes_bound_report_before_record_and_replays_same_receipt(
    tmp_path: Path,
) -> None:
    """An authenticated complete scan leaves writers disabled and one immutable receipt."""
    boundary = DeploymentBoundary()
    cutover = service(tmp_path, boundary)
    record = await cutover.prepare(UUID(int=2))
    report = ProtocolInventory.decode(
        (tmp_path / "protocol/reports" / f"{UUID(int=2)}.json").read_bytes()
    )
    record.validate_inventory(report)
    assert boundary.excluded
    assert (tmp_path / "protocol/000001.json").read_bytes() == record.canonical
    assert await cutover.prepare(UUID(int=2)) == record


@pytest.mark.parametrize("changes", [{"root_id": UUID(int=99)}, {"operations": frozenset()}])
async def test_cutover_requires_an_authenticated_root_and_operation_grant(
    tmp_path: Path, changes: dict[str, object]
) -> None:
    """Wrong-root and missing-operation grants cannot reach writer shutdown or certification."""
    boundary = DeploymentBoundary()
    boundary.grant = boundary.grant.model_copy(update=changes)
    with pytest.raises(PermissionError, match="not authorized"):
        await service(tmp_path, boundary).prepare(UUID(int=2))
    assert not boundary.excluded
    assert not (tmp_path / "protocol/000001.json").exists()


async def test_controller_evidence_must_match_external_authentication(tmp_path: Path) -> None:
    """A controller cannot substitute a different actor after authentication."""
    boundary = DeploymentBoundary()
    boundary.evidence = boundary.evidence.model_copy(update={"operator": "other"})
    with pytest.raises(ValueError, match="authenticated authority"):
        await service(tmp_path, boundary).prepare(UUID(int=2))
    assert not (tmp_path / "protocol/000001.json").exists()


async def test_lost_external_fence_prevents_a_report(tmp_path: Path) -> None:
    """No observation can certify a root after its exclusion proof is lost."""
    boundary = DeploymentBoundary()
    boundary.valid = False
    with pytest.raises(ValueError, match="external fence lost"):
        await service(tmp_path, boundary).prepare(UUID(int=2))
    assert not (tmp_path / "protocol/000001.json").exists()


def test_fence_observation_interval_must_be_positive(tmp_path: Path) -> None:
    """An invalid monitor interval cannot disable periodic observation."""
    boundary = DeploymentBoundary()
    with pytest.raises(ValueError, match="positive"):
        CutoverService(
            boundary,
            boundary,
            boundary,
            EmptyCatalog(),
            MaintenanceStore(tmp_path, tmp_path.stat().st_uid),
            root_id=UUID(int=1),
            catalog_root=PurePosixPath("/data"),
            code_digest="b" * 64,
            now=lambda: datetime(2026, 1, 1, tzinfo=UTC),
            check_interval=0,
        )


async def test_complete_scan_records_exact_healthy_orphan_membership(
    tmp_path: Path,
    legacy: tuple[object, str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The workflow scans real documents and publishes exact verified membership."""
    boundary = DeploymentBoundary()

    async def records(catalog: EmptyCatalog) -> tuple[object, ...]:
        """Supply the acknowledged hierarchy from the persistence boundary."""
        return legacy_records()

    monkeypatch.setattr(EmptyCatalog, "generation_records", records)
    result = await service(tmp_path, boundary).prepare(UUID(int=2))
    report = ProtocolInventory.decode(
        (tmp_path / "protocol/reports" / f"{UUID(int=2)}.json").read_bytes()
    )
    assert len(report.revisions) == 1
    assert report.revisions[0].path == legacy[1]
    assert report.revisions[0].outcome == "VERIFIED"
    result.validate_inventory(report)


async def test_report_without_record_is_resumable_under_the_same_fence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A crash after durable report installation can replay without fabricating a record."""
    original = MaintenanceStore.write_evidence

    def write(store: MaintenanceStore, path: str, payload: bytes) -> None:
        """Interrupt only the record installation at the storage I/O boundary."""
        if path == "000001.json":
            raise OSError("record installation interrupted")
        original(store, path, payload)

    boundary = DeploymentBoundary()
    with monkeypatch.context() as patch:
        patch.setattr(MaintenanceStore, "write_evidence", write)
        with pytest.raises(ExceptionGroup, match="TaskGroup"):
            await service(tmp_path, boundary).prepare(UUID(int=2))
    report = tmp_path / "protocol/reports" / f"{UUID(int=2)}.json"
    assert report.is_file()
    assert not (tmp_path / "protocol/000001.json").exists()
    before = report.read_bytes()
    await service(tmp_path, boundary).prepare(UUID(int=2))
    assert report.read_bytes() == before
    assert (tmp_path / "protocol/000001.json").is_file()


async def test_periodic_fence_loss_interrupts_an_incomplete_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The live monitor interrupts a blocked scan when external exclusion is lost."""
    boundary = DeploymentBoundary()

    async def blocked(catalog: EmptyCatalog) -> tuple[object, ...]:
        """Hold a database read after invalidating the independently observed fence."""
        boundary.valid = False
        await asyncio.Future()
        return ()

    monkeypatch.setattr(EmptyCatalog, "generation_records", blocked)
    with pytest.raises(ExceptionGroup, match="TaskGroup"):
        await asyncio.wait_for(
            service(tmp_path, boundary, check_interval=0.001).prepare(UUID(int=2)), 1
        )
    assert not (tmp_path / "protocol/000001.json").exists()


async def test_corrupt_revision_does_not_prevent_exact_healthy_population_certification(
    tmp_path: Path,
    legacy: tuple[object, str, RevisionRecord],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The complete population retains degraded evidence while certifying only healthy members."""
    _, first_path, first = legacy
    second_path = str(PurePosixPath(first_path).parent / f"000002--{UUID(int=15).hex}")
    shutil.copytree(tmp_path / first_path, tmp_path / second_path)
    metadata = json.loads((tmp_path / second_path / "metadata.json").read_bytes())
    metadata["revision_number"] = 2
    metadata_bytes = canonical_bytes(metadata)
    second = replace(
        first,
        id=UUID(int=15),
        number=2,
        revision_path=str(PurePosixPath("/data") / second_path),
        metadata_sha256=hashlib.sha256(metadata_bytes).hexdigest(),
    )
    overwrite(tmp_path, second_path, "metadata.json", metadata_bytes)
    overwrite(
        tmp_path, second_path, "COMMITTED", replace(CommitRecord.of(second), protocol=1).canonical
    )
    overwrite(tmp_path, first_path, "payload/file", b"corruption")

    async def records(catalog: EmptyCatalog) -> tuple[object, ...]:
        return legacy_records()

    monkeypatch.setattr(EmptyCatalog, "generation_records", records)
    receipt = await service(tmp_path, DeploymentBoundary()).prepare(UUID(int=2))
    report = ProtocolInventory.decode(
        (tmp_path / "protocol/reports" / f"{UUID(int=2)}.json").read_bytes()
    )
    assert [(entry.revision_id, entry.outcome) for entry in report.revisions] == [
        (first.id, "DEGRADED"),
        (second.id, "VERIFIED"),
    ]
    assert receipt.verified_count == 1
    assert receipt.degraded_revision_ids == (first.id,)
    receipt.validate_inventory(report)


async def test_database_resolution_fence_loss_cannot_publish_or_resume_old_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lost exclusion at the transaction boundary requires a fresh complete verification."""
    boundary = DeploymentBoundary()

    async def resolve(*arguments: object) -> None:
        boundary.valid = False

    with monkeypatch.context() as patch:
        patch.setattr(EmptyCatalog, "resolve", resolve)
        with pytest.raises(ExceptionGroup):
            await service(tmp_path, boundary).prepare(UUID(int=2))
    assert not (tmp_path / "protocol/reports" / f"{UUID(int=2)}.json").exists()
    boundary.valid = True
    assert (await service(tmp_path, boundary).prepare(UUID(int=2))).run_id == UUID(int=2)
    result = await service(tmp_path, boundary).prepare(UUID(int=4))
    assert result.run_id == UUID(int=4)


@pytest.mark.parametrize("destination", ["report", "record"])
async def test_lost_fence_during_installation_retains_unusable_history_and_allows_fresh_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, destination: str
) -> None:
    """Installed bytes remain forensic history until a complete new preparation is endorsed."""
    boundary = DeploymentBoundary()
    original = MaintenanceStore.write_evidence
    report = f"reports/{UUID(int=2)}.json"
    selected = report if destination == "report" else "000001.json"

    def write(store: MaintenanceStore, path: str, payload: bytes) -> None:
        original(store, path, payload)
        if path == selected:
            boundary.valid = False

    with monkeypatch.context() as patch:
        patch.setattr(MaintenanceStore, "write_evidence", write)
        with pytest.raises(ExceptionGroup):
            await service(tmp_path, boundary).prepare(UUID(int=2))
    stranded = (tmp_path / "protocol" / selected).read_bytes()
    assert boundary.certificate is None
    boundary.valid = True
    result = await service(tmp_path, boundary).prepare(UUID(int=4))
    assert result.sequence == (2 if destination == "record" else 1)
    assert (tmp_path / "protocol" / selected).read_bytes() == stranded
    assert await service(tmp_path, boundary).prepare(UUID(int=4)) == result


@pytest.mark.parametrize("fence_intact", [False, True])
async def test_cancelled_installation_waits_for_its_actual_writer_before_resolving_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fence_intact: bool
) -> None:
    """Cancellation cannot abandon an in-flight write or certify it after its fence is lost."""
    import threading

    boundary = DeploymentBoundary()
    original = MaintenanceStore.write_evidence
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    released = threading.Event()
    finished = threading.Event()

    def write(store: MaintenanceStore, path: str, payload: bytes) -> None:
        if path == "000001.json":
            loop.call_soon_threadsafe(entered.set)
            assert released.wait(timeout=5), "test did not release its storage writer"
        original(store, path, payload)
        if path == "000001.json":
            finished.set()

    monkeypatch.setattr(MaintenanceStore, "write_evidence", write)
    task = asyncio.create_task(service(tmp_path, boundary).prepare(UUID(int=2)))
    await asyncio.wait_for(entered.wait(), 5)
    boundary.valid = fence_intact
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    assert not finished.is_set()
    released.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert finished.is_set()
    assert boundary.certificate is None
    boundary.valid = True
    assert (await service(tmp_path, boundary).prepare(UUID(int=2))).sequence == 1


async def test_failed_directory_sync_leaves_prepared_record_without_endorsement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A write that mutates storage then fails cannot certify its stranded immutable bytes."""
    import os

    original = os.fsync
    record_path = tmp_path / "protocol/000001.json"
    boundary = DeploymentBoundary()

    def sync(descriptor: int) -> None:
        original(descriptor)
        if record_path.exists():
            raise OSError("directory sync acknowledgement lost")

    with monkeypatch.context() as patch:
        patch.setattr(os, "fsync", sync)
        with pytest.raises(ExceptionGroup):
            await service(tmp_path, boundary).prepare(UUID(int=2))
    record = ProtocolTransition.decode(record_path.read_bytes())
    with pytest.raises(ValueError, match="no current endorsement"):
        await service(tmp_path, boundary).validate(record)
    assert await service(tmp_path, boundary).prepare(UUID(int=2)) == record
    await service(tmp_path, boundary).validate(record)


async def test_observed_fence_loss_stays_invalid_after_external_observations_recover(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A monitor's lost exclusion cannot be erased while its cancelled storage writer finishes."""
    import threading

    entered = asyncio.Event()
    observed = asyncio.Event()
    released = threading.Event()
    loop = asyncio.get_running_loop()
    original = MaintenanceStore.write_evidence

    class RecoveringBoundary(DeploymentBoundary):
        async def check(self, *arguments: object) -> None:
            if entered.is_set() and not observed.is_set():
                observed.set()
                raise ValueError("one observed exclusion loss")

    def write(store: MaintenanceStore, path: str, payload: bytes) -> None:
        if path == "000001.json":
            loop.call_soon_threadsafe(entered.set)
            assert released.wait(timeout=5)
        original(store, path, payload)

    monkeypatch.setattr(MaintenanceStore, "write_evidence", write)
    task = asyncio.create_task(
        service(tmp_path, RecoveringBoundary(), check_interval=0.001).prepare(UUID(int=2))
    )
    try:
        await asyncio.wait_for(observed.wait(), 5)
    finally:
        released.set()
    with pytest.raises(ExceptionGroup):
        await task
    assert (tmp_path / "protocol/000001.json").is_file()
    replacement = DeploymentBoundary()
    record = ProtocolTransition.decode((tmp_path / "protocol/000001.json").read_bytes())
    with pytest.raises(ValueError, match="no current endorsement"):
        await service(tmp_path, replacement).validate(record)


async def test_independent_cutovers_cannot_share_a_live_same_run_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second coordinator is refused while the first owns a blocked database observation."""
    entered = asyncio.Event()
    release = asyncio.Event()
    boundary = DeploymentBoundary()

    async def records(*arguments: object) -> tuple[object, ...]:
        entered.set()
        await release.wait()
        return ()

    monkeypatch.setattr(EmptyCatalog, "generation_records", records)
    first = asyncio.create_task(service(tmp_path, boundary).prepare(UUID(int=2)))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        with pytest.raises(BlockingIOError):
            await service(tmp_path, boundary).prepare(UUID(int=2))
        assert not first.done()
        assert not (tmp_path / "protocol/000001.json").exists()
    finally:
        release.set()
    record = await first
    await service(tmp_path, boundary).validate(record)
    assert await service(tmp_path, boundary).prepare(UUID(int=2)) == record


@pytest.mark.parametrize("change", ["root", "actor", "grant", "operation"])
async def test_consumer_requires_exact_root_and_operator_authority(
    tmp_path: Path, change: str
) -> None:
    """Receipt possession cannot authorize a different root or maintenance principal."""
    boundary = DeploymentBoundary()
    record = await service(tmp_path, boundary).prepare(UUID(int=2))
    if change == "root":
        record = record.model_copy(update={"root_id": UUID(int=99)})
    elif change == "actor":
        record = record.model_copy(update={"actor": "other"})
    elif change == "grant":
        boundary.grant = boundary.grant.model_copy(update={"root_id": UUID(int=99)})
    else:
        boundary.grant = boundary.grant.model_copy(update={"operations": frozenset()})
    with pytest.raises(PermissionError):
        await service(tmp_path, boundary).validate(record)


@pytest.mark.parametrize("after_close", [False, True])
async def test_exclusion_loss_at_ownership_release_cannot_return_a_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, after_close: bool
) -> None:
    """Final ownership release remains inside the exclusion-to-endorsement boundary."""
    import os

    boundary = DeploymentBoundary()
    original = os.close
    record_path = tmp_path / "protocol/000001.json"
    lock_path = tmp_path / "protocol/.maintenance.lock"

    def close(descriptor: int) -> None:
        final = record_path.exists() and os.fstat(descriptor).st_ino == lock_path.stat().st_ino
        if final and not after_close:
            boundary.valid = False
        original(descriptor)
        if final and after_close:
            boundary.valid = False

    with monkeypatch.context() as patch:
        patch.setattr(os, "close", close)
        with pytest.raises(ValueError, match="external fence lost"):
            await service(tmp_path, boundary).prepare(UUID(int=2))
    record = ProtocolTransition.decode(record_path.read_bytes())
    boundary.valid = True
    with pytest.raises(ValueError, match="no current endorsement"):
        await service(tmp_path, boundary).validate(record)


async def test_concurrent_observations_cannot_replace_a_lost_fence_with_recovered_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A queued publication check refuses the monitor's recorded exclusion loss."""
    resolving = asyncio.Event()
    observing = asyncio.Event()
    release = asyncio.Event()

    class ObservationBoundary(DeploymentBoundary):
        async def check(self, *arguments: object) -> None:
            if resolving.is_set() and not observing.is_set():
                observing.set()
                await release.wait()
                raise ValueError("observed exclusion loss")

    async def resolve(*arguments: object) -> None:
        resolving.set()
        await observing.wait()
        asyncio.get_running_loop().call_soon(release.set)

    monkeypatch.setattr(EmptyCatalog, "resolve", resolve)
    boundary = ObservationBoundary()
    with pytest.raises(ExceptionGroup):
        await asyncio.wait_for(service(tmp_path, boundary, check_interval=0.001).prepare(UUID(int=2)), 5)
    assert boundary.certificate is None
    assert not (tmp_path / "protocol/000001.json").exists()
