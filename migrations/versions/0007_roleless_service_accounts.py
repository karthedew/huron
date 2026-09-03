"""Service accounts hold no roles: their authority is intrinsic.

An organization service account exists for exactly one thing - letting an
external pipeline authenticate and CRUD its organization's datasets at the
silver and gold layers. That authority is a property of the principal kind,
synthesized at decision time from the ``service_accounts`` row
(``huron.pkg.rbac.roles.service_account_bindings``), so it is conferred in
whole when the org admin creates the account and revoked in whole with the
account or its keys - never granted, shaped, or widened through bindings.

Consequences here:

- the ``pipeline`` and ``ingest_pipeline`` roles and every binding to them
  are deleted; no role in the vocabulary carries silver/gold ``data.write``
  any more, so no binding can leak it to a human (invariant J holds by
  construction);
- ``reader`` becomes user-only - every remaining role is - and
  ``role_binding_guard`` now refuses any ``sa:`` principal outright, with
  an error that says where SA authority actually comes from;
- Huron's internal platform services (intake, builder, canonicalizer,
  retention, projection) are deployment identities, not organization
  service accounts, and are untouched.

The seed mirrors ``huron.pkg.rbac.roles.ROLES`` (changed there first, same
convention as 0002/0004/0005/0006).
"""

from migrations._ddl import execute_sql

revision = "0007_roleless_service_accounts"
down_revision = "0006_role_simplification"
branch_labels = None
depends_on = None


DDL = r"""
-- ------------------------------------------------------ pipeline roles out
DELETE FROM role_bindings WHERE role_code IN ('pipeline', 'ingest_pipeline');
DELETE FROM role_capabilities WHERE role_code IN ('pipeline', 'ingest_pipeline');
DELETE FROM roles WHERE code IN ('pipeline', 'ingest_pipeline');

-- ------------------------------------------------------- roles are human-only
UPDATE roles SET allowed_principal_kinds = ARRAY['user'] WHERE code = 'reader';

-- ------------------------------------------- bindings never name an sa: principal
DELETE FROM role_bindings WHERE principal LIKE 'sa:%';
CREATE OR REPLACE FUNCTION role_binding_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    role_row roles%ROWTYPE;
    principal_kind text;
BEGIN
    IF NEW.principal LIKE 'sa:%' THEN
        RAISE EXCEPTION 'service accounts hold no roles; their authority is intrinsic';
    END IF;
    SELECT * INTO role_row FROM roles WHERE code = NEW.role_code;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'unknown role %', NEW.role_code;
    END IF;
    principal_kind := CASE
        WHEN NEW.principal LIKE 'user:%' THEN 'user'
        WHEN NEW.principal LIKE 'group:%' THEN 'user'  -- groups are sets of users
        ELSE NULL
    END;
    IF principal_kind IS NULL THEN
        RAISE EXCEPTION 'principal must start with user: or group:';
    END IF;
    IF NOT (principal_kind = ANY (role_row.allowed_principal_kinds)) THEN
        RAISE EXCEPTION 'role % may not be held by % principals',
            NEW.role_code, principal_kind;
    END IF;
    IF NOT (NEW.scope_type = ANY (role_row.bindable_scopes)) THEN
        RAISE EXCEPTION 'role % cannot be bound at % scope',
            NEW.role_code, NEW.scope_type;
    END IF;
    RETURN NEW;
END $$;
"""


def upgrade() -> None:
    """Retire the pipeline roles, delete every ``sa:`` binding and refuse new ones in the guard."""
    execute_sql(DDL)


def downgrade() -> None:
    """Restore the pipeline roles and the binding guard that accepts ``sa:`` principals."""
    execute_sql(r"""
    UPDATE roles SET allowed_principal_kinds = ARRAY['user','service_account']
     WHERE code = 'reader';
    INSERT INTO roles (code, title, description, allowed_principal_kinds, bindable_scopes)
    VALUES
      ('pipeline', 'Pipeline',
       'Writes bronze, silver and gold for datasets that already exist.',
       ARRAY['service_account'], ARRAY['PROJECT','DATASET']),
      ('ingest_pipeline', 'Ingest Pipeline',
       'Pipeline plus dataset.create, for feeds originating outside the lake.',
       ARRAY['service_account'], ARRAY['PROJECT']);
    INSERT INTO role_capabilities (role_code, capability_code, layers) VALUES
      ('pipeline', 'dataset.discover', NULL),
      ('pipeline', 'data.read', NULL),
      ('pipeline', 'data.write', ARRAY['bronze','silver','gold']),
      ('ingest_pipeline', 'dataset.discover', NULL),
      ('ingest_pipeline', 'dataset.create', NULL),
      ('ingest_pipeline', 'data.read', NULL),
      ('ingest_pipeline', 'data.write', ARRAY['bronze','silver','gold']);
    CREATE OR REPLACE FUNCTION role_binding_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE
        role_row roles%ROWTYPE;
        principal_kind text;
    BEGIN
        SELECT * INTO role_row FROM roles WHERE code = NEW.role_code;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'unknown role %', NEW.role_code;
        END IF;
        principal_kind := CASE
            WHEN NEW.principal LIKE 'sa:%' THEN 'service_account'
            WHEN NEW.principal LIKE 'user:%' THEN 'user'
            WHEN NEW.principal LIKE 'group:%' THEN 'user'
            ELSE NULL
        END;
        IF principal_kind IS NULL THEN
            RAISE EXCEPTION 'principal must start with user:, group:, or sa:';
        END IF;
        IF NOT (principal_kind = ANY (role_row.allowed_principal_kinds)) THEN
            RAISE EXCEPTION 'role % may not be held by % principals',
                NEW.role_code, principal_kind;
        END IF;
        IF NOT (NEW.scope_type = ANY (role_row.bindable_scopes)) THEN
            RAISE EXCEPTION 'role % cannot be bound at % scope',
                NEW.role_code, NEW.scope_type;
        END IF;
        RETURN NEW;
    END $$;
    """)
