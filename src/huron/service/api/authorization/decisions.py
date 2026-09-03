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


def as_rbac_principal(principal: Principal) -> RbacPrincipal:
    """Project an authenticated principal onto the shape the RBAC engine reads.

    The engine needs only what bindings are matched against - subject,
    groups and kind - so the credential-specific fields (scopes, project,
    authentication method) are dropped here and never influence a decision.

    Args:
        principal: The principal a credential resolver produced.

    Returns:
        The engine's principal, whose ``identifiers`` are what bindings
        name.
    """
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

    Args:
        cache: The request's cache, filled on the first miss.
        repository: Where ``bindings_for`` is answered on a miss.
        identifiers: The principal's ``kind:subject`` and ``group:`` names,
            which is what stored bindings are matched against.

    Returns:
        Every binding naming any of the identifiers, fetched at most once
        per request.
    """
    if identifiers not in cache:
        cache[identifiers] = await repository.bindings_for(identifiers)
    return cache[identifiers]


async def bindings_for_principal(
    cache: BindingCacheMap, repository: HierarchyRepository, actor: RbacPrincipal
) -> tuple[Binding, ...]:
    """Return the bindings ``decide()`` should see for this caller.

    Humans (and their groups) resolve through stored role bindings. A
    service account holds no roles and has no binding rows: its whole
    authority is intrinsic to the principal kind, synthesized from the
    account's owning organization (``service_account_bindings``). An
    authenticated ``sa:`` principal with no service-account row - a key
    that outlived its account - gets no bindings and is denied everywhere,
    as does one whose account has been disabled. Both branches memoize in
    the same per-request cache, so a service account's row is read at most
    once per request too.

    Args:
        cache: The request's binding cache.
        repository: Source of stored bindings and service-account rows.
        actor: The engine's view of the caller, whose ``kind`` selects the
            branch and whose ``identifiers`` key the cache.

    Returns:
        The bindings to hand to ``decide()``: stored ones for a human,
        synthesized ones for a live service account, none for a service
        account that is missing or disabled.
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
    """Refuse with 403 unless the principal's role bindings allow ``capability`` here.

    The one place the tier turns a decision into an error: a guard or
    handler that must refuse calls this rather than mapping a ``Decision``
    to ``Forbidden`` itself, while a listing that only needs to know
    whether something is allowed reads ``decide()`` directly. Only an
    explicit ``ALLOW`` passes; a deny and an absence of applicable bindings
    are refused alike, and the refusal names the capability, layer, subject
    and scope level so an operator can tell which binding is missing.

    Args:
        cache: The request's binding cache.
        repository: Source of the principal's bindings.
        principal: The authenticated caller.
        capability: The capability the route requires, such as
            ``organization.create`` or ``data.write``.
        scope: Where the capability is exercised, carrying its full
            ancestry so inherited bindings apply.
        layer: For layer-scoped capabilities, the storage layer the
            binding must cover; ``None`` for every other capability.

    Raises:
        Forbidden: If the decision is anything but ``ALLOW``.
    """
    actor = as_rbac_principal(principal)
    bindings = await bindings_for_principal(cache, repository, actor)
    if decide(bindings, actor, capability, scope, layer=layer) is not Decision.ALLOW:
        suffix = f" on layer {layer}" if layer else ""
        raise Forbidden(
            f"{capability}{suffix} denied for {principal.subject} at {scope.scope_type.value} scope"
        )
