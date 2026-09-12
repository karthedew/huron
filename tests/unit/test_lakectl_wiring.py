"""Operator wiring uses authenticated storage and closes dedicated database resources."""

from pathlib import Path
from types import SimpleNamespace, TracebackType
from uuid import UUID

import pytest

from huron.applications.lakectl import wiring
from huron.applications.lakectl.settings import ControlledRoot, MaintenanceSettings
from huron.core.integrity.models import FenceEvidence, MaintenanceGrant, ProtocolTransition
from tests.unit.test_controller_settings import root_metadata as root_metadata

pytestmark = pytest.mark.unit


class EmptyDatabaseBoundary:
    """Supply an empty schema-0010 database through its external SQL boundary."""

    def __init__(self) -> None:
        self.closed = False

    def acquire(self) -> "EmptyDatabaseBoundary":
        """Acquire the same disposable connection boundary."""
        return self

    def transaction(self) -> "EmptyDatabaseBoundary":
        """Enter an independently tested database transaction boundary."""
        return self

    async def __aenter__(self) -> "EmptyDatabaseBoundary":
        return self

    async def __aexit__(
        self,
        kind: type[BaseException] | None,
        value: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        self.closed = True

    async def fetchval(self, query: str, *arguments: object) -> object:
        """Report dedicated roles and the exact supported schema, with no effective access."""
        if "version_num" in query:
            return "0010_independent_raw"
        return "SELECT NOT (rolsuper" in query

    async def fetch(self, query: str, *arguments: object) -> list[object]:
        """Supply an empty hierarchy, no sessions and no prior effective grants."""
        return []

    async def execute(self, query: str, *arguments: object) -> str:
        """Accept role disabling at the external connection boundary."""
        return "ALTER ROLE"


class ControllerBoundary:
    """Supply authenticated controller observations without substituting core workflow behavior."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.wrong_inode = False

    async def describe(self) -> ControlledRoot:
        """Supply the real local directory's identity from the controller boundary."""
        info = self.root.stat()
        return ControlledRoot(
            root_id=UUID(int=1),
            path=self.root,
            owner_uid=1001,
            device=info.st_dev,
            inode=info.st_ino + int(self.wrong_inode),
        )

    async def authenticate(self) -> MaintenanceGrant:
        """Supply a root-scoped grant issued by the independent authentication boundary."""
        return MaintenanceGrant(root_id=UUID(int=1), operator="local:0", operations={"cutover"})

    async def establish(self, grant: MaintenanceGrant, run_id: UUID) -> FenceEvidence:
        """Supply the external fence for the authenticated operator."""
        return FenceEvidence(
            root_id=grant.root_id,
            controller_id=UUID(int=2),
            generation=1,
            operator=grant.operator,
            terminated_writers=(),
            old_roles=("old_app",),
            new_role="new_app",
        )

    async def check(self, evidence: FenceEvidence) -> None:
        """Keep the independently enforced boundary valid for this deterministic scenario."""

    async def certify(self, transition: ProtocolTransition) -> None:
        """Acknowledge the external controller's endorsement."""

    async def validate_certificate(self, transition: ProtocolTransition) -> None:
        """Accept the deterministic controller's live certificate."""


async def test_wiring_runs_actual_core_and_adapters_with_dedicated_pool_lifetime(
    tmp_path: Path,
    root_metadata: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Authenticated local storage reaches the full coordinator and publishes its bound receipt."""
    monkeypatch.setattr(wiring, "sys", SimpleNamespace(platform="linux"))
    controller = ControllerBoundary(tmp_path)
    database = EmptyDatabaseBoundary()
    monkeypatch.setattr(wiring, "ControllerClient", lambda socket: controller)
    monkeypatch.setattr(wiring.asyncpg, "create_pool", lambda url: database)
    settings = MaintenanceSettings(
        controller_socket=tmp_path / "controller.sock", database_url="secret"
    )
    receipt = await wiring.prepare(settings, UUID(int=3))
    assert receipt.root_id == UUID(int=1)
    assert len(receipt.code_digest) == 64
    assert receipt.instant.utcoffset().total_seconds() == 0
    assert database.closed
    assert (tmp_path / "protocol/000001.json").read_bytes() == receipt.canonical


async def test_wiring_refuses_unsupported_namespace_and_controller_inode_mismatch(
    tmp_path: Path,
    root_metadata: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Maintenance cannot scan a host path that disagrees with authenticated Linux storage."""
    settings = MaintenanceSettings(
        controller_socket=tmp_path / "controller.sock", database_url="secret"
    )
    monkeypatch.setattr(wiring, "sys", SimpleNamespace(platform="darwin"))
    with pytest.raises(ValueError, match="actual local Linux"):
        await wiring.prepare(settings, UUID(int=3))
    monkeypatch.setattr(wiring, "sys", SimpleNamespace(platform="linux"))
    controller = ControllerBoundary(tmp_path)
    controller.wrong_inode = True
    monkeypatch.setattr(wiring, "ControllerClient", lambda socket: controller)
    with pytest.raises(ValueError, match="differs from authenticated"):
        await wiring.prepare(settings, UUID(int=3))
    assert not (tmp_path / "protocol").exists()
