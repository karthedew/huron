"""Compose request-bound Raw web operations over the application's existing runtime."""

from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request

from huron.core.catalog import CatalogCreation, DatasetCollection
from huron.core.catalog.external import PROVISIONER_SUBJECT, ExternalCatalog
from huron.core.raw import RawIngestionService, RevisionReadService
from huron.core.raw.web import RawWebOperations
from huron.core.security import AccessPolicy
from huron.core.security.authentication_errors import AuthError
from huron.core.security.principal import Principal
from huron.core.security.raw_delegation import (
    DelegatedBindings,
    RawDelegation,
    RawDelegationVerifier,
    raw_dataset_bindings,
)
from huron.core.security.rules import Binding, Classification, RoleBindingAuthorizer, ScopeType

from .runtime import Runtime


async def signed_request(request: Request, runtime: Runtime) -> RawDelegation:
    """Verify only the dedicated bridge credential and exact request bytes.

    Args:
        request: Actual incoming HTTP request.
        runtime: Configured application wiring.

    Returns:
        Verified target and actor authority.

    Raises:
        HTTPException: If the bridge is disabled or has no durable persistence.
        AuthError: If no dedicated bearer credential was supplied.
    """
    if not runtime.settings.raw_bridge_secret or runtime.raw_web is None:
        raise HTTPException(404, "Raw web uploads are not configured")
    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise AuthError("a signed Raw web request is required")
    path = request.scope["raw_path"].decode("ascii")
    query = request.scope["query_string"].decode("ascii")
    if query:
        path += f"?{query}"
    headers = {
        name: request.headers[name]
        for name in ("idempotency-key", "if-match")
        if name in request.headers
    }
    delegation = RawDelegationVerifier(runtime.settings.raw_bridge_secret).verify(
        token, method=request.method, path=path, headers=headers
    )
    if request.method != "PUT":
        delegation.verify_body(await request.body())
    return delegation


Delegation = Annotated[RawDelegation, Depends(signed_request)]


def operations(runtime: Runtime, delegation: Delegation) -> RawWebOperations:
    """Bind existing domain workflows to the verified request and its exact dataset.

    Internal hierarchy creation uses explicit deployment authority; uploads and
    reads always use the real human's expiring dataset-scoped bindings.

    Args:
        runtime: Existing PostgreSQL and POSIX lifecycle wiring.
        delegation: Verified actor and upstream authority.

    Returns:
        Target-checked Raw web workflows.

    Raises:
        HTTPException: If durable mappings are unavailable.
    """
    if runtime.raw_web is None:
        raise HTTPException(404, "Raw web uploads are not configured")
    authorizer = RoleBindingAuthorizer((Classification("raw-web", 0, True),))
    provisioner = Principal(PROVISIONER_SUBJECT, authentication_method="deployment")
    provisioning = DelegatedBindings(
        (
            Binding(
                principal=f"user:{PROVISIONER_SUBJECT}",
                capabilities=frozenset(
                    {"organization.create", "project.create", "dataset.create", "dataset.discover"}
                ),
                scope_type=ScopeType.SYSTEM,
                scope_id=None,
            ),
        )
    )
    infrastructure = CatalogCreation(
        AccessPolicy(provisioner, runtime.hierarchy, provisioning, authorizer),
        runtime.hierarchy,
        runtime.raw_store,
        classification_vocabulary=("raw-web",),
    )

    def access(dataset_id: UUID) -> AccessPolicy:
        """Bind authority to a dataset resolved from the immutable target mapping.

        Args:
            dataset_id: Exact persisted dataset identity.

        Returns:
            The actor-bound policy with no persistent grants.
        """
        return AccessPolicy(
            delegation.actor,
            runtime.hierarchy,
            raw_dataset_bindings(delegation, dataset_id),
            authorizer,
        )

    def ingestion(dataset_id: UUID) -> RawIngestionService:
        """Construct the existing actor-bound Raw workflow.

        Args:
            dataset_id: Persisted exact target.

        Returns:
            Authorized Raw ingestion operations.
        """
        policy = access(dataset_id)
        creation = CatalogCreation(
            policy,
            runtime.hierarchy,
            runtime.raw_store,
            classification_vocabulary=("raw-web",),
        )
        datasets = DatasetCollection(policy, runtime.hierarchy, runtime.raw_store)
        return runtime.raw.ingestion(policy, creation, datasets)

    def revisions(dataset_id: UUID) -> RevisionReadService:
        """Construct the existing actor-bound revision reader.

        Args:
            dataset_id: Persisted exact target.

        Returns:
            Authorized revision operations.
        """
        return runtime.raw.revisions(access(dataset_id))

    return RawWebOperations(
        delegation,
        ExternalCatalog(runtime.raw_web, infrastructure),
        runtime.hierarchy,
        runtime.raw_web,
        ingestion,
        revisions,
    )


Operations = Annotated[RawWebOperations, Depends(operations)]
