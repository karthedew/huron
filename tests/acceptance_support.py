"""Capacity prerequisites for the full-size upload acceptance workload."""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

MINIMUM_FREE_BYTES = 25 * 1024**3


def require_upload_capacity(path: Path) -> None:
    """Refuse a full-size upload when its filesystem lacks 25 GiB of free capacity.

    The sparse source consumes negligible blocks, while upload and completion
    coexist at 18 GiB. The remaining 7 GiB covers the configured 1 GiB reserve
    and filesystem overhead or other local consumers; this is no reservation
    against concurrent writers.

    Args:
        path: Existing directory on the filesystem that will hold the test data.

    Raises:
        RuntimeError: If available capacity is below the prerequisite.
    """
    free = shutil.disk_usage(path).free
    if free < MINIMUM_FREE_BYTES:
        raise RuntimeError(
            f"upload acceptance requires at least {MINIMUM_FREE_BYTES} free bytes "
            f"(25 GiB) at {path}; available: {free}"
        )
