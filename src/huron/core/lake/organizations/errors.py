"""Organization errors."""

from __future__ import annotations

from huron.pkg.errors import HuronError, Invalid, register

__all__ = [
    "DeclarationInvalid",
    "OrganizationDeclared",
    "OrganizationNotEmpty",
    "OrganizationsManaged",
]

ORGANIZATION_NOT_EMPTY = register("ORGANIZATION_NOT_EMPTY", 409, "Organization not empty")
ORGANIZATIONS_MANAGED = register("ORGANIZATIONS_MANAGED", 409, "Organizations are managed")
ORGANIZATION_DECLARED = register("ORGANIZATION_DECLARED", 409, "Organization declared")


class OrganizationNotEmpty(HuronError):
    """The organization still has catalogs."""

    error_code = ORGANIZATION_NOT_EMPTY


class OrganizationsManaged(HuronError):
    """The service configuration declares the organizations, so the API cannot create one."""

    error_code = ORGANIZATIONS_MANAGED


class OrganizationDeclared(HuronError):
    """The organization is declared in the configuration: it cannot be deleted or regranted."""

    error_code = ORGANIZATION_DECLARED


class DeclarationInvalid(Invalid):
    """The configuration declares organizations that break a rule."""
