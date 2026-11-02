"""Errors shared by every area of the lake."""

from __future__ import annotations

from huron.pkg.errors import HuronError, register

__all__ = ["NameTaken", "VersionConflict"]

NAME_TAKEN = register("NAME_TAKEN", 409, "Name taken")
VERSION_CONFLICT = register("VERSION_CONFLICT", 412, "Version conflict")


class NameTaken(HuronError):
    """Another object already uses the name where names must be unique."""

    error_code = NAME_TAKEN


class VersionConflict(HuronError):
    """The caller's expected version is not the current one; ``current_version`` says which is."""

    error_code = VERSION_CONFLICT

    def __init__(self, current_version: int) -> None:
        super().__init__(
            f"the current version is {current_version}", {"current_version": current_version}
        )
        self.current_version = current_version
