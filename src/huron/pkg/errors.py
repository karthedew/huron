"""Error codes and the base error type rendered as RFC 9457 problem documents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

__all__ = [
    "DEPENDENCY_UNAVAILABLE",
    "FORBIDDEN",
    "INTERNAL",
    "NOT_FOUND",
    "REQUEST_INVALID",
    "STATE_CONFLICT",
    "UNAUTHENTICATED",
    "Conflict",
    "ErrorCode",
    "ErrorCodes",
    "Forbidden",
    "HuronError",
    "Invalid",
    "NotFound",
    "Unauthenticated",
    "Unavailable",
    "error_codes",
    "register",
]

PROBLEM_TYPE_PREFIX = "https://huron.dev/problems/"


@dataclass(frozen=True, slots=True)
class ErrorCode:
    """A stable, documented error identifier with its HTTP status."""

    code: str
    status: int
    title: str


class ErrorCodes:
    """A registry of error codes that refuses duplicates."""

    def __init__(self) -> None:
        self._codes: dict[str, ErrorCode] = {}

    def register(self, code: str, status: int, title: str) -> ErrorCode:
        """Register a new code; registering an existing code raises ``ValueError``."""
        if code in self._codes:
            raise ValueError(f"error code {code!r} is already registered")
        entry = ErrorCode(code, status, title)
        self._codes[code] = entry
        return entry

    def get(self, code: str) -> ErrorCode:
        """Return a registered code; raises ``KeyError`` when unknown."""
        return self._codes[code]

    def all(self) -> list[ErrorCode]:
        """Return every registered code sorted by name."""
        return sorted(self._codes.values(), key=lambda entry: entry.code)

    def __iter__(self) -> Iterator[ErrorCode]:
        return iter(self.all())

    def __contains__(self, code: object) -> bool:
        return code in self._codes


def error_codes() -> ErrorCodes:
    """Return the process-wide registry shared by the API and the CLI."""
    return _REGISTRY


def register(code: str, status: int, title: str) -> ErrorCode:
    """Register ``code`` in the shared registry."""
    return _REGISTRY.register(code, status, title)


class HuronError(Exception):
    """Base class of every error Huron reports to a user.

    Subclasses bind ``error_code``; ``context`` carries machine-readable detail.
    """

    error_code: ClassVar[ErrorCode]

    def __init__(self, message: str, context: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.context: dict[str, Any] = dict(context or {})

    @property
    def code(self) -> str:
        """The stable error code."""
        return self.error_code.code

    @property
    def status(self) -> int:
        """The HTTP status of the error."""
        return self.error_code.status

    def problem(self, instance: str | None = None) -> dict[str, Any]:
        """Render the error as an RFC 9457 problem document."""
        document: dict[str, Any] = {
            "type": PROBLEM_TYPE_PREFIX + self.code.lower().replace("_", "-"),
            "title": self.error_code.title,
            "status": self.status,
            "detail": self.message,
            "code": self.code,
            "context": self.context,
        }
        if instance is not None:
            document["instance"] = instance
        return document


_REGISTRY = ErrorCodes()

INTERNAL = register("INTERNAL", 500, "Internal error")
UNAUTHENTICATED = register("UNAUTHENTICATED", 401, "Authentication required")
FORBIDDEN = register("FORBIDDEN", 403, "Forbidden")
NOT_FOUND = register("NOT_FOUND", 404, "Not found")
STATE_CONFLICT = register("STATE_CONFLICT", 409, "State conflict")
REQUEST_INVALID = register("REQUEST_INVALID", 422, "Request invalid")
DEPENDENCY_UNAVAILABLE = register("DEPENDENCY_UNAVAILABLE", 503, "Dependency unavailable")


class Unauthenticated(HuronError):
    """No valid credentials were presented."""

    error_code = UNAUTHENTICATED


class Forbidden(HuronError):
    """The actor lacks the privilege the operation needs."""

    error_code = FORBIDDEN


class NotFound(HuronError):
    """The object does not exist or is not visible to the actor."""

    error_code = NOT_FOUND


class Conflict(HuronError):
    """The object is in a state that does not allow the operation."""

    error_code = STATE_CONFLICT


class Invalid(HuronError):
    """The request is well formed but its content is not acceptable."""

    error_code = REQUEST_INVALID


class Unavailable(HuronError):
    """A dependency the operation needs is not reachable."""

    error_code = DEPENDENCY_UNAVAILABLE
