"""Response bodies owned by ``endpoints/roles.py``."""

from __future__ import annotations

from pydantic import BaseModel

from huron.pkg.catalog.layers import Layer
from huron.pkg.rbac import ScopeType


class LayerGrantView(BaseModel):
    """A data-plane capability limited to a set of layers.

    ``layers`` is ``null`` when the grant reaches every layer, mirroring
    ``Binding.layers`` rather than expanding it - the two are different
    statements and a client that flattens them loses the distinction.
    """

    capability: str
    layers: list[Layer] | None


class RoleView(BaseModel):
    """One role in the catalog: what it can do and who may hold it.

    Every collection field is sorted, because the role model stores them as
    frozensets and a frozenset's iteration order is not stable across
    processes.
    """

    code: str
    title: str
    description: str
    capabilities: list[str]
    layer_grants: list[LayerGrantView]
    bindable_scopes: list[ScopeType]
    allowed_principal_kinds: list[str]
