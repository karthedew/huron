"""Role simplification: the data-steward role is removed and the dataset activation gate with it.

The steward's only capability delta over ``developer`` was
``dataset.policy_attach``, which the admin roles already hold - a whole role
for one act. Governance moved to the admins by scope (project admins:
amendments, publication approval, project policies; organization admins:
organization schemas and policies), and what gates dataset creation is the
inherited policy chain, not a human checklist:

- the ``data_steward`` role and its rows are deleted (bindings first - any
  existing steward binding is simply gone, and the affected principal is
  re-granted ``developer`` or ``project_admin`` by an admin as appropriate);
- datasets are ACTIVE on creation: the ``DRAFT`` default and every existing
  ``DRAFT`` row are lifted to ``ACTIVE``;
- ``projects.dataset_creation_mode`` - the per-project steward-approval
  switch - is dropped outright.

The seed mirrors ``huron.pkg.rbac.roles.ROLES`` (changed there first, same
convention as 0002/0004/0005).
"""

from migrations._ddl import execute_sql

revision = "0006_role_simplification"
down_revision = "0005_auth"
branch_labels = None
depends_on = None


DDL = r"""
-- ------------------------------------------------------------ role removal
DELETE FROM role_bindings WHERE role_code = 'data_steward';
DELETE FROM role_capabilities WHERE role_code = 'data_steward';
DELETE FROM roles WHERE code = 'data_steward';

-- ------------------------------------------------- datasets: no draft gate
UPDATE datasets SET lifecycle_state = 'ACTIVE' WHERE lifecycle_state = 'DRAFT';
ALTER TABLE datasets ALTER COLUMN lifecycle_state SET DEFAULT 'ACTIVE';

-- ------------------------------------- projects: steward-approval switch
ALTER TABLE projects DROP COLUMN dataset_creation_mode;
"""


def upgrade() -> None:
    """Delete ``data_steward``, lift DRAFT datasets to ACTIVE and drop the creation-mode column."""
    execute_sql(DDL)


def downgrade() -> None:
    """Restore the creation-mode column, the DRAFT default and the ``data_steward`` role."""
    execute_sql(r"""
    ALTER TABLE projects
      ADD COLUMN dataset_creation_mode text NOT NULL DEFAULT 'steward_approval';
    ALTER TABLE datasets ALTER COLUMN lifecycle_state SET DEFAULT 'DRAFT';
    INSERT INTO roles (code, title, description, allowed_principal_kinds, bindable_scopes)
    VALUES ('data_steward', 'Data Steward',
            'Developer plus dataset policy; shapes silver/gold via pipelines only.',
            ARRAY['user'], ARRAY['ORGANIZATION','PROJECT','DATASET']);
    INSERT INTO role_capabilities (role_code, capability_code, layers) VALUES
      ('data_steward', 'dataset.discover', NULL),
      ('data_steward', 'dataset.create', NULL),
      ('data_steward', 'dataset.update', NULL),
      ('data_steward', 'dataset.policy_attach', NULL),
      ('data_steward', 'release.create', NULL),
      ('data_steward', 'data.read', NULL),
      ('data_steward', 'data.write', ARRAY['raw','bronze']);
    """)
