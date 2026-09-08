"""Authorized Huron workflows for authenticated, trusted application entry points.

Construct adapters at a composition root, bind an authenticated Principal through
AccessPolicy, and invoke these services. Underscore modules implement internal
persistence and ingestion mechanics; they are not caller-facing authorization boundaries.
A remote SDK authenticates through the API rather than instantiating server services.
"""

from .access import AccessPolicy
from .catalog import CatalogService
from .identity import IdentityService
from .raw import RawIngestionService
from .revisions import RevisionReadService

__all__ = [
    "AccessPolicy",
    "CatalogService",
    "IdentityService",
    "RawIngestionService",
    "RevisionReadService",
]
