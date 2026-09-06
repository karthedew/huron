"""Storage adapters for the API tier: one module per port.

The package is organised by port, not by backend: ``ports`` declares the
four Protocols this tier owns (``RbacStore``, ``ApiKeyWriter``,
``HierarchyWriter``, ``HierarchyStore``) and the values that go with them
(``IdempotencyClaim``, ``LedgerEntry``, ``Replay``, ``Window``), and each
other module holds every implementation of one port - the in-memory
reference store beside the Postgres one where both exist. ``Visibility`` is
re-exported here from ``huron.pkg.rbac`` because it is a parameter of the
hierarchy port's read methods, and this package's public surface is where
every other consumer imports store-related types from. This module is the
package's only public surface; ``repository``, ``app``, ``authorization``
and the routes import the names below and never a submodule, which
import-linter enforces. What is exported: the four ports and their values,
``AuditEvent``, ``SystemClock``, ``InMemoryRbacStore``,
``InMemoryHierarchyStore``, and the six Postgres stores that share one
``asyncpg`` pool.
"""

from huron.pkg.rbac import Visibility
from huron.service.api.records import AuditEvent

from .api_keys import PostgresApiKeyStore
from .credentials import PostgresCredentialStore
from .hierarchy import InMemoryHierarchyStore, PostgresHierarchyStore, SystemClock
from .ports import (
    ApiKeyWriter,
    HierarchyStore,
    HierarchyWriter,
    IdempotencyClaim,
    LedgerEntry,
    RbacStore,
    Replay,
    Window,
)
from .principals import PostgresPrincipalStore
from .rbac import InMemoryRbacStore, PostgresRbacStore
from .sessions import PostgresSessionStore

__all__ = [
    "ApiKeyWriter",
    "AuditEvent",
    "HierarchyStore",
    "HierarchyWriter",
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
    "RbacStore",
    "Replay",
    "SystemClock",
    "Visibility",
    "Window",
]
