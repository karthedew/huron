"""The actual authorized release workflow for tests that seed existing repository fixtures."""

from __future__ import annotations

from typing import TYPE_CHECKING

from huron.core.access import AccessPolicy
from huron.core.releases import Releases
from huron.pkg.auth import Principal
from huron.pkg.rbac import RoleBindingAuthorizer

if TYPE_CHECKING:
    from huron.core._catalog import HierarchyRepository


def releases_for(repository: HierarchyRepository, *, visible: bool = True) -> Releases:
    """Bind a seeded owner or an undiscovering actor to the real release workflow."""
    access = AccessPolicy(
        Principal("tester" if visible else "outsider"),
        repository.hierarchy,
        repository.rbac,
        RoleBindingAuthorizer(),
    )
    return Releases(access, repository.hierarchy, repository.raw_store)
