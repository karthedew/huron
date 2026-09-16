"""Failures owned by HTTP parsing and deployment readiness."""

from huron.core.foundation.errors import DomainError


class InvalidCursor(DomainError):
    """The supplied cursor is not a keyset position this service issued."""

    code, status_code = "INVALID_CURSOR", 400


class DependencyUnavailable(DomainError):
    """A dependency probed by readiness did not answer."""

    code, status_code = "DEPENDENCY_UNAVAILABLE", 503


ERROR_CODES = frozenset({"INVALID_CURSOR", "DEPENDENCY_UNAVAILABLE"})
