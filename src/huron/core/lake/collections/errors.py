"""Collection errors."""

from __future__ import annotations

from huron.pkg.errors import HuronError, register

__all__ = ["CollectionNotEmpty", "CollectionsNotAllowed", "MetadataInvalid"]

METADATA_INVALID = register("METADATA_INVALID", 422, "Metadata invalid")
COLLECTION_NOT_EMPTY = register("COLLECTION_NOT_EMPTY", 409, "Collection not empty")
COLLECTIONS_NOT_ALLOWED = register("COLLECTIONS_NOT_ALLOWED", 409, "Collections not allowed")


class MetadataInvalid(HuronError):
    """Metadata does not validate against the schema; ``context.problems`` lists why."""

    error_code = METADATA_INVALID


class CollectionNotEmpty(HuronError):
    """The collection still has recorded files."""

    error_code = COLLECTION_NOT_EMPTY


class CollectionsNotAllowed(HuronError):
    """The namespace does not allow collections."""

    error_code = COLLECTIONS_NOT_ALLOWED
