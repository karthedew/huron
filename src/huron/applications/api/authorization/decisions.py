"""Bindings, the per-request cache, the allow/deny call, and the caller's visibility.

Role bindings are cached for exactly one request and never wider:
``request_binding_cache`` is a ``Depends``-cached provider, so FastAPI
builds one dict per request and every guard and handler in that request
shares it. A mid-request role change cannot apply retroactively, and no
cache may outlive the principal it was built for. ``current_visibility``
computes the same caller's ``Visibility`` once per request, through
FastAPI's own dependency cache, so every guard and listing that declares it
shares one computation.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from huron.core.security import (
    BindingCacheMap,
    as_rbac_principal,
    bindings_for_principal,
    check,
    visibility_for_principal,
)
from huron.core.security.rules import Visibility

from ..runtime import Bindings, Runtime
from .credentials import CurrentPrincipal


async def request_binding_cache() -> BindingCacheMap:
    """Mint one binding cache per request, and never wider.

    FastAPI resolves a cached dependency once per request, so every guard
    and handler in one request shares this dict and none of them shares it
    with another request. A mid-request role change must not apply
    retroactively to bindings already fetched, and no cache may outlive the
    principal it was built for.

    Returns:
        A fresh, empty cache keyed by identifier set; ``_cached_bindings_for``
        and ``bindings_for_principal`` fill it.
    """
    return {}


BindingCache = Annotated[BindingCacheMap, Depends(request_binding_cache)]


async def current_visibility(
    cache: BindingCache, repository: Bindings, principal: CurrentPrincipal, runtime: Runtime
) -> Visibility:
    """Compute the caller's discovery rights once per request.

    Reduces the caller's bindings against the hierarchy's shape exactly
    once: ``project_visibilities`` names every project's classification and
    owning organization, and ``dataset_parents`` is fetched only when the
    caller holds at least one DATASET-scope binding, since that is the only
    way a dataset can appear in the result at all. FastAPI's own per-request
    dependency cache is what keeps this to one computation no matter how
    many guards and handlers in the request declare ``CurrentVisibility``.

    Args:
        cache: The request's binding cache.
        repository: Source of the caller's bindings and the hierarchy's
            projects and dataset parents.
        principal: The authenticated caller.
        runtime: The published wiring, for the classification-aware
            authorizer that computes the result.

    Returns:
        The organization, project and dataset ids the caller may discover,
        and whether discovery is unrestricted.
    """
    return await visibility_for_principal(
        cache, repository, principal, runtime.authorizer, runtime.hierarchy
    )


CurrentVisibility = Annotated[Visibility, Depends(current_visibility)]

__all__ = [
    "BindingCache",
    "BindingCacheMap",
    "CurrentVisibility",
    "as_rbac_principal",
    "bindings_for_principal",
    "check",
    "current_visibility",
    "request_binding_cache",
]
