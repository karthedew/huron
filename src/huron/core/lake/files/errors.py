"""Commit errors."""

from __future__ import annotations

from huron.pkg.errors import HuronError, register

__all__ = ["BaseVersionConflict", "CommitInvalid", "CommitTooLarge", "FileNotRecorded"]

COMMIT_INVALID = register("COMMIT_INVALID", 422, "Commit invalid")
FILE_NOT_RECORDED = register("FILE_NOT_RECORDED", 422, "File not recorded")
COMMIT_TOO_LARGE = register("COMMIT_TOO_LARGE", 413, "Commit too large")
BASE_VERSION_CONFLICT = register("BASE_VERSION_CONFLICT", 409, "Base version conflict")


class CommitInvalid(HuronError):
    """The commit request is malformed."""

    error_code = COMMIT_INVALID


class FileNotRecorded(HuronError):
    """A commit removes a file that is not recorded."""

    error_code = FILE_NOT_RECORDED


class CommitTooLarge(HuronError):
    """The commit names more entries than one commit may hold."""

    error_code = COMMIT_TOO_LARGE


class BaseVersionConflict(HuronError):
    """The commit was prepared against an older version of the collection."""

    error_code = BASE_VERSION_CONFLICT

    def __init__(self, current_version: int, base_version: int) -> None:
        super().__init__(
            f"the collection is at version {current_version}, not {base_version}; pull first",
            {"current_version": current_version, "base_version": base_version},
        )
        self.current_version = current_version
