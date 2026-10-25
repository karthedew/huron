"""Structural conformance of shared adapters at the API wiring boundary."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from huron.core.catalog.ports import (
    CreationStore,
    CreationTransaction,
    DescriptionStore,
    DescriptionTransaction,
)
from huron.core.security.facts import CatalogFacts

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager


class Mutation(CreationTransaction, DescriptionTransaction, Protocol):
    """The capabilities one shared adapter transaction structurally supplies."""


class HierarchyStore(CreationStore, DescriptionStore, CatalogFacts, Protocol):
    """A single adapter supplies independent consumer-owned views over one connection."""

    def transaction(self) -> AbstractAsyncContextManager[Mutation]:
        """Open the shared adapter's transaction.

        Returns:
            A writer structurally satisfying each consumer's narrow mutation port.
        """
        ...
