"""Group-to-role reads over committed lake mappings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from huron.core.security.broker import Grant, Role

if TYPE_CHECKING:
    from huron.core.metastore.lake.memory import LakeTables


class InMemoryRoleMappings:
    """Read the current scoped grants for the requested directory groups."""

    tables: LakeTables

    async def roles_for_groups(self, groups: frozenset[str]) -> tuple[Grant, ...]:
        """Translate matching rows into validated scoped grants.

        Args:
            groups: Directory groups carried by the authenticated identity.

        Returns:
            One grant per matching row, with no contribution from unknown groups.

        Raises:
            ValueError: If a stored role or its scope is invalid.
        """
        grants = []
        for row in self.tables.group_role_map.values():
            if row.ldap_group not in groups:
                continue
            role = Role.from_code(row.role_code)
            expected_scope = "catalog" if role.catalog_scoped else "organization"
            if row.role_scope != expected_scope:
                raise ValueError("Stored role scope does not match its role")
            grants.append(Grant(role, row.catalog))
        return tuple(grants)
