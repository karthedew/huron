"""Construct preparatory cutover from authenticated local deployment capabilities."""

from __future__ import annotations

import hashlib
import sys
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

import asyncpg

from huron.core.integrity import CutoverService
from huron.core.metastore.legacy import PostgresLegacyMaintenance
from huron.core.metastore.maintenance import PostgresRoleExclusion
from huron.core.rawstore.maintenance import MaintenanceStore

from .engine import require_local_administrator
from .exclusion import ControllerClient

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from .settings import MaintenanceSettings


@asynccontextmanager
async def deployment(
    settings: MaintenanceSettings,
) -> AsyncIterator[CutoverService]:
    """Own the authenticated local deployment resources for a complete cutover operation.

    Args:
        settings: Private dedicated maintenance credentials and controller endpoint.

    Yields:
        Integrity operations bound to the controller's actual local storage namespace.

    Raises:
        ValueError: If the local Linux storage namespace differs from the controller's root.
    """
    require_local_administrator()
    if sys.platform != "linux":
        raise ValueError("cutover requires the controller's actual local Linux namespace")
    controller = ControllerClient(settings.controller_socket)
    root = await controller.describe()
    info = root.path.lstat()
    if (info.st_dev, info.st_ino) != (root.device, root.inode):
        raise ValueError("local inspection root differs from authenticated controller storage")
    store = MaintenanceStore(root.path, root.owner_uid)
    async with asyncpg.create_pool(settings.database_url.get_secret_value()) as pool:
        service = CutoverService(
            controller,
            controller,
            PostgresRoleExclusion(pool),
            PostgresLegacyMaintenance(pool, _now),
            store,
            root_id=root.root_id,
            catalog_root=PurePosixPath("/data"),
            code_digest=_implementation_digest(),
            now=_now,
        )
        yield service


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
