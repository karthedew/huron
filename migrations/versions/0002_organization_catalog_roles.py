"""Catalog roles at organization scope: every catalog of the organization inherits them.

Revision ID: 0002_organization_catalog_roles
Revises: 0001_huron
Create Date: 2026-10-31 00:00:00.000000

The downgrade deletes the organization-scope catalog-role grants, which version 1 cannot hold.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002_organization_catalog_roles"
down_revision: str | None = "0001_huron"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CATALOG_ROLES = "('catalog_admin', 'contributor', 'reader')"
_PLATFORM_AND_ORG = (
    "(role = 'platform_admin' and scope_type = 'platform')"
    " or (role = 'org_admin' and scope_type = 'organization')"
)


def upgrade() -> None:
    """Allow the catalog roles at organization scope."""
    op.drop_constraint(op.f("ck_grants_role_scope"), "grants", type_="check", schema="huron")
    op.create_check_constraint(
        op.f("ck_grants_role_scope"),
        "grants",
        f"{_PLATFORM_AND_ORG} or (role in {_CATALOG_ROLES}"
        " and scope_type in ('organization', 'catalog'))",
        schema="huron",
    )


def downgrade() -> None:
    """Delete organization-scope catalog-role grants and restore the version-1 rule."""
    op.execute(
        f"delete from huron.grants where scope_type = 'organization' and role in {_CATALOG_ROLES}"
    )
    op.drop_constraint(op.f("ck_grants_role_scope"), "grants", type_="check", schema="huron")
    op.create_check_constraint(
        op.f("ck_grants_role_scope"),
        "grants",
        f"{_PLATFORM_AND_ORG} or (role in {_CATALOG_ROLES} and scope_type = 'catalog')",
        schema="huron",
    )
