"""Public Integrity operations own epochs and admission independently of local process adapters."""

import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from huron.core.integrity import ControllerAdmission
from huron.core.integrity.models import (
    ControlledRoot,
    ControllerState,
    DeploymentObservation,
    FenceEvidence,
    MaintenanceGrant,
    ProtocolInventory,
    ProtocolTransition,
)

pytestmark = pytest.mark.unit


class ControllerCapabilities:
    """Deterministic external observations, authority, persistence and process effects."""

    def __init__(self) -> None:
        self.identity = DeploymentObservation(
            ControlledRoot(
                root_id=UUID(int=1), path=Path("/data"), owner_uid=1001, device=2, inode=3
            ),
            controller_id=UUID(int=2),
            composition="a" * 64,
        )
        self.grant = MaintenanceGrant(
            root_id=UUID(int=1), operator="operator", operations={"cutover"}
        )
        self.state: ControllerState | None = None
        self.processes: tuple[str, ...] = ()
        self.documents: dict[tuple[str, str], bytes] = {}
        self.events: list[str] = []
        self.faults: dict[str, BaseException] = {}

    def event(self, operation: str) -> None:
        """Record one external effect and inject its configured failure."""
        self.events.append(operation)
        if operation in self.faults:
            raise self.faults[operation]

    def authenticate(self, peer_uid: int) -> MaintenanceGrant:
        """Require an externally recognized peer before returning its current grant."""
        if peer_uid not in (0, 1002):
            raise PermissionError("maintenance grant denied")
        return (
            self.grant if peer_uid == 1002 else self.grant.model_copy(update={"operator": "root"})
        )

    def require_restart(self, peer_uid: int) -> None:
        """Require the distinct deployment restart grant."""
        if peer_uid != 1003:
            raise PermissionError("restart grant denied")

    def load(self) -> ControllerState | None:
        """Return only durably acknowledged authority state."""
        return self.state

    def persist(self, state: ControllerState) -> None:
        """Acknowledge state only when the durable write succeeds."""
        self.event(f"persist:{state.generation}")
        self.state = state

    def observe(self) -> DeploymentObservation:
        """Supply the external deployment and storage observation."""
        self.event("observe")
        return self.identity

    def writers(self) -> tuple[str, ...]:
        """Supply the complete validated external writer population."""
        self.event("writers")
        return self.processes

    def terminate(self, writer: str) -> None:
        """Remove one external process only after the workflow has persisted exclusion."""
        self.event(f"terminate:{writer}")
        assert self.state is not None and self.state.run_id is not None
        self.processes = tuple(item for item in self.processes if item != writer)

    def start(self) -> str:
        """Expose the effect of an admitted fixed application start."""
        self.event("start")
        return "application"

    @asynccontextmanager
    async def database(self) -> AsyncIterator["ControllerCapabilities"]:
        """Inject database acquisition and resource-release failures independently."""
        self.event("database_enter")
        try:
            yield self
        finally:
            self.event("database_exit")

    async def identify(self) -> str:
        """Supply the observed primary database identity."""
        self.event("identify")
        return "1/2/huron"

    async def check(self, fence: FenceEvidence) -> None:
        """Observe database identity and current role exclusion."""
        self.event("database_check")

    @contextmanager
    def claim(self) -> Iterator[None]:
        """Inject failures obtaining and releasing exclusive evidence access."""
        self.event("claim")
        try:
            yield
        finally:
            self.event("release")

    def read_control(self, revision_path: str, name: str) -> bytes:
        """Supply exact stored bytes or distinguish absence from I/O failure."""
        self.event("read")
        try:
            return self.documents[revision_path, name]
        except KeyError as error:
            raise FileNotFoundError(name) from error


def admission(capabilities: ControllerCapabilities) -> ControllerAdmission:
    """Construct the public workflow exclusively from injected capabilities."""
    return ControllerAdmission(
        capabilities,
        capabilities,
        capabilities,
        capabilities,
        capabilities.database,
        identity=capabilities.identity.identity,
        old_roles=("old",),
        new_role="new",
    )


@pytest.fixture
async def prepared() -> tuple[ControllerAdmission, ControllerCapabilities, ProtocolTransition]:
    """Establish a real Integrity epoch with exact report and record bytes supplied externally."""
    capabilities = ControllerCapabilities()
    controller = admission(capabilities)
    fence = await controller.establish(1002, UUID(int=3))
    inventory = ProtocolInventory(
        root_id=fence.root_id, run_id=UUID(int=3), fence=fence, revisions=()
    )
    record = ProtocolTransition.bind(
        inventory, sequence=1, instant=datetime(2026, 1, 1, tzinfo=UTC), code_digest="b" * 64
    )
    capabilities.documents["protocol", "000001.json"] = record.canonical
    capabilities.documents["protocol/reports", "000001.json"] = inventory.canonical
    await controller.validate(1002, record)
    capabilities.events.clear()
    return controller, capabilities, record


async def test_integrity_persists_epoch_before_process_control_and_keeps_restart_excluded() -> None:
    """Public construction advances startup; establish durably excludes before any termination."""
    capabilities = ControllerCapabilities()
    controller = admission(capabilities)
    assert capabilities.state is not None and capabilities.state.generation == 1
    assert controller.restart(1003) == "application"
    capabilities.processes = ("z", "a")
    capabilities.events.clear()
    fence = await controller.establish(1002, UUID(int=3))
    assert fence.terminated_writers == ("a", "z")
    assert capabilities.events.index("identify") < capabilities.events.index("persist:2")
    assert capabilities.events.index("persist:2") < capabilities.events.index("terminate:z")
    assert capabilities.processes == ()
    controller.abandon(1002, fence)
    restarted = admission(capabilities)
    assert capabilities.state.generation == 4
    assert capabilities.state.run_id == UUID(int=3)
    with pytest.raises(ValueError, match="restart is excluded"):
        restarted.restart(1003)
    with pytest.raises(ValueError, match="generation changed"):
        restarted.check(1002, fence)


@pytest.mark.parametrize("change", ["root", "controller", "device", "inode", "composition"])
def test_integrity_refuses_persisted_identity_from_another_deployment(change: str) -> None:
    """No startup epoch can bind persisted authority to a different deployment or storage root."""
    capabilities = ControllerCapabilities()
    admission(capabilities)
    assert capabilities.state is not None
    field = {"root": "root_id", "controller": "controller_id"}.get(change, change)
    value = (
        UUID(int=99)
        if change in {"root", "controller"}
        else "changed"
        if change == "composition"
        else 99
    )
    capabilities.state = capabilities.state.model_copy(update={field: value})
    with pytest.raises(ValueError, match="identity changed"):
        admission(capabilities)
    assert capabilities.state.generation == 1


@pytest.mark.parametrize(
    "fault",
    [
        "observe",
        "writers",
        "claim",
        "read",
        "release",
        "database_enter",
        "database_check",
        "database_exit",
    ],
)
@pytest.mark.parametrize("error_type", [OSError, asyncio.CancelledError])
async def test_integrity_ends_epoch_on_every_failed_live_observation(
    prepared: tuple[ControllerAdmission, ControllerCapabilities, ProtocolTransition],
    fault: str,
    error_type: type[BaseException],
) -> None:
    """Both ordinary failure and cancellation invalidate durably before propagating unchanged."""
    controller, capabilities, record = prepared
    error = error_type("injected live observation failure")
    capabilities.faults[fault] = error
    with pytest.raises(error_type) as caught:
        await controller.validate(1002, record)
    assert caught.value is error
    assert capabilities.state is not None
    assert capabilities.state.generation == record.fence.generation + 1
    capabilities.faults.clear()
    with pytest.raises(ValueError, match="generation changed"):
        await controller.validate(1002, record)


async def test_failed_persistence_still_ends_the_in_memory_epoch(
    prepared: tuple[ControllerAdmission, ControllerCapabilities, ProtocolTransition],
) -> None:
    """Failure before disk replacement cannot let this process admit the old receipt again."""
    controller, capabilities, record = prepared
    capabilities.faults[f"persist:{record.fence.generation + 1}"] = OSError("state write failed")
    with pytest.raises(OSError, match="state write failed"):
        controller.abandon(1002, record.fence)
    assert capabilities.state is not None
    assert capabilities.state.generation == record.fence.generation
    capabilities.faults.clear()
    with pytest.raises(ValueError, match="generation changed"):
        await controller.validate(1002, record)
    controller.abandon(1002, record.fence)
    assert capabilities.state.generation == record.fence.generation
    with pytest.raises(ValueError, match="restart is excluded"):
        controller.restart(1003)
    new = await controller.establish(1002, record.run_id)
    assert new.generation == record.fence.generation + 2


@pytest.mark.parametrize("point", ["identify", "terminate:writer"])
async def test_establish_cancellation_invalidates_before_it_propagates(point: str) -> None:
    """Cancellation while identifying or terminating cannot leave the attempted epoch live."""
    capabilities = ControllerCapabilities()
    controller = admission(capabilities)
    capabilities.processes = ("writer",)
    capabilities.faults[point] = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await controller.establish(1002, UUID(int=3))
    assert capabilities.state is not None
    assert capabilities.state.generation == (2 if point == "identify" else 3)
    if point == "terminate:writer":
        with pytest.raises(ValueError, match="restart is excluded"):
            controller.restart(1003)


@pytest.mark.parametrize(
    "change",
    ["peer", "root", "operation", "operator", "run", "fence", "record", "report", "absent"],
)
async def test_bad_arguments_never_invalidate_a_valid_epoch(
    prepared: tuple[ControllerAdmission, ControllerCapabilities, ProtocolTransition], change: str
) -> None:
    """Authority and receipt mismatches refuse the request while preserving another valid attempt."""
    controller, capabilities, record = prepared
    grant = capabilities.grant
    documents = dict(capabilities.documents)
    peer, presented = 1002, record
    if change == "peer":
        peer = 1003
    elif change == "root":
        capabilities.grant = grant.model_copy(update={"root_id": UUID(int=99)})
    elif change == "operation":
        capabilities.grant = grant.model_copy(update={"operations": frozenset()})
    elif change == "operator":
        peer = 0
    elif change == "run":
        presented = record.model_copy(update={"run_id": UUID(int=99)})
    elif change == "fence":
        presented = record.model_copy(
            update={"fence": record.fence.model_copy(update={"generation": 99})}
        )
    elif change == "record":
        presented = record.model_copy(update={"code_digest": "c" * 64})
    elif change == "report":
        capabilities.documents["protocol/reports", "000001.json"] = b"{}"
    else:
        del capabilities.documents["protocol/reports", "000001.json"]
    with pytest.raises((PermissionError, ValueError)):
        await controller.validate(peer, presented)
    assert capabilities.state is not None
    assert capabilities.state.generation == record.fence.generation
    capabilities.grant = grant
    capabilities.documents = documents
    await controller.validate(1002, record)


def test_restart_requires_its_own_authority_and_invalidates_failed_process_start() -> None:
    """Maintenance authority never implies restart authority; admitted start failures end the epoch."""
    capabilities = ControllerCapabilities()
    controller = admission(capabilities)
    capabilities.events.clear()
    with pytest.raises(PermissionError, match="restart grant"):
        controller.restart(1002)
    assert capabilities.events == []
    capabilities.faults["start"] = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        controller.restart(1003)
    assert capabilities.state is not None and capabilities.state.generation == 2


async def test_evidence_admission_rechecks_the_fence_after_database_observation(
    prepared: tuple[ControllerAdmission, ControllerCapabilities, ProtocolTransition],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A writer appearing during the database check is refused and ends the epoch."""
    controller, capabilities, record = prepared

    async def escaped(fence: FenceEvidence) -> None:
        capabilities.processes = ("new-writer",)

    monkeypatch.setattr(capabilities, "check", escaped)
    with pytest.raises(ValueError, match="foreign writer"):
        await controller.validate(1002, record)
    assert capabilities.state is not None
    assert capabilities.state.generation == record.fence.generation + 1


def test_controller_state_retains_the_exact_persisted_json_and_legacy_defaults() -> None:
    """Relocated state accepts the same minimal documents and emits the same complete JSON fields."""
    minimal = (
        b'{"root_id":"00000000-0000-0000-0000-000000000001",'
        b'"controller_id":"00000000-0000-0000-0000-000000000002",'
        b'"device":2,"inode":3,"composition":"deployment","generation":0}'
    )
    expected = minimal[:-1] + b',"run_id":null,"writers":[],"operator":null,"database":null}'
    state = ControllerState.model_validate_json(minimal)
    assert state.model_dump_json().encode() == expected
    assert ControllerState.model_validate_json(expected) == state
    with pytest.raises(ValueError, match="greater than or equal to 0"):
        ControllerState.model_validate_json(minimal.replace(b'"generation":0', b'"generation":-1'))
    with pytest.raises(ValueError, match="Extra inputs"):
        ControllerState.model_validate_json(minimal[:-1] + b',"certified_sha256":"forbidden"}')
    with pytest.raises(ValueError, match="frozen"):
        state.generation = 2
