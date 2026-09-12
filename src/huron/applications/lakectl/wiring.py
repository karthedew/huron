"""Construct preparatory cutover from authenticated local deployment capabilities."""

from __future__ import annotations

import hashlib
import sys
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

import asyncpg

from huron.core.integrity.cutover import CutoverService
from huron.pkg.metastore.legacy import PostgresLegacyMaintenance
from huron.pkg.metastore.maintenance import PostgresRoleExclusion
from huron.pkg.rawstore.maintenance import MaintenanceStore

from .engine import require_local_administrator
from .exclusion import ControllerClient

if TYPE_CHECKING:
    from uuid import UUID

    from huron.core.integrity.models import ProtocolTransition

    from .settings import MaintenanceSettings


async def prepare(settings: MaintenanceSettings, run_id: UUID) -> ProtocolTransition:
    """Run verification against the controller's actual Linux storage namespace.

    Args:
        settings: Private dedicated maintenance credentials and controller endpoint.
        run_id: Stable retry identity for this verification attempt.

    Returns:
        Durable transition receipt, with application identities still excluded.

    Raises:
        ValueError: If the local storage namespace disagrees with controller evidence.
    """
    require_local_administrator()
    if sys.platform != "linux":
        raise ValueError("cutover requires the controller's actual local Linux namespace")
    controller = ControllerClient(settings.controller_socket)
    root = await controller.describe()
    info = root.path.lstat()
    if (info.st_dev, info.st_ino) != (root.device, root.inode):
        raise ValueError("local inspection root differs from authenticated controller storage")
    async with asyncpg.create_pool(settings.database_url.get_secret_value()) as pool:
        service = CutoverService(
            controller,
            controller,
            PostgresRoleExclusion(pool),
            PostgresLegacyMaintenance(pool, _now),
            MaintenanceStore(root.path, root.owner_uid),
            root_id=root.root_id,
            catalog_root=PurePosixPath("/data"),
            code_digest=_implementation_digest(),
            now=_now,
        )
        return await service.prepare(run_id)


def _now() -> datetime:
    return datetime.now(UTC)


def _implementation_digest() -> str:
    root = Path(__file__).parents[2]
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        name = path.relative_to(root).as_posix().encode()
        payload = path.read_bytes()
        digest.update(len(name).to_bytes(8, "big") + name)
        digest.update(len(payload).to_bytes(8, "big") + payload)
    return digest.hexdigest()
