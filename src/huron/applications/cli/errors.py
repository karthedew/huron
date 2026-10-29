"""Exit codes and the errors the CLI reports."""

from __future__ import annotations

from enum import IntEnum
from typing import Any

__all__ = [
    "ApiError",
    "CliError",
    "ExitCode",
    "NotLoggedIn",
    "StorageFailure",
    "UsageError",
    "exit_code_for",
]


class ExitCode(IntEnum):
    """Process exit codes, documented in the user guide."""

    OK = 0
    FAILED = 1
    USAGE = 2
    NOT_LOGGED_IN = 3
    FORBIDDEN = 4
    NOT_FOUND = 5
    CONFLICT = 6
    VALIDATION = 7
    STORAGE = 8
    INTERRUPTED = 130


class CliError(Exception):
    """An error the CLI prints as ``error: <message> [<code>]`` with an optional hint."""

    def __init__(
        self,
        message: str,
        exit_code: ExitCode = ExitCode.FAILED,
        *,
        hint: str | None = None,
        code: str | None = None,
        problem: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code
        self.hint = hint
        self.code = code
        self.problem = problem


class UsageError(CliError):
    """The command line was not usable."""

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message, ExitCode.USAGE, hint=hint)


class NotLoggedIn(CliError):
    """No usable Huron token."""

    def __init__(self, message: str = "you are not logged in") -> None:
        super().__init__(message, ExitCode.NOT_LOGGED_IN, hint="run: huron login")


class StorageFailure(CliError):
    """The share could not be used."""

    def __init__(self, message: str, *, hint: str | None = None, code: str | None = None) -> None:
        super().__init__(message, ExitCode.STORAGE, hint=hint, code=code)


class ApiError(CliError):
    """A problem document returned by the API."""

    @classmethod
    def from_problem(cls, status: int, document: dict[str, Any]) -> ApiError:
        """Build from an RFC 9457 document."""
        code = str(document.get("code", "HTTP"))
        message = str(document.get("detail") or document.get("title") or f"HTTP {status}")
        hint = _HINTS.get(code)
        return cls(message, exit_code_for(code, status), hint=hint, code=code, problem=document)


def exit_code_for(code: str, status: int) -> ExitCode:
    """The exit code for an API error code."""
    exact = _EXACT.get(code)
    if exact is not None:
        return exact
    if code.endswith(("_NOT_EMPTY", "_CONFLICT")):
        return ExitCode.CONFLICT
    if code.startswith("SCHEMA_") or code.endswith("_INVALID"):
        return ExitCode.VALIDATION
    return ExitCode.FAILED


_EXACT = {
    "UNAUTHENTICATED": ExitCode.NOT_LOGGED_IN,
    "TOKEN_INVALID": ExitCode.NOT_LOGGED_IN,
    "FORBIDDEN": ExitCode.FORBIDDEN,
    "NOT_FOUND": ExitCode.NOT_FOUND,
    "STORAGE_FAILED": ExitCode.STORAGE,
    "ACL_FAILED": ExitCode.STORAGE,
    "NAME_TAKEN": ExitCode.CONFLICT,
    "COLLECTIONS_NOT_ALLOWED": ExitCode.CONFLICT,
    "PRECONDITION_REQUIRED": ExitCode.CONFLICT,
    "FILE_NOT_RECORDED": ExitCode.VALIDATION,
    "COMMIT_TOO_LARGE": ExitCode.VALIDATION,
}
_HINTS = {
    "BASE_VERSION_CONFLICT": "run: huron pull",
    "VERSION_CONFLICT": "run: huron pull",
    "UNAUTHENTICATED": "run: huron login",
    "TOKEN_INVALID": "run: huron login",
}
