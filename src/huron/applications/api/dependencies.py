"""Bind transport-independent workflows to the authenticated request actor."""

from typing import Annotated

from fastapi import Depends

from huron.core.catalog import (
    CatalogCreation,
    DatasetCollection,
    OrganizationCollection,
    ProjectCollection,
)
from huron.core.security import AccessPolicy, Bindings, IdentityService, Policies, ServiceAccounts

from .authorization.credentials import CurrentPrincipal
from .runtime import Runtime


def _access_policy(runtime: Runtime, actor: CurrentPrincipal) -> AccessPolicy:
    """Build the actor-bound authorization policy every workflow factory below shares.

    Args:
        runtime: The process's configured capabilities.
        actor: The authenticated request principal.

    Returns:
        Fresh authorization facts bound to this actor and this runtime's
        hierarchy, RBAC and classification capabilities.
    """
    return AccessPolicy(actor, runtime.hierarchy, runtime.rbac, runtime.authorizer)


def organization_collection(runtime: Runtime, actor: CurrentPrincipal) -> OrganizationCollection:
    """Bind organization discovery and descriptions to the authenticated actor.

    Args:
        runtime: The process's configured capabilities.
        actor: The authenticated request principal.

    Returns:
        Authorized organization reads and descriptive updates.
    """
    return OrganizationCollection(
        _access_policy(runtime, actor), runtime.hierarchy, runtime.generations
    )


Organizations = Annotated[OrganizationCollection, Depends(organization_collection)]


def project_collection(runtime: Runtime, actor: CurrentPrincipal) -> ProjectCollection:
    """Bind project discovery and descriptions to the authenticated actor.

    Args:
        runtime: The process's configured capabilities.
        actor: The authenticated request principal.

    Returns:
        Authorized project reads and descriptive updates.
    """
    return ProjectCollection(_access_policy(runtime, actor), runtime.hierarchy, runtime.generations)


Projects = Annotated[ProjectCollection, Depends(project_collection)]


def dataset_collection(runtime: Runtime, actor: CurrentPrincipal) -> DatasetCollection:
    """Bind dataset discovery, descriptions and layer views to the authenticated actor.

    Args:
        runtime: The process's configured capabilities.
        actor: The authenticated request principal.

    Returns:
        Authorized dataset reads, descriptive updates and layer descriptions.
    """
    return DatasetCollection(_access_policy(runtime, actor), runtime.hierarchy, runtime.generations)


Datasets = Annotated[DatasetCollection, Depends(dataset_collection)]


def catalog_creation(runtime: Runtime, actor: CurrentPrincipal) -> CatalogCreation:
    """Bind explicit identity creation to the authenticated actor.

    Args:
        runtime: The process's initialized capabilities and classification settings.
        actor: The authenticated caller.

    Returns:
        Authorized creation with transaction-scoped retry and durable publication.
    """
    return CatalogCreation(
        _access_policy(runtime, actor),
        runtime.hierarchy,
        runtime.generations,
        classification_vocabulary=tuple(
            value.code for value in runtime.settings.classification_vocabulary
        ),
    )


Creation = Annotated[CatalogCreation, Depends(catalog_creation)]


def role_bindings(runtime: Runtime, actor: CurrentPrincipal) -> Bindings:
    """Bind role-binding administration to the authenticated actor.

    Args:
        runtime: The process's configured capabilities.
        actor: The authenticated caller.

    Returns:
        Authorized binding grant, list and revoke operations.
    """
    return Bindings(_access_policy(runtime, actor), runtime.hierarchy, runtime.rbac)


RoleBindings = Annotated[Bindings, Depends(role_bindings)]


def policy_administration(runtime: Runtime, actor: CurrentPrincipal) -> Policies:
    """Bind policy definition and attachment to the authenticated actor.

    Args:
        runtime: The process's configured capabilities.
        actor: The authenticated caller.

    Returns:
        Authorized policy create, list and attach operations.
    """
    return Policies(_access_policy(runtime, actor), runtime.hierarchy, runtime.rbac)


PolicyAdministration = Annotated[Policies, Depends(policy_administration)]


def service_account_administration(runtime: Runtime, actor: CurrentPrincipal) -> ServiceAccounts:
    """Bind service-account administration to the authenticated actor.

    Args:
        runtime: The process's configured capabilities.
        actor: The authenticated caller.

    Returns:
        Authorized service-account create, read, list and disable operations.
    """
    return ServiceAccounts(_access_policy(runtime, actor), runtime.hierarchy, runtime.rbac)


ServiceAccountAdministration = Annotated[ServiceAccounts, Depends(service_account_administration)]


def identity_service(runtime: Runtime, actor: CurrentPrincipal) -> IdentityService:
    """Bind identity management to the authenticated actor.

    Args:
        runtime: The process's configured capabilities.
        actor: The authenticated caller.

    Returns:
        Authorized identity operations.
    """
    return IdentityService(
        _access_policy(runtime, actor),
        runtime.principals,
        runtime.api_keys,
        service_account_administration(runtime, actor),
    )


Identity = Annotated[IdentityService, Depends(identity_service)]
