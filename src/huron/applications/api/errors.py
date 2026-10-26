"""Failures owned by HTTP parsing."""

from huron.core.foundation.errors import DomainError


class InvalidCursor(DomainError):
    """The supplied cursor is not a keyset position this service issued."""

    code, status_code = "INVALID_CURSOR", 400


ERROR_CODES = frozenset({"INVALID_CURSOR"})
