"""Bind transport-independent workflows to the authenticated request actor."""

from typing import Annotated

from fastapi import Depends

from huron.core.access import AccessPolicy
from huron.core.catalog import CatalogService
from huron.core.catalog_creation import CatalogCreation
from huron.core.identity import IdentityService
from huron.core.raw import RawIngestionService
from huron.core.releases import Releases
from huron.core.revisions import RevisionReadService

from .authorization.credentials import CurrentPrincipal
from .runtime import Runtime


def catalog_service(runtime: Runtime, actor: CurrentPrincipal) -> CatalogService:
    """Create the actor-bound catalog facade for this request.

    Args:
        runtime: The process's configured capabilities.
        actor: The authenticated request principal.

    Returns:
        Catalog operations that enforce the actor's permissions themselves.
    """
    return CatalogService(
        runtime.repository,
        AccessPolicy(actor, runtime.hierarchy, runtime.rbac, runtime.authorizer),
        runtime.hierarchy,
    )


Catalog = Annotated[CatalogService, Depends(catalog_service)]


def catalog_creation(runtime: Runtime, actor: CurrentPrincipal) -> CatalogCreation:
    """Bind explicit identity creation to the authenticated actor.

    Args:
        runtime: The process's initialized capabilities and classification settings.
        actor: The authenticated caller.

    Returns:
        Authorized creation with transaction-scoped retry and durable publication.
    """
    return CatalogCreation(
        AccessPolicy(actor, runtime.hierarchy, runtime.rbac, runtime.authorizer),
        runtime.hierarchy,
        runtime.repository.raw_store,
        classification_vocabulary=tuple(
            value.code for value in runtime.settings.classification_vocabulary
        ),
    )


Creation = Annotated[CatalogCreation, Depends(catalog_creation)]


def catalog_releases(runtime: Runtime, actor: CurrentPrincipal) -> Releases:
    """Bind immutable release publication and resolution to the authenticated actor.

    Args:
        runtime: The process's configured capabilities.
        actor: The authenticated caller.

    Returns:
        Authorized release creation, resolution and browsing.
    """
    return Releases(
        AccessPolicy(actor, runtime.hierarchy, runtime.rbac, runtime.authorizer),
        runtime.hierarchy,
        runtime.repository.raw_store,
    )


ReleaseWorkflow = Annotated[Releases, Depends(catalog_releases)]


def raw_ingestion_service(runtime: Runtime, actor: CurrentPrincipal) -> RawIngestionService:
    """Bind Raw ingestion to the authenticated actor.

    Args:
        runtime: The process's configured capabilities.
        actor: The authenticated caller.

    Returns:
        Authorized Raw ingestion operations.
    """
    return RawIngestionService(
        runtime.ingest,
        AccessPolicy(actor, runtime.hierarchy, runtime.rbac, runtime.authorizer),
        catalog_creation(runtime, actor),
    )


RawIngestion = Annotated[RawIngestionService, Depends(raw_ingestion_service)]


def identity_service(runtime: Runtime, actor: CurrentPrincipal) -> IdentityService:
    """Bind identity management to the authenticated actor.

    Args:
        runtime: The process's configured capabilities.
        actor: The authenticated caller.

    Returns:
        Authorized identity operations.
    """
    return IdentityService(
        AccessPolicy(actor, runtime.hierarchy, runtime.rbac, runtime.authorizer),
        runtime.principals,
        runtime.credentials,
        runtime.sessions,
        runtime.api_keys,
        catalog_service(runtime, actor),
    )


Identity = Annotated[IdentityService, Depends(identity_service)]


def revision_service(runtime: Runtime, actor: CurrentPrincipal) -> RevisionReadService:
    """Bind revision reads to the authenticated actor.

    Args:
        runtime: The configured capabilities.
        actor: The authenticated caller.

    Returns:
        Authorized revision reads.
    """
    return RevisionReadService(
        runtime.revisions, AccessPolicy(actor, runtime.hierarchy, runtime.rbac, runtime.authorizer)
    )


Revisions = Annotated[RevisionReadService, Depends(revision_service)]
