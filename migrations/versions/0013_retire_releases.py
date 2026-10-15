"""Retire Raw release tags: a dataset keeps only its full, numbered revisions.

Dropping ``releases`` also drops its indexes, constraints and the
``releases_immutable_before_update`` trigger; the trigger function is a
separate object and goes next. The ``release.create`` grants go before the
capability itself, because ``role_capabilities_capability_code_fkey`` refuses
to delete a capability a role still grants. The developer role's description
drops tagging to match ``huron.core.security.roles.ROLES``.
"""

from migrations._ddl import execute_sql

revision = "0013_retire_releases"
down_revision = "0012_raw_web_catalogs"
branch_labels = None
depends_on = None

DDL = """
DROP TABLE releases;
DROP FUNCTION releases_immutable();
DELETE FROM role_capabilities WHERE capability_code = 'release.create';
DELETE FROM capabilities WHERE code = 'release.create';
UPDATE roles SET description = 'Commit to raw and bronze; create and update datasets.'
    WHERE code = 'developer';
"""


def upgrade() -> None:
    """Drop release tags, their trigger function and the capability that created them."""
    execute_sql(DDL)


def downgrade() -> None:
    """Refuse recreating release tags whose rows the upgrade dropped.

    Raises:
        RuntimeError: Always; dropped release tags cannot be restored online.
    """
    raise RuntimeError("retired release tags cannot be restored online")
