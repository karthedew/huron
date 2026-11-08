"""Storage errors."""

from __future__ import annotations

from typing import TYPE_CHECKING

from huron.pkg.errors import HuronError, register

if TYPE_CHECKING:
    from huron.core.storage.lakepath import LakePath

__all__ = ["InheritanceFailed", "LakeUnavailable", "SourceGone", "StorageError", "SymlinkInLake"]

STORAGE_FAILED = register("STORAGE_FAILED", 500, "Storage failed")
SYMLINK_IN_LAKE = register("SYMLINK_IN_LAKE", 409, "Symbolic link in the lake")
LAKE_UNAVAILABLE = register("LAKE_UNAVAILABLE", 503, "Lake unavailable")


class StorageError(HuronError):
    """The share could not be used: missing, unmarked or unwritable."""

    error_code = STORAGE_FAILED


class SymlinkInLake(StorageError):
    """A name on the way to a place on the lake, or the place itself, is a symbolic link.

    Nothing was changed, and the link stays: the storage administrator removes it.
    """

    error_code = SYMLINK_IN_LAKE

    def __init__(self, link: LakePath) -> None:
        super().__init__(
            f"{link} is a symbolic link. The lake must not contain symbolic links. Remove it.",
            {"path": str(link)},
        )


class InheritanceFailed(StorageError):
    """A new directory did not inherit the setgid bit and the group of its parent.

    The directory was removed again. Only the storage administrator can fix the parent.
    """

    def __init__(self, location: LakePath, reason: str) -> None:
        super().__init__(f"{location}: {reason}", {"path": str(location)})


class LakeUnavailable(StorageError):
    """The lake is not mounted, or its marker refuses the write."""

    error_code = LAKE_UNAVAILABLE


class SourceGone(StorageError):
    """The upload's file is gone from ``.tus-uploads`` or is not the measured file any more.

    Another attempt may have placed it.
    """

    def __init__(self, source: LakePath) -> None:
        super().__init__(f"the upload file {source} does not exist", {"path": str(source)})
