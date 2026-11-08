"""What the service records about a catalog, for ``adm check`` and ``tree``."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from huron.applications.cli.client import ApiClient
from huron.applications.cli.sync import recorded_files

__all__ = ["CatalogInventory", "take_inventory", "walk_namespaces"]


@dataclass(frozen=True, slots=True)
class CatalogInventory:
    """A catalog's namespaces and collections as the service records them."""

    catalog: dict[str, Any]
    namespaces: list[dict[str, Any]]
    collections: list[dict[str, Any]]

    @property
    def disk_path(self) -> str:
        """The catalog directory relative to the share prefix."""
        return f"{self.catalog['organization']}/{self.catalog['name']}"

    def directories(self) -> Iterator[tuple[str, str]]:
        """``(identifier, disk_path)`` of the catalog and its namespaces, parents first.

        The collections are in :attr:`collections`.
        """
        yield self.catalog["name"], self.disk_path
        for namespace in self.namespaces:
            yield namespace["identifier"], namespace["disk_path"]


def take_inventory(api: ApiClient, catalog: str, *, files: bool) -> CatalogInventory:
    """Walk the catalog's namespace tree and collections; with ``files``, their recorded files."""
    found = api.get(f"/api/v1/catalogs/{catalog}")
    namespaces = list(walk_namespaces(api, catalog, ""))
    collections: list[dict[str, Any]] = []
    for namespace in namespaces:
        path = f"/api/v1/catalogs/{catalog}/namespaces/{namespace['path']}/collections"
        for collection in api.pages(path):
            if files and collection.get("path"):
                collection["files"] = recorded_files(api, collection["id"])
                sidecar = api.request(
                    "GET", f"/api/v1/collections/{collection['id']}/metadata.json"
                )
                collection["sidecar"] = sidecar.content
            collection["created"] = datetime.fromisoformat(collection["created_at"])
            collections.append(collection)
    return CatalogInventory(found, namespaces, collections)


def walk_namespaces(api: ApiClient, catalog: str, parent: str) -> Iterator[dict[str, Any]]:
    """Every namespace below ``parent`` (a path; empty for the top), each before its children."""
    for namespace in api.pages(f"/api/v1/catalogs/{catalog}/namespaces", {"parent": parent}):
        yield namespace
        if namespace["namespace_count"]:
            yield from walk_namespaces(api, catalog, namespace["path"])
