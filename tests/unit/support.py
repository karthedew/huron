"""Shared test builders for the API tier's injectable storage seam."""

from __future__ import annotations

from huron.pkg.auth import (
    MemoryApiKeyStore,
    MemoryCredentialStore,
    MemoryPrincipalStore,
    MemorySessionStore,
)
from huron.service.api.runtime import ApiStores
from huron.service.api.stores import InMemoryHierarchyStore, InMemoryRbacStore


def memory_stores() -> ApiStores:
    """Build a fresh in-memory ``ApiStores`` for one test's application.

    Returns:
        A store bundle backed entirely by process memory, with nothing
        shared with any other call.
    """
    return ApiStores(
        hierarchy=InMemoryHierarchyStore(),
        rbac=InMemoryRbacStore(),
        api_keys=MemoryApiKeyStore(),
        credentials=MemoryCredentialStore(),
        sessions=MemorySessionStore(),
        principals=MemoryPrincipalStore(),
    )
