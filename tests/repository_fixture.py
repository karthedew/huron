"""A test-seeded storage bundle, standing in for what application startup wires.

Direct-core tests construct one hierarchy adapter, one RBAC adapter and one
raw store together, exactly as ``create_app``'s lifespan does, without going
through a retired catalog facade to reach them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from huron.applications.api.capabilities import HierarchyStore, Storage
    from huron.core.security.ports import RbacStore


@dataclass(frozen=True, slots=True)
class RepositoryFixture:
    """The three storage capabilities a test wires directly.

    Attributes:
        raw_store: Durable-document storage; initialized on construction,
            exactly as application startup initializes it before serving.
        hierarchy: The hierarchy adapter under test.
        rbac: The RBAC adapter under test.
    """

    raw_store: Storage
    hierarchy: HierarchyStore
    rbac: RbacStore

    def __post_init__(self) -> None:
        """Initialize the raw store's directory layout."""
        self.raw_store.initialize()
