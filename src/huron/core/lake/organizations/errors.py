"""Organization errors."""

from __future__ import annotations

from huron.pkg.errors import HuronError, register

__all__ = ["OrganizationNotEmpty"]

ORGANIZATION_NOT_EMPTY = register("ORGANIZATION_NOT_EMPTY", 409, "Organization not empty")


class OrganizationNotEmpty(HuronError):
    """The organization still has catalogs."""

    error_code = ORGANIZATION_NOT_EMPTY
