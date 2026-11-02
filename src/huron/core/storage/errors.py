"""Storage errors."""

from __future__ import annotations

from huron.pkg.errors import HuronError, register

__all__ = ["StorageError"]

STORAGE_FAILED = register("STORAGE_FAILED", 500, "Storage failed")


class StorageError(HuronError):
    """The share could not be used: missing, unmarked, unwritable, or an ACL failed."""

    error_code = STORAGE_FAILED
