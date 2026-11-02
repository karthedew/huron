"""The namespace tree of a catalog with its collections as leaves, for ``huron tree``."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from rich.text import Text
from rich.tree import Tree

from huron.applications.cli.client import ApiClient
from huron.applications.cli.inventory import walk_namespaces

__all__ = ["build_tree", "render_tree"]


def build_tree(
    api: ApiClient, catalog: str, namespace: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """The tree of ``catalog``, or under ``namespace`` (its API view), as nested mappings.

    The root holds ``catalog``, ``namespace`` (its path; ``None`` for the whole catalog), the
    collections directly in that namespace and its child ``namespaces``; a subtree's root also holds
    ``collections_allowed``. Each namespace node holds its ``name``, ``identifier``,
    ``collections_allowed``, ``collections`` and ``namespaces``. Collection leaves hold their full
    ``identifier``, ``name`` and ``state``.
    """
    root: dict[str, Any] = {"catalog": catalog, "namespace": None}
    path = ""
    if namespace is not None:
        path = str(namespace["path"])
        root.update(
            namespace=path,
            collections_allowed=namespace["collections_allowed"],
            collections=_collections(api, catalog, path),
        )
    root.setdefault("collections", [])
    root["namespaces"] = []
    nodes: dict[str, dict[str, Any]] = {path: root}
    for view in walk_namespaces(api, catalog, path):
        node = {
            "name": view["name"],
            "identifier": view["identifier"],
            "collections_allowed": view["collections_allowed"],
            "collections": _collections(api, catalog, view["path"]),
            "namespaces": [],
        }
        nodes[view["path"]] = node
        parent = str(view["path"]).rpartition(".")[0]
        nodes.get(parent, root)["namespaces"].append(node)
    return root


def render_tree(tree: Mapping[str, Any]) -> Tree:
    """A rich tree rooted at the catalog's name, collections as leaves of namespaces (``name/``).

    A subtree hangs from one branch named by its namespace path.
    """
    root = Tree(Text(str(tree["catalog"]), style="bold"))
    top = root if tree["namespace"] is None else root.add(_branch(tree["namespace"], tree))
    _fill(top, tree)
    return root


def _collections(api: ApiClient, catalog: str, path: str) -> list[dict[str, Any]]:
    listing = api.pages(f"/api/v1/catalogs/{catalog}/namespaces/{path}/collections")
    return [
        {"identifier": item["identifier"], "name": item["name"], "state": item["state"]}
        for item in listing
    ]


def _fill(branch: Tree, node: Mapping[str, Any]) -> None:
    for child in node["namespaces"]:
        _fill(branch.add(_branch(child["name"], child)), child)
    for collection in node["collections"]:
        branch.add(
            Text.assemble(str(collection["identifier"]), (f"  {collection['state']}", "dim"))
        )


def _branch(name: str, node: Mapping[str, Any]) -> Text:
    note = "collections allowed" if node["collections_allowed"] else "no collections"
    return Text.assemble((f"{name}/", "bold"), (f"  ({note})", "dim"))
