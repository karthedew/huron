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
from .decisions import BindingCache, check
from .scopes import dataset_scope, organization_scope, project_scope

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


def require_system(capability: str) -> Callable[..., Awaitable[Principal]]:
    """Guard a platform-scope route (e.g. ``organization.create``)."""

    async def dependency(
        principal: CurrentPrincipal, repository: Repository, cache: BindingCache
    ) -> Principal:
        await check(cache, repository, principal, capability, Scope.system())
        return principal

    return dependency


def require_organization(capability: str) -> Callable[..., Awaitable[Principal]]:
    """Guard a route addressing one organization (path: ``organization_id``)."""

    async def dependency(
        organization_id: UUID,
        principal: CurrentPrincipal,
        repository: Repository,
        cache: BindingCache,
    ) -> Principal:
        scope = organization_scope(repository, organization_id)
        await check(cache, repository, principal, capability, scope)
        return principal

    return dependency


def require_project(capability: str) -> Callable[..., Awaitable[Principal]]:
    """Guard a route addressing one project (path: ``project_id``)."""

    async def dependency(
        project_id: UUID,
        principal: CurrentPrincipal,
        repository: Repository,
        cache: BindingCache,
    ) -> Principal:
        scope = project_scope(repository, project_id)
        await check(cache, repository, principal, capability, scope)
        return principal

    return dependency


def require_dataset(capability: str) -> Callable[..., Awaitable[Principal]]:
    """Guard a route addressing one dataset (path: ``dataset_id``)."""

    async def dependency(
        dataset_id: UUID,
        principal: CurrentPrincipal,
        repository: Repository,
        cache: BindingCache,
    ) -> Principal:
        scope = dataset_scope(repository, dataset_id)
        await check(cache, repository, principal, capability, scope)
        return principal

    return dependency


@dataclass(frozen=True, slots=True)
class LayerWrite:
    principal: Principal
    layer: Layer


async def dataset_layer_writer(
    dataset_id: UUID,
    layer: str,
    principal: CurrentPrincipal,
    repository: Repository,
    cache: BindingCache,
) -> LayerWrite:
    """Guard a data-plane write: layer rule first, then the binding check.

    ``ensure_layer_writable`` refuses human principals on silver/gold no
    matter what bindings exist (defense in depth); ``check`` then requires a
    ``data.write`` binding covering this dataset and this layer.
    """
    parsed = parse_layer(layer)
    ensure_layer_writable(parsed, principal.kind)
    capability, layer_code = required_capability(LayerAction.WRITE, parsed)
    scope = dataset_scope(repository, dataset_id)
    await check(cache, repository, principal, capability, scope, layer=layer_code)
    return LayerWrite(principal=principal, layer=parsed)
