"""Storage errors."""

from __future__ import annotations

from huron.pkg.errors import HuronError, register

__all__ = ["LakeUnavailable", "OutsideLake", "StorageError"]

STORAGE_FAILED = register("STORAGE_FAILED", 500, "Storage failed")
OUTSIDE_LAKE = register("OUTSIDE_LAKE", 422, "Outside the lake")
LAKE_UNAVAILABLE = register("LAKE_UNAVAILABLE", 503, "Lake unavailable")


class StorageError(HuronError):
    """The share could not be used: missing, unmarked, unwritable, or an ACL failed."""

    error_code = STORAGE_FAILED


class OutsideLake(StorageError):
    """A path resolves outside the lake path, or onto another filesystem below it."""

    error_code = OUTSIDE_LAKE


class LakeUnavailable(StorageError):
    """The lake is not mounted, or its marker refuses the write."""

    error_code = LAKE_UNAVAILABLE
