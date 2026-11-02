"""Catalog errors."""

from __future__ import annotations

from huron.pkg.errors import HuronError, register

__all__ = ["CatalogNotEmpty"]

CATALOG_NOT_EMPTY = register("CATALOG_NOT_EMPTY", 409, "Catalog not empty")


class CatalogNotEmpty(HuronError):
    """The catalog still has namespaces."""

    error_code = CATALOG_NOT_EMPTY
