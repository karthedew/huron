"""The ``grants`` table: roles granted to LDAP groups."""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Index,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
)

from huron.core.metastore.tables import metadata

__all__ = ["grants"]

grants = Table(
    "grants",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("scope_type", Text, nullable=False),
    Column("scope_id", Uuid, nullable=True),
    Column("role", Text, nullable=False),
    Column("ldap_group", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("created_by", Text, nullable=False),
    UniqueConstraint(
        "scope_type", "scope_id", "role", "ldap_group", postgresql_nulls_not_distinct=True
    ),
    CheckConstraint("(scope_type = 'platform') = (scope_id is null)", name="scope_id"),
    CheckConstraint(
        "(role = 'platform_admin' and scope_type = 'platform')"
        " or (role = 'org_admin' and scope_type = 'organization')"
        " or (role in ('catalog_admin', 'contributor', 'reader') and scope_type = 'catalog')",
        name="role_scope",
    ),
    Index(None, "ldap_group"),
    Index(None, "scope_type", "scope_id"),
)
