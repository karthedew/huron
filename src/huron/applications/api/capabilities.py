"""Structural conformance of shared adapters at the API wiring boundary."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from huron.core.catalog.external import ExternalDatasetStore
from huron.core.catalog.ports import (
    CreationStore,
    CreationTransaction,
    DescriptionStore,
    DescriptionTransaction,
    GenerationStorage,
)
from huron.core.raw.ports import HierarchyStore as RawPersistence
from huron.core.raw.ports import HierarchyWriter, RawStore, ReleaseStore, ReleaseTransaction
from huron.core.raw.web_ports import RawPublicationStore
from huron.core.security.facts import CatalogFacts

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager


class Mutation(
    CreationTransaction, DescriptionTransaction, HierarchyWriter, ReleaseTransaction, Protocol
):
    """The capabilities one shared adapter transaction structurally supplies."""


class HierarchyStore(
    CreationStore, DescriptionStore, RawPersistence, ReleaseStore, CatalogFacts, Protocol
):
    """A single adapter supplies independent consumer-owned views over one connection."""

    def transaction(self) -> AbstractAsyncContextManager[Mutation]:
        """Open the shared adapter's transaction.

        Returns:
            A writer structurally satisfying each consumer's narrow mutation port.
        """
        ...


class Storage(RawStore, GenerationStorage, Protocol):
    """One POSIX adapter supplies both generation and Raw storage capabilities."""


class RawWebPersistence(ExternalDatasetStore, RawPublicationStore, Protocol):
    """One adapter supplies durable catalog mappings and publication receipts."""
