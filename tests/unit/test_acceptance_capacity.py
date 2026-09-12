"""Full-size acceptance refuses undersized disks before opening an upload."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from tests.acceptance_support import MINIMUM_FREE_BYTES, require_upload_capacity

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("free", [0, MINIMUM_FREE_BYTES - 1])
def test_upload_capacity_refuses_insufficient_free_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, free: int
) -> None:
    """Empty and just-undersized filesystems fail rather than skip or shrink the upload."""
    monkeypatch.setattr(
        "tests.acceptance_support.shutil.disk_usage", lambda path: SimpleNamespace(free=free)
    )
    with pytest.raises(RuntimeError, match="25 GiB"):
        require_upload_capacity(tmp_path)


@pytest.mark.parametrize("free", [MINIMUM_FREE_BYTES, MINIMUM_FREE_BYTES + 1])
def test_upload_capacity_accepts_the_exact_boundary_and_larger_disks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, free: int
) -> None:
    """Exactly the documented minimum and additional capacity admit the full workload."""
    monkeypatch.setattr(
        "tests.acceptance_support.shutil.disk_usage", lambda path: SimpleNamespace(free=free)
    )
    require_upload_capacity(tmp_path)


def test_upload_capacity_propagates_unavailable_filesystem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed capacity observation cannot authorize an acceptance upload."""

    def unavailable(path: Path) -> None:
        raise OSError("filesystem unavailable")

    monkeypatch.setattr("tests.acceptance_support.shutil.disk_usage", unavailable)
    with pytest.raises(OSError, match="filesystem unavailable"):
        require_upload_capacity(tmp_path)
