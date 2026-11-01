"""Pick a collection by walking a catalog's namespaces, for ``huron checkout`` without arguments."""

from __future__ import annotations

from huron.applications.cli.client import ApiClient
from huron.applications.cli.errors import UsageError
from huron.applications.cli.prompts import Prompter

__all__ = ["UP", "CollectionPicker"]

UP = ".."


class CollectionPicker:
    """Asks, one namespace level at a time, until the user chooses a collection.

    Each level offers the child namespaces (``name/``), the collections directly in it and, below
    the top, ``..`` to go up. The top level of a catalog holds no collections.
    """

    def __init__(self, api: ApiClient, prompter: Prompter) -> None:
        self._api = api
        self._prompter = prompter

    def pick(self, catalog: str) -> str:
        """The full identifier of the chosen collection; refuses a catalog with no namespaces."""
        path = ""
        while True:
            choices = self._choices(catalog, path)
            if not choices:
                raise UsageError(
                    f"catalog {catalog} has no namespaces",
                    hint="to create one, run `huron create namespace <identifier>`",
                )
            where = f"{catalog}.{path}" if path else catalog
            question = (
                f"{where} is empty. Choose {UP} to go to the level above"
                if list(choices) == [UP]
                else f"{where}: choose a namespace (its name ends with /) or a collection"
            )
            kind, value = choices[self._prompter.select(question, list(choices))]
            if kind == "collection":
                return value
            path = value

    def _choices(self, catalog: str, path: str) -> dict[str, tuple[str, str]]:
        choices: dict[str, tuple[str, str]] = {}
        if path:
            choices[UP] = ("namespace", path.rpartition(".")[0])
        base = f"/api/v1/catalogs/{catalog}/namespaces"
        for namespace in self._api.pages(base, {"parent": path}):
            choices[f"{namespace['name']}/"] = ("namespace", str(namespace["path"]))
        if path:
            for collection in self._api.pages(f"{base}/{path}/collections"):
                choices[str(collection["name"])] = ("collection", str(collection["identifier"]))
        return choices
