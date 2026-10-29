"""An in-test grant reader with a fixed catalog → organization map."""

import uuid
from collections.abc import Iterable, Mapping, Sequence

from huron.core.security.rbac import PLATFORM, Grant, Role, Scope, ScopeType


class FakeGrantReader:
    """Grants held in a list; catalogs mapped to their organizations."""

    def __init__(self, grants: Iterable[Grant], catalogs: Mapping[uuid.UUID, uuid.UUID]) -> None:
        self.grants = list(grants)
        self.catalogs = dict(catalogs)

    async def roles_for_groups(self, groups: Iterable[str]) -> Sequence[tuple[Scope, Role]]:
        wanted = set(groups)
        return [(g.scope, g.role) for g in self.grants if g.ldap_group in wanted]

    async def groups_for_scope(self, scope: Scope) -> Mapping[Role, Sequence[str]]:
        found: dict[Role, list[str]] = {}
        for grant in self.grants:
            if grant.scope == scope:
                found.setdefault(grant.role, []).append(grant.ldap_group)
        return found

    async def enclosing(self, scope: Scope) -> Sequence[Scope]:
        if scope.type is ScopeType.CATALOG:
            assert scope.id is not None
            organization = self.catalogs.get(scope.id)
            if organization is None:
                return [scope, PLATFORM]
            return [scope, Scope.organization(organization), PLATFORM]
        if scope.type is ScopeType.ORGANIZATION:
            return [scope, PLATFORM]
        return [PLATFORM]
