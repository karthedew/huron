"""The actual authorized release workflow for tests that seed existing repository fixtures."""

from __future__ import annotations

from typing import TYPE_CHECKING

from huron.core.security import AccessPolicy
from huron.core.raw import Releases
from huron.core.security.principal import Principal
from huron.core.security.rules import RoleBindingAuthorizer

if TYPE_CHECKING:
    from tests.repository_fixture import RepositoryFixture


def releases_for(repository: RepositoryFixture, *, visible: bool = True) -> Releases:
    """Bind a seeded owner or an undiscovering actor to the real release workflow."""
    access = AccessPolicy(
        Principal("tester" if visible else "outsider"),
        repository.hierarchy,
        repository.rbac,
        RoleBindingAuthorizer(),
    )
    return Releases(access, repository.hierarchy, repository.raw_store)
