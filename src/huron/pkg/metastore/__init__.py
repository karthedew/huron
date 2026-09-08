"""Persistence adapters with one module per capability.

In-memory and PostgreSQL implementations share behavioral contracts. Core owns
the persistence protocols; these adapters conform structurally without importing
core. Records and persistence values belong to catalog; credential protocols and
values belong to auth. Applications construct adapters at their composition root.
"""

from huron.pkg.catalog.persistence import IdempotencyClaim, LedgerEntry, Replay, Window
from huron.pkg.catalog.records import AuditEvent
from huron.pkg.rbac import Visibility

from .api_keys import PostgresApiKeyStore
from .credentials import PostgresCredentialStore
from .hierarchy import InMemoryHierarchyStore, PostgresHierarchyStore, SystemClock
from .principals import PostgresPrincipalStore
from .rbac import InMemoryRbacStore, PostgresRbacStore
from .sessions import PostgresSessionStore

__all__ = [
    "AuditEvent",
    "IdempotencyClaim",
    "InMemoryHierarchyStore",
    "InMemoryRbacStore",
    "LedgerEntry",
    "PostgresApiKeyStore",
    "PostgresCredentialStore",
    "PostgresHierarchyStore",
    "PostgresPrincipalStore",
    "PostgresRbacStore",
    "PostgresSessionStore",
    "Replay",
    "SystemClock",
    "Visibility",
    "Window",
]
