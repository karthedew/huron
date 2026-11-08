"""Storage errors."""

from __future__ import annotations

from typing import TYPE_CHECKING

from huron.pkg.errors import HuronError, register

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["LakeUnavailable", "OutsideLake", "SourceGone", "StorageError"]

STORAGE_FAILED = register("STORAGE_FAILED", 500, "Storage failed")
OUTSIDE_LAKE = register("OUTSIDE_LAKE", 422, "Outside the lake")
LAKE_UNAVAILABLE = register("LAKE_UNAVAILABLE", 503, "Lake unavailable")


class StorageError(HuronError):
    """The share could not be used: missing, unmarked or unwritable."""

    error_code = STORAGE_FAILED


class OutsideLake(StorageError):
    """A path resolves outside the lake path, or onto another filesystem below it."""

    error_code = OUTSIDE_LAKE


class LakeUnavailable(StorageError):
    """The lake is not mounted, or its marker refuses the write."""

    error_code = LAKE_UNAVAILABLE


class SourceGone(StorageError):
    """The upload's file is no longer in ``.tus-uploads``: another attempt may have placed it."""

    def __init__(self, source: Path) -> None:
        super().__init__(f"the upload file {source} does not exist", {"path": str(source)})
