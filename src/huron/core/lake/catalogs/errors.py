"""Catalog errors."""

from __future__ import annotations

from huron.pkg.errors import HuronError, NotFound, register

__all__ = ["CatalogNotEmpty", "CatalogNotFound"]

CATALOG_NOT_EMPTY = register("CATALOG_NOT_EMPTY", 409, "Catalog not empty")


class CatalogNotEmpty(HuronError):
    """The catalog still has namespaces."""

    error_code = CATALOG_NOT_EMPTY


class CatalogNotFound(NotFound):
    """The catalog does not exist, or the caller may not see it."""

    def __init__(self, name: str) -> None:
        super().__init__(f"catalog {name!r} not found", {"catalog": name})
