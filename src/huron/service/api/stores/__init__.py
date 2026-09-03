"""Storage adapters for the API tier: one module per port.

The package is organised by port, not by backend: ``ports`` declares the
two Protocols this tier owns (``RbacStore``, ``ApiKeyWriter``), and each
other module holds every implementation of one port - the in-memory
reference store beside the Postgres one where both exist. This module is
the package's only public surface; ``repository``, ``app``,
``authorization`` and the routes import the names below and never a
submodule, which import-linter enforces. What is exported: the two ports,
``InMemoryRbacStore``, and the five Postgres stores that share one
``asyncpg`` pool.
"""

from .api_keys import PostgresApiKeyStore
from .credentials import PostgresCredentialStore
from .ports import ApiKeyWriter, RbacStore
from .principals import PostgresPrincipalStore
from .rbac import InMemoryRbacStore, PostgresRbacStore
from .sessions import PostgresSessionStore

__all__ = [
    "ApiKeyWriter",
    "InMemoryRbacStore",
    "PostgresApiKeyStore",
    "PostgresCredentialStore",
    "PostgresPrincipalStore",
    "PostgresRbacStore",
    "PostgresSessionStore",
    "RbacStore",
]
