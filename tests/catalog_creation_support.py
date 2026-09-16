"""Actual authorized creation workflows for tests that seed existing repository fixtures."""

from __future__ import annotations

from typing import TYPE_CHECKING

from huron.core.security import AccessPolicy
from huron.core.catalog import CatalogCreation
from huron.core.security.principal import Principal
from huron.core.security.rules import RoleBindingAuthorizer, ScopeType

if TYPE_CHECKING:
    from tests.repository_fixture import RepositoryFixture


async def creation_for(
    repository: RepositoryFixture,
    *,
    classifications: tuple[str, ...] = ("open",),
    visible: bool = True,
) -> CatalogCreation:
    """Bind a seeded owner or an undiscovering actor to the real creation workflow."""
    if visible:
        grants = await repository.rbac.bindings_at(ScopeType.SYSTEM, None)
        if not any(
            b.principal == "user:tester" and b.role_code == "platform_owner" for b in grants
        ):
            await repository.rbac.grant_role(
                principal="user:tester",
                role_code="platform_owner",
                scope_type=ScopeType.SYSTEM,
                scope_id=None,
                created_by="bootstrap",
            )
    access = AccessPolicy(
        Principal("tester" if visible else "outsider"),
        repository.hierarchy,
        repository.rbac,
        RoleBindingAuthorizer(),
    )
    return CatalogCreation(
        access,
        repository.hierarchy,
        repository.raw_store,
        classification_vocabulary=classifications,
    )
