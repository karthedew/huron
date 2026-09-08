"""Authorization over authenticated actors and authoritative catalog state."""

from __future__ import annotations

from typing import TYPE_CHECKING

from huron.pkg.catalog.errors import DomainError
from huron.pkg.catalog.failures import Forbidden
from huron.pkg.rbac import (
    Binding,
    DatasetVisibility,
    Decision,
    Scope,
    ScopeType,
    Visibility,
    decide,
)
from huron.pkg.rbac import Principal as RbacPrincipal
from huron.pkg.rbac.roles import PRINCIPAL_KIND_SERVICE_ACCOUNT, service_account_bindings

if TYPE_CHECKING:
    from uuid import UUID

    from huron.pkg.auth import Principal
    from huron.pkg.catalog.records import Dataset
    from huron.pkg.rbac import RoleBindingAuthorizer

    from ._catalog import HierarchyRepository

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


class AccessPolicy:
    """Resolve one actor's permissions without relying on a transport dependency.

    Instances belong to one operation context; no binding cache is shared between actors.
    """

    def __init__(
        self, actor: Principal, repository: HierarchyRepository, authorizer: RoleBindingAuthorizer
    ) -> None:
        """Bind an authenticated actor to authoritative permission sources.

        Args:
            actor: The authenticated caller.
            repository: Catalog and role-binding operations.
            authorizer: Classification-aware discovery policy.
        """
        self.actor = actor
        self._repository = repository
        self._authorizer = authorizer

    async def visibility(self) -> Visibility:
        """Compute current discovery rights from authoritative bindings.

        Returns:
            The resources this actor may discover.
        """
        actor = as_rbac_principal(self.actor)
        bindings = await bindings_for_principal({}, self._repository, actor)
        dataset_ids = frozenset(
            binding.scope_id
            for binding in bindings
            if binding.scope_type is ScopeType.DATASET and binding.scope_id is not None
        )
        projects = await self._repository.project_visibilities()
        parents = await self._repository.dataset_parents(dataset_ids) if dataset_ids else {}
        return self._authorizer.visibility(
            actor,
            bindings,
            projects,
            [DatasetVisibility(dataset_id=k, project_id=v) for k, v in parents.items()],
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
        visible = await self.visibility()
        if kind is ScopeType.ORGANIZATION:
            await self._repository.organization(resource_id, visible)
            return Scope(kind, resource_id, organization_id=resource_id)
        if kind is ScopeType.PROJECT:
            project = await self._repository.project(resource_id, visible)
            return Scope(
                kind, resource_id, organization_id=project.organization_id, project_id=project.id
            )
        dataset = await self._repository.dataset(resource_id, visible)
        project = await self._repository.project(dataset.project_id, Visibility.ALL)
        return Scope(
            kind,
            resource_id,
            organization_id=project.organization_id,
            project_id=project.id,
            dataset_id=dataset.id,
        )

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

    async def dataset(self, dataset_id: UUID) -> Dataset:
        """Resolve a dataset using the current actor's discovery rights.

        Args:
            dataset_id: The dataset identifier.

        Returns:
            Its authoritative catalog record.
        """
        return await self._repository.dataset(dataset_id, await self.visibility())
