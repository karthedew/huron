"""The dependencies a route declares.

Holding a ``Principal`` returned by a ``require_*`` dependency is proof the
capability check passed.
Every factory returns a **new** closure per call, so a capability declared
both on a router and as a parameter must share one bound closure or the
check runs twice; routes never re-check permissions.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated
from uuid import UUID

from fastapi import Path

from huron.core.security.principal import Principal
from huron.core.security.rules import Scope, ScopeType
from huron.core.security.scopes import resource_scope

from ..runtime import Bindings, Hierarchy
from .credentials import CurrentPrincipal
from .decisions import BindingCache, CurrentVisibility, check


def require_system(capability: str) -> Callable[..., Awaitable[Principal]]:
    """Guard a platform-scope route (e.g. ``organization.create``).

    The returned dependency authenticates the caller, then requires a
    binding that allows ``capability`` at SYSTEM scope - which only a
    SYSTEM-scope binding can, since nothing is inherited upward. It
    raises the resolver's ``AuthError`` (401) for a missing or bad
    credential and ``Forbidden`` (403) when the bindings do not allow
    the capability.

    Args:
        capability: The capability the route requires, bound into the
            returned closure.

    Returns:
        A new dependency yielding the authenticated principal once the
        check passed; the same closure must be reused wherever the same
        capability is declared, or the check runs twice.
    """

    async def dependency(
        principal: CurrentPrincipal, repository: Bindings, cache: BindingCache
    ) -> Principal:
        """Enforce the bound capability at SYSTEM scope.

        Args:
            principal: The authenticated caller.
            repository: Source of the caller's bindings.
            cache: The request's binding cache.

        Returns:
            The same principal, as proof the check passed.
        """
        await check(cache, repository, principal, capability, Scope.system())
        return principal

    return dependency


def _require_resource(
    capability: str, kind: ScopeType, path_parameter: str
) -> Callable[..., Awaitable[Principal]]:
    """Bind a catalog guard to its capability and named HTTP path parameter.

    Args:
        capability: The capability required at the resolved resource.
        kind: The resource scope whose authoritative ancestry is resolved.
        path_parameter: The public path parameter naming that resource.

    Returns:
        A fresh dependency checking discovery before capability authorization.
    """

    async def dependency(
        resource_id: Annotated[UUID, Path(alias=path_parameter)],
        principal: CurrentPrincipal,
        repository: Bindings,
        cache: BindingCache,
        hierarchy: Hierarchy,
        visibility: CurrentVisibility,
    ) -> Principal:
        """Resolve the addressed resource and enforce the bound capability.

        Args:
            resource_id: The identifier parsed from the named path parameter.
            principal: The authenticated caller.
            repository: Source of resource ancestry and role bindings.
            cache: The request's binding cache.
            hierarchy: Typed catalog readers used for authoritative ancestry.
            visibility: The caller's discovery rights.

        Returns:
            The caller after discovery and capability checks pass.
        """
        scope = await resource_scope(hierarchy, kind, resource_id, visibility)
        await check(cache, repository, principal, capability, scope)
        return principal

    return dependency


def require_organization(capability: str) -> Callable[..., Awaitable[Principal]]:
    """Guard a route addressing one organization (path: ``organization_id``).

    The returned dependency authenticates the caller, resolves the
    ``organization_id`` path parameter to its scope through the caller's
    visibility - an id that is absent or simply not the caller's to
    discover fails with the repository's not-found error (404) before any
    binding is read - and then requires a binding allowing ``capability``
    at that organization or at SYSTEM scope. It raises the resolver's
    ``AuthError`` (401) for a missing or bad credential and ``Forbidden``
    (403) when the bindings do not allow the capability.

    Args:
        capability: The capability the route requires, bound into the
            returned closure.

    Returns:
        A new dependency yielding the authenticated principal once the
        check passed; the same closure must be reused wherever the same
        capability is declared, or the check runs twice.
    """
    return _require_resource(capability, ScopeType.ORGANIZATION, "organization_id")


def require_project(capability: str) -> Callable[..., Awaitable[Principal]]:
    """Guard a route addressing one project (path: ``project_id``).

    The returned dependency authenticates the caller, resolves the
    ``project_id`` path parameter to a scope carrying its organization,
    through the caller's visibility - an id that is absent or simply not
    the caller's to discover fails with the repository's not-found error
    (404) before any binding is read - and then requires a binding
    allowing ``capability`` at the project, its organization or SYSTEM
    scope. It raises the resolver's ``AuthError`` (401) for a missing or
    bad credential and ``Forbidden`` (403) when the bindings do not allow
    the capability.

    Args:
        capability: The capability the route requires, bound into the
            returned closure.

    Returns:
        A new dependency yielding the authenticated principal once the
        check passed; the same closure must be reused wherever the same
        capability is declared, or the check runs twice.
    """
    return _require_resource(capability, ScopeType.PROJECT, "project_id")


def require_dataset(capability: str) -> Callable[..., Awaitable[Principal]]:
    """Guard a route addressing one dataset (path: ``dataset_id``).

    The returned dependency authenticates the caller, resolves the
    ``dataset_id`` path parameter to a scope carrying its project and
    organization, through the caller's visibility - an id that is absent
    or simply not the caller's to discover fails with the repository's
    not-found error (404) before any binding is read - and then requires a
    binding allowing ``capability`` at the dataset or any of its ancestors.
    It raises the resolver's ``AuthError`` (401) for a missing or bad
    credential and ``Forbidden`` (403) when the bindings do not allow the
    capability.

    Args:
        capability: The capability the route requires, bound into the
            returned closure.

    Returns:
        A new dependency yielding the authenticated principal once the
        check passed; the same closure must be reused wherever the same
        capability is declared, or the check runs twice.
    """
    return _require_resource(capability, ScopeType.DATASET, "dataset_id")
