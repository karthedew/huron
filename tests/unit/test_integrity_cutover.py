"""Core cutover enforces external authority and appends one report and one record per epoch."""

import asyncio
import hashlib
import json
import shutil
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import UUID

import pytest

from huron.core.integrity import CutoverService
from huron.core.integrity.models import FenceEvidence, MaintenanceGrant, ProtocolInventory, ProtocolTransition
from huron.core.raw.documents import CommitRecord
from huron.core.foundation.canonical import canonical_bytes
from huron.core.raw.types import RevisionRecord
from huron.core.rawstore.maintenance import MaintenanceStore
from tests.unit.test_lakectl_wiring import IDENTITY
from tests.unit.test_legacy_verification import legacy as legacy
from tests.unit.test_legacy_verification import legacy_records, overwrite

pytestmark = pytest.mark.unit


class DeploymentBoundary:
    """Deterministic authentication, controller epoch and role-fence boundary.

    The start receipt is generation 1 and is never issued; ``establish`` mints 2, and every
    observed loss, ``abandon`` of the live receipt and later mint adds one, as the real
    controller's durable state does.
    """

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
            database=IDENTITY,
        )
        self.valid = True
        self.excluded = False
        self.abandoned: list[int] = []

    async def authenticate(self) -> MaintenanceGrant:
        """Supply the grant from the injected authentication boundary."""
        return self.grant

    async def establish(self, grant: MaintenanceGrant, run_id: UUID) -> FenceEvidence:
        """Mint the next epoch unconditionally and issue its receipt."""
        self._advance()
        return self.evidence

    async def identify(self) -> str:
        """Report the maintenance database identity the receipts carry."""
        return self.evidence.database

    async def exclude(self, fence: FenceEvidence) -> None:
        """Record exclusion at the database I/O boundary."""
        self.excluded = True

    async def check(self, evidence: FenceEvidence) -> None:
        """Observe the fence first, ending the epoch on loss; then compare the receipt whole."""
        if not self.valid:
            self._advance()
            raise ValueError("external fence lost")
        if evidence != self.evidence:
            raise ValueError("controller exclusion generation changed")

    async def abandon(self, evidence: FenceEvidence) -> None:
        """End the epoch this receipt names; ignore a receipt that is already stale."""
        if evidence == self.evidence:
            self.abandoned.append(evidence.generation)
            self._advance()

    async def validate(self, transition: ProtocolTransition) -> None:
        """Admit a record only while its fence is the live, intact receipt."""
        await self.check(transition.fence)

    def _advance(self) -> None:
        self.evidence = self.evidence.model_copy(
            update={"generation": self.evidence.generation + 1}
        )


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


async def test_cutover_writes_bound_report_before_record_and_a_second_run_appends(
    tmp_path: Path,
) -> None:
    """An authenticated complete scan leaves writers disabled and appends one immutable record."""
    boundary = DeploymentBoundary()
    cutover = service(tmp_path, boundary)
    record = await cutover.prepare(UUID(int=2))
    report = ProtocolInventory.decode(
        (tmp_path / "protocol/reports/000001.json").read_bytes()
    )
    record.validate_inventory(report)
    assert boundary.excluded
    assert record.fence.generation == 2
    first_record = (tmp_path / "protocol/000001.json").read_bytes()
    assert first_record == record.canonical
    second = await cutover.prepare(UUID(int=2))
    assert second.sequence == 2
    assert second.fence.generation == 3
    assert second.report_path == "reports/000002.json"
    assert (tmp_path / "protocol/reports/000002.json").is_file()
    assert (tmp_path / "protocol/000002.json").is_file()
    assert (tmp_path / "protocol/000001.json").read_bytes() == first_record
    assert boundary.abandoned == []


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
    assert boundary.abandoned == []
    assert boundary.evidence.generation == 1


async def test_controller_evidence_must_match_external_authentication(tmp_path: Path) -> None:
    """A controller cannot substitute a different actor after authentication."""
    boundary = DeploymentBoundary()
    boundary.evidence = boundary.evidence.model_copy(update={"operator": "other"})
    with pytest.raises(ValueError, match="authenticated authority"):
        await service(tmp_path, boundary).prepare(UUID(int=2))
    assert not (tmp_path / "protocol/000001.json").exists()
    assert boundary.abandoned == [2]
    assert not boundary.excluded


async def test_lost_external_fence_prevents_a_report(tmp_path: Path) -> None:
    """No observation can admit a root after its exclusion proof is lost."""
    boundary = DeploymentBoundary()
    boundary.valid = False
    with pytest.raises(ValueError, match="external fence lost"):
        await service(tmp_path, boundary).prepare(UUID(int=2))
    assert not (tmp_path / "protocol/000001.json").exists()
    assert boundary.abandoned == []
    assert boundary.evidence.generation == 3
    assert boundary.excluded


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
        (tmp_path / "protocol/reports/000001.json").read_bytes()
    )
    assert len(report.revisions) == 1
    assert report.revisions[0].path == legacy[1]
    assert report.revisions[0].outcome == "VERIFIED"
    result.validate_inventory(report)


async def test_stranded_report_is_history_and_retry_appends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stranded report becomes permanent history and a retry appends a fresh pair."""
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
    report = tmp_path / "protocol/reports/000001.json"
    assert report.is_file()
    assert not (tmp_path / "protocol/000001.json").exists()
    assert boundary.abandoned == [2]
    before = report.read_bytes()
    retry = await service(tmp_path, boundary).prepare(UUID(int=2))
    assert retry.sequence == 2
    assert retry.fence.generation == 4
    assert report.read_bytes() == before
    assert not (tmp_path / "protocol/000001.json").exists()
    assert (tmp_path / "protocol/000002.json").is_file()


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
    assert boundary.abandoned == []
    assert boundary.evidence.generation == 3


async def test_corrupt_revision_does_not_prevent_exact_healthy_population_certification(
    tmp_path: Path,
    legacy: tuple[object, str, RevisionRecord],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The complete population retains degraded evidence while admitting only healthy members."""
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
        (tmp_path / "protocol/reports/000001.json").read_bytes()
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
    assert not (tmp_path / "protocol/reports/000001.json").exists()
    assert boundary.abandoned == []
    assert boundary.evidence.generation == 3
    boundary.valid = True
    first = await service(tmp_path, boundary).prepare(UUID(int=2))
    assert first.sequence == 1
    assert first.run_id == UUID(int=2)
    assert first.fence.generation == 4
    result = await service(tmp_path, boundary).prepare(UUID(int=4))
    assert result.sequence == 2
    assert result.run_id == UUID(int=4)
    assert result.fence.generation == 5


@pytest.mark.parametrize("destination", ["report", "record"])
async def test_lost_fence_during_installation_retains_unusable_history_and_allows_fresh_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, destination: str
) -> None:
    """Installed bytes remain forensic history until a complete new preparation is admitted."""
    boundary = DeploymentBoundary()
    original = MaintenanceStore.write_evidence
    report = "reports/000001.json"
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
    assert boundary.abandoned == []
    assert boundary.evidence.generation == 3
    boundary.valid = True
    result = await service(tmp_path, boundary).prepare(UUID(int=4))
    assert result.sequence == 2
    assert (tmp_path / "protocol" / selected).read_bytes() == stranded
    third = await service(tmp_path, boundary).prepare(UUID(int=4))
    assert third.sequence == 3
    assert third.fence.generation == result.fence.generation + 1
    assert third != result


@pytest.mark.parametrize("fence_intact", [False, True])
async def test_cancelled_installation_waits_for_its_actual_writer_before_resolving_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fence_intact: bool
) -> None:
    """Cancellation cannot abandon an in-flight write or admit it after its fence is lost."""
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
    assert boundary.abandoned == [2]
    boundary.valid = True
    retry = await service(tmp_path, boundary).prepare(UUID(int=2))
    assert retry.sequence == 2
    assert retry.fence.generation == 4


async def test_failed_directory_sync_leaves_a_complete_record_that_no_epoch_admits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A write that mutates storage then fails cannot let any epoch admit its stranded bytes."""
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
    assert boundary.abandoned == [2]
    record = ProtocolTransition.decode(record_path.read_bytes())
    unchanged = record_path.read_bytes()
    with pytest.raises(ValueError, match="generation changed"):
        await service(tmp_path, boundary).validate(record)
    retry = await service(tmp_path, boundary).prepare(UUID(int=2))
    assert retry.sequence == 2
    assert retry.fence.generation == 4
    assert retry != record
    assert record_path.read_bytes() == unchanged
    await service(tmp_path, boundary).validate(retry)


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
        async def check(self, evidence: FenceEvidence) -> None:
            if entered.is_set() and not observed.is_set():
                observed.set()
                raise ValueError("one observed exclusion loss")
            await super().check(evidence)

    def write(store: MaintenanceStore, path: str, payload: bytes) -> None:
        if path == "000001.json":
            loop.call_soon_threadsafe(entered.set)
            assert released.wait(timeout=5)
        original(store, path, payload)

    monkeypatch.setattr(MaintenanceStore, "write_evidence", write)
    boundary = RecoveringBoundary()
    task = asyncio.create_task(
        service(tmp_path, boundary, check_interval=0.001).prepare(UUID(int=2))
    )
    try:
        await asyncio.wait_for(observed.wait(), 5)
    finally:
        released.set()
    with pytest.raises(ExceptionGroup):
        await task
    assert (tmp_path / "protocol/000001.json").is_file()
    assert boundary.abandoned == [2]
    record = ProtocolTransition.decode((tmp_path / "protocol/000001.json").read_bytes())
    with pytest.raises(ValueError, match="generation changed"):
        await service(tmp_path, boundary).validate(record)


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
    assert boundary.abandoned == []
    assert boundary.evidence.generation == 2
    record = await first
    await service(tmp_path, boundary).validate(record)
    again = await service(tmp_path, boundary).prepare(UUID(int=2))
    assert again.sequence == 2
    assert again.fence.generation == 3
    assert again != record


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
    """A loss observed at the final validation ends the epoch, so the complete record is never admitted."""
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
    assert boundary.abandoned == []
    assert boundary.evidence.generation == 3
    record = ProtocolTransition.decode(record_path.read_bytes())
    boundary.valid = True
    with pytest.raises(ValueError, match="generation changed"):
        await service(tmp_path, boundary).validate(record)


async def test_concurrent_observations_cannot_replace_a_lost_fence_with_recovered_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A queued publication check refuses the monitor's recorded exclusion loss."""
    resolving = asyncio.Event()
    observing = asyncio.Event()
    release = asyncio.Event()

    class ObservationBoundary(DeploymentBoundary):
        async def check(self, evidence: FenceEvidence) -> None:
            if resolving.is_set() and not observing.is_set():
                observing.set()
                await release.wait()
                raise ValueError("observed exclusion loss")
            await super().check(evidence)

    async def resolve(*arguments: object) -> None:
        resolving.set()
        await observing.wait()
        asyncio.get_running_loop().call_soon(release.set)

    monkeypatch.setattr(EmptyCatalog, "resolve", resolve)
    boundary = ObservationBoundary()
    with pytest.raises(ExceptionGroup):
        await asyncio.wait_for(
            service(tmp_path, boundary, check_interval=0.001).prepare(UUID(int=2)), 5
        )
    assert boundary.abandoned == [2]
    assert not (tmp_path / "protocol/000001.json").exists()


async def test_stored_sequence_validation_loads_canonical_evidence_and_checks_live_authority(
    tmp_path: Path,
) -> None:
    """Callers need only a sequence to admit exact stored evidence, never a scan or manual decoding."""
    boundary = DeploymentBoundary()
    cutover = service(tmp_path, boundary)
    record = await cutover.prepare(UUID(int=2))
    assert await cutover.validate_sequence(1) == record
    with pytest.raises(FileNotFoundError):
        await cutover.validate_sequence(2)
    boundary.valid = False
    with pytest.raises(ValueError, match="external fence lost"):
        await cutover.validate_sequence(1)
    boundary.valid = True
    with pytest.raises(ValueError, match="generation changed"):
        await cutover.validate_sequence(1)
    assert (tmp_path / "protocol/000001.json").read_bytes() == record.canonical


@pytest.mark.parametrize("change", ["root", "operation", "actor"])
async def test_stored_sequence_validation_requires_root_operation_and_record_authority(
    tmp_path: Path, change: str
) -> None:
    """Direct stored-sequence operations independently refuse foreign grants and record actors."""
    boundary = DeploymentBoundary()
    cutover = service(tmp_path, boundary)
    await cutover.prepare(UUID(int=2))
    changes = {
        "root": {"root_id": UUID(int=99)},
        "operation": {"operations": frozenset()},
        "actor": {"operator": "other"},
    }
    boundary.grant = boundary.grant.model_copy(update=changes[change])
    with pytest.raises(PermissionError):
        await cutover.validate_sequence(1)
    if change != "actor":
        with pytest.raises(PermissionError):
            await cutover.validate_sequence(2)
    assert boundary.evidence.generation == 2


async def test_stored_sequence_validation_refuses_noncanonical_bytes_without_rewriting_history(
    tmp_path: Path,
) -> None:
    """The complete sequence operation keeps the original canonical-decoding guarantee."""
    boundary = DeploymentBoundary()
    cutover = service(tmp_path, boundary)
    record = await cutover.prepare(UUID(int=2))
    path = tmp_path / "protocol/000001.json"
    path.chmod(0o600)
    malformed = record.canonical + b"\n"
    path.write_bytes(malformed)
    with pytest.raises(ValueError, match="not canonical"):
        await cutover.validate_sequence(1)
    assert boundary.evidence.generation == 2
    assert path.read_bytes() == malformed
