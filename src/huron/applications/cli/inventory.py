"""What the service records about a catalog, gathered for ``check`` and ``acl apply``."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from huron.applications.cli.client import ApiClient
from huron.applications.cli.sync import recorded_files
from huron.core.storage import DirectoryKind, EffectiveGroups

__all__ = ["CatalogInventory", "take_inventory"]


@dataclass(frozen=True, slots=True)
class CatalogInventory:
    """A catalog's namespaces and collections as the service records them."""

    catalog: dict[str, Any]
    groups: EffectiveGroups
    namespaces: list[dict[str, Any]]
    collections: list[dict[str, Any]]

    @property
    def disk_path(self) -> str:
        """The catalog directory relative to the share prefix."""
        return f"{self.catalog['organization']}/{self.catalog['name']}"

    def directories(self) -> Iterator[tuple[str, str, DirectoryKind]]:
        """``(identifier, disk_path, kind)`` of every directory, catalog first, parents first."""
        yield self.catalog["name"], self.disk_path, DirectoryKind.CATALOG
        for namespace in self.namespaces:
            kind = (
                DirectoryKind.NAMESPACE_WITH_COLLECTIONS
                if namespace["collections_allowed"]
                else DirectoryKind.NAMESPACE
            )
            yield namespace["identifier"], namespace["disk_path"], kind
        for collection in self.collections:
            if collection.get("path"):
                yield collection["identifier"], collection["path"], DirectoryKind.COLLECTION


def take_inventory(api: ApiClient, catalog: str, *, files: bool) -> CatalogInventory:
    """Walk the catalog's namespace tree and collections; with ``files``, their recorded files."""
    found = api.get(f"/api/v1/catalogs/{catalog}")
    groups = EffectiveGroups.from_mapping(api.get(f"/api/v1/catalogs/{catalog}/grants"))
    namespaces = list(_walk(api, catalog, ""))
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
    return CatalogInventory(found, groups, namespaces, collections)


def _walk(api: ApiClient, catalog: str, parent: str) -> Iterator[dict[str, Any]]:
    for namespace in api.pages(f"/api/v1/catalogs/{catalog}/namespaces", {"parent": parent}):
        yield namespace
        if namespace["namespace_count"]:
            yield from _walk(api, catalog, namespace["path"])
