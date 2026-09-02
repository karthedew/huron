"""Bindings, the per-request cache, and the allow/deny call.

Role bindings are cached for exactly one request and never wider:
``request_binding_cache`` is a ``Depends``-cached provider, so FastAPI
builds one dict per request and every guard and handler in that request
shares it. A mid-request role change cannot apply retroactively, and no
cache may outlive the principal it was built for.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import Depends

from huron.pkg.auth import Principal
from huron.pkg.catalog.errors import DomainError
from huron.pkg.rbac import Binding, Decision, Scope, decide
from huron.pkg.rbac import Principal as RbacPrincipal
from huron.pkg.rbac.roles import PRINCIPAL_KIND_SERVICE_ACCOUNT, service_account_bindings

from ..errors import Forbidden

if TYPE_CHECKING:
    from ..repository import HierarchyRepository

BindingCacheMap = dict[frozenset[str], tuple[Binding, ...]]


async def request_binding_cache() -> BindingCacheMap:
    """One binding cache per request, and never wider.

    FastAPI resolves a cached dependency once per request, so every guard
    and handler in one request shares this dict and none of them shares it
    with another request. A mid-request role change must not apply
    retroactively to bindings already fetched, and no cache may outlive the
    principal it was built for.
    """
    return {}


BindingCache = Annotated[BindingCacheMap, Depends(request_binding_cache)]


def as_rbac_principal(principal: Principal) -> RbacPrincipal:
    return RbacPrincipal(subject=principal.subject, groups=principal.groups, kind=principal.kind)


async def _cached_bindings_for(
    cache: BindingCacheMap, repository: HierarchyRepository, identifiers: frozenset[str]
) -> tuple[Binding, ...]:
    """Memoize ``bindings_for`` by identifier set for the life of one request.

    A single route commonly needs the caller's bindings more than once (a
    ``require_*`` guard, then a layer-workflow listing that decides per
    layer) - without this, each of those would re-issue the same join query.
    The caller supplies the cache (``request_binding_cache`` mints exactly
    one per request via FastAPI's dependency cache) so this function itself
    never creates or discards one: it must not survive past the request,
    since a mid-request role change should never apply retroactively to
    bindings already fetched, and it must never leak between requests or
    principals.
    """
    if identifiers not in cache:
        cache[identifiers] = await repository.bindings_for(identifiers)
    return cache[identifiers]


async def bindings_for_principal(
    cache: BindingCacheMap, repository: HierarchyRepository, actor: RbacPrincipal
) -> tuple[Binding, ...]:
    """The bindings ``decide()`` should see for this caller.

    Humans (and their groups) resolve through stored role bindings. A
    service account holds no roles and has no binding rows: its whole
    authority is intrinsic to the principal kind, synthesized from the
    account's owning organization (``service_account_bindings``). An
    authenticated ``sa:`` principal with no service-account row - a key
    that outlived its account - gets no bindings and is denied everywhere.
    """
    if actor.kind != PRINCIPAL_KIND_SERVICE_ACCOUNT:
        return await _cached_bindings_for(cache, repository, actor.identifiers)
    if actor.identifiers not in cache:
        try:
            account = await repository.service_account_by_subject(actor.subject)
        except DomainError:
            cache[actor.identifiers] = ()
        else:
            cache[actor.identifiers] = (
                service_account_bindings(f"sa:{actor.subject}", account.organization_id)
                if account.disabled_at is None
                else ()
            )
    return cache[actor.identifiers]


async def check(
    cache: BindingCacheMap,
    repository: HierarchyRepository,
    principal: Principal,
    capability: str,
    scope: Scope,
    *,
    layer: str | None = None,
) -> None:
    """403 unless the principal's role bindings allow ``capability`` here."""
    actor = as_rbac_principal(principal)
    bindings = await bindings_for_principal(cache, repository, actor)
    if decide(bindings, actor, capability, scope, layer=layer) is not Decision.ALLOW:
        suffix = f" on layer {layer}" if layer else ""
        raise Forbidden(
            f"{capability}{suffix} denied for {principal.subject} at {scope.scope_type.value} scope"
        )
