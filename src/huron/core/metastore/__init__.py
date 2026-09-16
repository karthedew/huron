"""Persistence adapters with one module per capability.

In-memory and PostgreSQL implementations share behavioral contracts. Core owns
the persistence protocols; adapters conform structurally to each consumer's narrow
view. Records belong to their domains and generic retry values to Foundation.
Applications construct adapters and own their resource lifetimes.
"""

from .api_keys import PostgresApiKeyStore
from .credentials import PostgresCredentialStore
from .hierarchy import InMemoryHierarchyStore, PostgresHierarchyStore, SystemClock
from .memory_apikeys import MemoryApiKeyStore
from .memory_password import MemoryCredentialStore
from .memory_principals import MemoryPrincipalStore
from .memory_sessions import MemorySessionStore
from .principals import PostgresPrincipalStore
from .rbac import InMemoryRbacStore, PostgresRbacStore
from .sessions import PostgresSessionStore

__all__ = [
    "InMemoryHierarchyStore",
    "InMemoryRbacStore",
    "MemoryApiKeyStore",
    "MemoryCredentialStore",
    "MemoryPrincipalStore",
    "MemorySessionStore",
    "PostgresApiKeyStore",
    "PostgresCredentialStore",
    "PostgresHierarchyStore",
    "PostgresPrincipalStore",
    "PostgresRbacStore",
    "PostgresSessionStore",
    "SystemClock",
]
