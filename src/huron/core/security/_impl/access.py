"""Authorization over authenticated actors and authoritative catalog state."""

from __future__ import annotations

from typing import TYPE_CHECKING

from huron.core.foundation.errors import DomainError, Forbidden
from huron.core.security.roles import PRINCIPAL_KIND_SERVICE_ACCOUNT, service_account_bindings
from huron.core.security.rules import (
    Binding,
    DatasetVisibility,
    Decision,
    Scope,
    ScopeType,
    Visibility,
    decide,
)
from huron.core.security.rules import Principal as RbacPrincipal

if TYPE_CHECKING:
    from uuid import UUID

    from huron.core.foundation.retry import IdempotencyClaim
    from huron.core.security.facts import BindingFacts, CatalogFacts
    from huron.core.security.principal import Principal
    from huron.core.security.rules import RoleBindingAuthorizer

BindingCacheMap = dict[frozenset[str], tuple[Binding, ...]]


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
    cache: BindingCacheMap, repository: BindingFacts, identifiers: frozenset[str]
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
    cache: BindingCacheMap, repository: BindingFacts, actor: RbacPrincipal
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
    repository: BindingFacts,
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


async def visibility_for_principal(
    cache: BindingCacheMap,
    repository: BindingFacts,
    principal: Principal,
    authorizer: RoleBindingAuthorizer,
    hierarchy: CatalogFacts,
) -> Visibility:
    """Resolve discovery rights against authoritative bindings and catalog ancestry.

    The caller owns the binding cache lifetime: HTTP dependencies may share it
    within one request, while reusable operations supply a fresh cache. Dataset
    ancestry is loaded only for dataset-scoped bindings.

    Args:
        cache: Bindings already loaded in this authorization context.
        repository: Source of bindings, classifications and dataset parents.
        principal: The authenticated caller.
        authorizer: The classification-aware discovery policy.
        hierarchy: Current classifications and dataset ancestry.

    Returns:
        The resources this caller may discover.
    """
    actor = as_rbac_principal(principal)
    bindings = await bindings_for_principal(cache, repository, actor)
    dataset_ids = frozenset(
        binding.scope_id
        for binding in bindings
        if binding.scope_type is ScopeType.DATASET and binding.scope_id is not None
    )
    projects = await hierarchy.project_visibilities()
    parents = await hierarchy.dataset_parents(dataset_ids) if dataset_ids else {}
    return authorizer.visibility(
        actor,
        bindings,
        projects,
        [DatasetVisibility(dataset_id=k, project_id=v) for k, v in parents.items()],
    )


class AccessPolicy:
    """Resolve one actor's permissions without relying on a transport dependency.

    Instances belong to one operation context; no binding cache is shared between actors.
    """

    def __init__(
        self,
        actor: Principal,
        hierarchy: CatalogFacts,
        repository: BindingFacts,
        authorizer: RoleBindingAuthorizer,
    ) -> None:
        """Bind an authenticated actor to authoritative permission sources.

        Args:
            actor: The authenticated caller.
            hierarchy: Current catalog discovery facts and typed readers.
            repository: Catalog and role-binding operations.
            authorizer: Classification-aware discovery policy.
        """
        self.actor = actor
        self._repository = repository
        self._hierarchy = hierarchy
        self._authorizer = authorizer

    def require_claim(self, claim: IdempotencyClaim) -> None:
        """Require a retry identity owned by this authenticated actor.

        Callers separately enforce the operation's capability and target access
        before validating its claim, preserving their authorization ordering.

        Args:
            claim: The retry identity supplied for the authorized operation.

        Raises:
            Forbidden: If the claim belongs to another actor.
        """
        if claim.principal != self.actor.subject:
            raise Forbidden("idempotency claim must belong to the authenticated actor")

    async def visibility(self) -> Visibility:
        """Compute current discovery rights from authoritative bindings.

        Returns:
            The resources this actor may discover.
        """
        return await visibility_for_principal(
            {}, self._repository, self.actor, self._authorizer, self._hierarchy
        )

    async def scope(self, kind: ScopeType, resource_id: UUID | None = None) -> Scope:
        """Resolve authoritative ancestry, refusing undiscoverable resources first.

        Args:
            kind: The addressed resource's scope type.
            resource_id: Its identifier, absent only for system scope.

        Returns:
            A scope with authoritative ancestry.

        Raises:
            ValueError: If a non-system scope has no identifier.
        """
        if kind is ScopeType.SYSTEM:
            return Scope.system()
        if resource_id is None:
            raise ValueError("resource scope requires an identifier")
        return await self._hierarchy.resource_scope(kind, resource_id, await self.visibility())

    async def require(
        self,
        capability: str,
        kind: ScopeType,
        resource_id: UUID | None = None,
        *,
        layer: str | None = None,
    ) -> None:
        """Require permission using fresh bindings and authoritative ancestry.

        Args:
            capability: The requested operation.
            kind: The target's scope type.
            resource_id: The target identifier.
            layer: The data layer, for data capabilities.
        """
        scope = await self.scope(kind, resource_id)
        await check({}, self._repository, self.actor, capability, scope, layer=layer)

    async def bindings(self) -> tuple[Binding, ...]:
        """Read current human or service-account authority for this actor.

        Returns:
            The current compiled bindings, without retaining a permission cache.
        """
        return await bindings_for_principal({}, self._repository, as_rbac_principal(self.actor))
