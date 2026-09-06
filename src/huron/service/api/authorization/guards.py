"""The dependencies a route declares.

Holding a ``Principal`` returned by a ``require_*`` dependency is proof the
capability check passed; holding an ``IngestDrive`` is proof the caller may
act on one ingest session, and whether they own it. Every factory returns a
**new** closure per call, so a capability declared both on a router and as a
parameter must share one bound closure or the check runs twice; routes never
re-check permissions.
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
    required_capability,
)
from huron.pkg.rbac import Scope

from ..errors import Forbidden
from ..runtime import Ingest, Repository
from .credentials import CurrentPrincipal
from .decisions import BindingCache, CurrentVisibility, check
from .scopes import dataset_scope, organization_scope, project_scope

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ..ingest import SessionLedger
    from ..repository import HierarchyRepository
    from .decisions import BindingCacheMap


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
class IngestDrive:
    """Proof that the caller may act on one session: the ledger as read, and whether they own it.

    ``owner`` is true only when the session's ``created_by`` is the
    caller's own subject; a project admin resolving through
    ``project.update`` instead is proof enough to read or abort a
    session, never to drive its upload, verification or commit.
    """

    principal: Principal
    ledger: SessionLedger
    owner: bool


async def _raw_write(
    cache: BindingCacheMap, repository: HierarchyRepository, principal: Principal, scope: Scope
) -> None:
    """Refuse a raw-layer write the kind rule or the caller's bindings forbid.

    Raises ``LayerWriteForbidden`` if a principal of this kind may never
    write raw, and ``Forbidden`` if the caller holds no ``data.write@raw``
    binding covering ``scope``.

    Args:
        cache: The request's binding cache.
        repository: Source of the caller's bindings.
        principal: The authenticated caller, whose ``kind`` the layer rule
            reads.
        scope: Where the write is aimed.
    """
    ensure_layer_writable(Layer.RAW, principal.kind)
    capability, layer_code = required_capability(LayerAction.WRITE, Layer.RAW)
    await check(cache, repository, principal, capability, scope, layer=layer_code)


async def dataset_raw_writer(
    dataset_id: UUID,
    principal: CurrentPrincipal,
    repository: Repository,
    cache: BindingCache,
    visibility: CurrentVisibility,
) -> Principal:
    """Guard opening a raw ingest session on an existing dataset.

    The dataset is resolved to its scope first, so an unknown or invisible
    dataset is 404 before the layer rule or the binding ever runs.

    Args:
        dataset_id: The path parameter naming the dataset to write to.
        principal: The authenticated caller.
        repository: Resolves the dataset's ancestry and the caller's
            bindings.
        cache: The request's binding cache.
        visibility: The caller's discovery rights, used to resolve
            ``dataset_id``.

    Returns:
        The caller, as proof the checks passed.
    """
    scope = await dataset_scope(repository, dataset_id, visibility)
    await _raw_write(cache, repository, principal, scope)
    return principal


async def project_intake(
    project_id: UUID,
    principal: CurrentPrincipal,
    repository: Repository,
    cache: BindingCache,
    visibility: CurrentVisibility,
) -> Principal:
    """Guard minting a dataset at intake and opening its first raw ingest session.

    The kind rule and the raw-write binding are checked before
    ``dataset.create``, so a service account is refused for writing raw
    before it is ever asked whether it may mint a dataset at all - it never
    mints one it cannot fill.

    Args:
        project_id: The path parameter naming the project to intake into.
        principal: The authenticated caller.
        repository: Resolves the project's ancestry and the caller's
            bindings.
        cache: The request's binding cache.
        visibility: The caller's discovery rights, used to resolve
            ``project_id``.

    Returns:
        The caller, as proof the checks passed.
    """
    scope = await project_scope(repository, project_id, visibility)
    await _raw_write(cache, repository, principal, scope)
    await check(cache, repository, principal, "dataset.create", scope)
    return principal


async def session_overseer(
    session_id: UUID,
    principal: CurrentPrincipal,
    repository: Repository,
    ingest: Ingest,
    cache: BindingCache,
    visibility: CurrentVisibility,
) -> IngestDrive:
    """Guard reading or aborting a session: the owner, or a project admin.

    Args:
        session_id: The path parameter naming the session.
        principal: The authenticated caller.
        repository: Resolves the session's dataset scope and the caller's
            bindings.
        ingest: The ingest service the session's ledger is read from.
        cache: The request's binding cache.
        visibility: The caller's discovery rights, used to resolve the
            session's dataset.

    Returns:
        Proof of the caller's standing: the ledger as read, and whether
        the caller is the session's owner.
    """
    ledger = await ingest.ledger(session_id)
    scope = await dataset_scope(repository, ledger.dataset_id, visibility)
    owner = ledger.created_by == principal.subject
    if not owner:
        await check(cache, repository, principal, "project.update", scope)
    return IngestDrive(principal=principal, ledger=ledger, owner=owner)


async def session_owner(
    session_id: UUID,
    principal: CurrentPrincipal,
    repository: Repository,
    ingest: Ingest,
    cache: BindingCache,
    visibility: CurrentVisibility,
) -> IngestDrive:
    """Guard driving a session: the owner alone, and only while their raw-write binding stands.

    Resolves exactly as :func:`session_overseer` does, then refuses a
    caller who is not the owner even if ``project.update`` let them
    through that resolution - administering a session is not driving it -
    and finally re-checks the owner's own raw-write binding, so a
    revocation takes effect on the very next call.

    Args:
        session_id: The path parameter naming the session.
        principal: The authenticated caller.
        repository: Resolves the session's dataset scope and the caller's
            bindings.
        ingest: The ingest service the session's ledger is read from.
        cache: The request's binding cache.
        visibility: The caller's discovery rights, used to resolve the
            session's dataset.

    Returns:
        Proof of the caller's standing to drive the session.

    Raises:
        Forbidden: If the caller does not own the session.
    """
    drive = await session_overseer(session_id, principal, repository, ingest, cache, visibility)
    if not drive.owner:
        raise Forbidden(f"{principal.subject} does not own ingest session {session_id}")
    scope = await dataset_scope(repository, drive.ledger.dataset_id, visibility)
    await _raw_write(cache, repository, principal, scope)
    return drive
