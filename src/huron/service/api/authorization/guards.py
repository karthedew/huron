"""The dependencies a route declares.

Holding a ``Principal`` returned by a ``require_*`` dependency is proof the
capability check passed; holding a ``LayerWrite`` is proof both the layer
rule and the binding check passed. Every factory returns a **new** closure
per call, so a capability declared both on a router and as a parameter must
share one bound closure or the check runs twice; routes never re-check
permissions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from huron.pkg.auth import Principal
from huron.pkg.catalog.layers import (
    Layer,
    LayerAction,
    ensure_layer_writable,
    parse_layer,
    required_capability,
)
from huron.pkg.rbac import Scope

from ..runtime import Repository
from .credentials import CurrentPrincipal
from .decisions import BindingCache, CurrentVisibility, check
from .scopes import dataset_scope, organization_scope, project_scope

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


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
        principal: CurrentPrincipal, repository: Repository, cache: BindingCache
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

    async def dependency(
        organization_id: UUID,
        principal: CurrentPrincipal,
        repository: Repository,
        cache: BindingCache,
        visibility: CurrentVisibility,
    ) -> Principal:
        """Enforce the bound capability at the addressed organization.

        Args:
            organization_id: The path parameter, bound by name.
            principal: The authenticated caller.
            repository: Resolves the organization and the caller's bindings.
            cache: The request's binding cache.
            visibility: The caller's discovery rights, used to resolve
                ``organization_id``.

        Returns:
            The same principal, as proof the check passed.
        """
        scope = await organization_scope(repository, organization_id, visibility)
        await check(cache, repository, principal, capability, scope)
        return principal

    return dependency


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

    async def dependency(
        project_id: UUID,
        principal: CurrentPrincipal,
        repository: Repository,
        cache: BindingCache,
        visibility: CurrentVisibility,
    ) -> Principal:
        """Enforce the bound capability at the addressed project.

        Args:
            project_id: The path parameter, bound by name.
            principal: The authenticated caller.
            repository: Resolves the project and the caller's bindings.
            cache: The request's binding cache.
            visibility: The caller's discovery rights, used to resolve
                ``project_id``.

        Returns:
            The same principal, as proof the check passed.
        """
        scope = await project_scope(repository, project_id, visibility)
        await check(cache, repository, principal, capability, scope)
        return principal

    return dependency


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

    async def dependency(
        dataset_id: UUID,
        principal: CurrentPrincipal,
        repository: Repository,
        cache: BindingCache,
        visibility: CurrentVisibility,
    ) -> Principal:
        """Enforce the bound capability at the addressed dataset.

        Args:
            dataset_id: The path parameter, bound by name.
            principal: The authenticated caller.
            repository: Resolves the dataset's ancestry and the caller's
                bindings.
            cache: The request's binding cache.
            visibility: The caller's discovery rights, used to resolve
                ``dataset_id``.

        Returns:
            The same principal, as proof the check passed.
        """
        scope = await dataset_scope(repository, dataset_id, visibility)
        await check(cache, repository, principal, capability, scope)
        return principal

    return dependency


@dataclass(frozen=True, slots=True)
class LayerWrite:
    """Proof that a data-plane write to one layer was authorized.

    Holding one means both the layer rule and the binding check passed
    for ``principal`` on ``layer``; a handler that receives it writes
    without re-checking. Frozen so the proof cannot be edited after the
    fact.
    """

    principal: Principal
    layer: Layer


async def dataset_layer_writer(
    dataset_id: UUID,
    layer: str,
    principal: CurrentPrincipal,
    repository: Repository,
    cache: BindingCache,
    visibility: CurrentVisibility,
) -> LayerWrite:
    """Guard a data-plane write: the dataset's scope first, then the layer rule, then the binding.

    The dataset is resolved to its scope before anything else, so an
    unknown or invisible dataset is 404 before the layer workflow ever gets
    a chance to refuse it. ``ensure_layer_writable`` then refuses human
    principals on silver/gold no matter what bindings exist (defense in
    depth); ``check`` requires a ``data.write`` binding covering this
    dataset and this layer. The failures propagate from the callees in that
    order: an unknown or invisible dataset is the repository's not-found
    error, an unknown layer name and a kind/layer mismatch are the layer
    module's domain errors, and a binding that does not cover the write is
    ``Forbidden``.

    Args:
        dataset_id: The path parameter naming the dataset written to.
        layer: The path parameter naming the layer, as sent; parsed here.
        principal: The authenticated caller, whose ``kind`` the layer rule
            reads.
        repository: Resolves the dataset's ancestry and the caller's
            bindings.
        cache: The request's binding cache.
        visibility: The caller's discovery rights, used to resolve
            ``dataset_id``.

    Returns:
        The proof handlers write under: the principal and the parsed layer.
    """
    scope = await dataset_scope(repository, dataset_id, visibility)
    parsed = parse_layer(layer)
    ensure_layer_writable(parsed, principal.kind)
    capability, layer_code = required_capability(LayerAction.WRITE, parsed)
    await check(cache, repository, principal, capability, scope, layer=layer_code)
    return LayerWrite(principal=principal, layer=parsed)
