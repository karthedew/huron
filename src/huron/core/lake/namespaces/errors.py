"""Namespace errors."""

from __future__ import annotations

from huron.pkg.errors import HuronError, register

__all__ = ["NamespaceNotEmpty"]

NAMESPACE_NOT_EMPTY = register("NAMESPACE_NOT_EMPTY", 409, "Namespace not empty")


class NamespaceNotEmpty(HuronError):
    """The namespace still has child namespaces or collections."""

    error_code = NAMESPACE_NOT_EMPTY
