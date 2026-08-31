"""RBAC: principals, service accounts, the role catalog, guarded bindings,
and policies.

The role/capability seed below mirrors ``huron.pkg.rbac.roles.ROLES`` - that
module is the source of truth and a contract test compares the two against a
migrated database. The operationally important invariants land here as
database rules, not application code:

- ``role_bindings_guard`` refuses a binding whose principal kind or scope
  level the role does not allow, so "silver/gold writers are service
  accounts" holds even for rows inserted with psql.
- ``service_accounts`` rows must reference a principal of kind
  ``service_account`` (``service_account_kind_guard``).
"""

from alembic import op

revision = "0002_rbac"
down_revision = "0001_foundations"
branch_labels = None
depends_on = None


DDL = r"""
-- ---------------------------------------------------------------- principals
-- One row per authenticatable subject, user or service account. The
-- ``subject`` is what tokens and bindings name; ``idp_subject`` ties a user
-- to the OIDC provider's stable ``sub`` claim.
CREATE TABLE principals (
    id uuid PRIMARY KEY,
    kind text NOT NULL CHECK (kind IN ('user', 'service_account')),
    subject text NOT NULL UNIQUE,
    display_name text NOT NULL DEFAULT '',
    idp_subject text UNIQUE,
    disabled_at timestamptz,
    created_at timestamptz NOT NULL,
    CHECK (kind = 'user' OR idp_subject IS NULL)
);

-- Service accounts are owned by an organization and may only be created by
-- principals holding ``service_account.manage`` there (enforced in the API;
-- the ownership row itself is enforced here).
CREATE TABLE service_accounts (
    principal_id uuid PRIMARY KEY REFERENCES principals(id),
    organization_id uuid NOT NULL REFERENCES organizations(id),
    name text NOT NULL CHECK (name ~ '^[a-z0-9][a-z0-9-]{1,61}$'),
    created_by text NOT NULL,
    created_at timestamptz NOT NULL,
    UNIQUE (organization_id, name)
);

CREATE FUNCTION service_account_kind_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE principal_kind text;
BEGIN
    SELECT kind INTO principal_kind FROM principals WHERE id = NEW.principal_id;
    IF principal_kind IS DISTINCT FROM 'service_account' THEN
        RAISE EXCEPTION 'service_accounts.principal_id must reference a service_account principal';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER service_accounts_kind_guard BEFORE INSERT OR UPDATE ON service_accounts
FOR EACH ROW EXECUTE FUNCTION service_account_kind_guard();

-- -------------------------------------------------------------- role catalog
-- 3NF: a role names a bundle; role_capabilities is the many-to-many with the
-- one role-dependent attribute (the layer restriction on data.* capabilities).
CREATE TABLE roles (
    code text PRIMARY KEY CHECK (code ~ '^[a-z][a-z0-9_]{1,62}$'),
    title text NOT NULL,
    description text NOT NULL DEFAULT '',
    allowed_principal_kinds text[] NOT NULL CHECK (
        allowed_principal_kinds <@ ARRAY['user', 'service_account']
        AND cardinality(allowed_principal_kinds) > 0
    ),
    bindable_scopes text[] NOT NULL CHECK (
        bindable_scopes <@ ARRAY['SYSTEM', 'ORGANIZATION', 'PROJECT', 'DATASET']
        AND cardinality(bindable_scopes) > 0
    ),
    is_system boolean NOT NULL DEFAULT true
);

CREATE TABLE capabilities (
    code text PRIMARY KEY CHECK (code ~ '^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$'),
    description text NOT NULL DEFAULT ''
);

CREATE TABLE role_capabilities (
    role_code text NOT NULL REFERENCES roles(code) ON DELETE CASCADE,
    capability_code text NOT NULL REFERENCES capabilities(code),
    -- NULL = every layer; non-NULL only makes sense for data.* capabilities.
    layers text[] CHECK (layers IS NULL OR layers <@ ARRAY['raw','bronze','silver','gold']),
    PRIMARY KEY (role_code, capability_code)
);

-- ------------------------------------------------------------- role_bindings
-- 0001 stored free-form capability arrays per binding; bindings now grant a
-- role and the capability expansion happens through role_capabilities.
ALTER TABLE role_bindings DROP COLUMN capabilities;
ALTER TABLE role_bindings RENAME COLUMN role TO role_code;
ALTER TABLE role_bindings
    ADD CONSTRAINT role_bindings_role_fk FOREIGN KEY (role_code) REFERENCES roles(code),
    ADD CONSTRAINT role_bindings_principal_format CHECK (
        principal ~ '^(user|group|sa):.+$'
    ),
    ADD CONSTRAINT role_bindings_no_duplicates
        UNIQUE NULLS NOT DISTINCT (principal, role_code, scope_type, scope_id);

CREATE FUNCTION role_binding_guard() RETURNS trigger LANGUAGE plpgsql AS $$
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
        WHEN NEW.principal LIKE 'group:%' THEN 'user'  -- groups are sets of users
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
CREATE TRIGGER role_bindings_guard BEFORE INSERT OR UPDATE ON role_bindings
FOR EACH ROW EXECUTE FUNCTION role_binding_guard();

-- ------------------------------------------------------------------ policies
CREATE TABLE policies (
    id uuid PRIMARY KEY,
    policy_type text NOT NULL CHECK (policy_type ~ '^[a-z][a-z0-9_]{1,62}$'),
    name text NOT NULL,
    spec jsonb NOT NULL,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL
);

CREATE TABLE policy_attachments (
    policy_id uuid NOT NULL REFERENCES policies(id),
    scope_type text NOT NULL CHECK (scope_type IN ('ORGANIZATION', 'PROJECT', 'DATASET')),
    scope_id uuid NOT NULL,
    attached_by text NOT NULL,
    attached_at timestamptz NOT NULL,
    PRIMARY KEY (policy_id, scope_type, scope_id)
);
CREATE INDEX policy_attachments_scope ON policy_attachments (scope_type, scope_id);

-- ------------------------------------------------------------------ api_keys
ALTER TABLE api_keys ADD COLUMN owner_kind text NOT NULL DEFAULT 'user'
    CHECK (owner_kind IN ('user', 'service_account'));

-- ---------------------------------------------------------------------- seed
-- Mirrors huron.pkg.rbac.roles.ROLES. Change that module first, then write a
-- follow-up migration; a contract test diffs the two.
INSERT INTO capabilities (code, description) VALUES
    ('organization.create',        'Create an organization (platform scope).'),
    ('organization.update',        'Edit an organization.'),
    ('organization.delete',        'Delete an organization (platform scope).'),
    ('organization.policy_attach', 'Attach a policy to an organization.'),
    ('project.create',             'Create a project inside an organization.'),
    ('project.update',             'Edit a project.'),
    ('project.policy_attach',      'Attach a policy to a project.'),
    ('dataset.create',             'Create a dataset inside a project.'),
    ('dataset.update',             'Edit dataset metadata.'),
    ('dataset.policy_attach',      'Attach a policy to a dataset.'),
    ('dataset.discover',           'See that a dataset exists in search and listings.'),
    ('release.create',             'Tag a dataset revision as a release.'),
    ('rbac.binding_manage',        'Grant and revoke role bindings in scope.'),
    ('service_account.manage',     'Create and disable service accounts in scope.'),
    ('data.read',                  'Read dataset bytes on a storage layer.'),
    ('data.write',                 'Commit dataset bytes to a storage layer.');

INSERT INTO roles (code, title, description, allowed_principal_kinds, bindable_scopes) VALUES
    ('reader', 'Reader',
     'Discover datasets and read every layer in scope.',
     ARRAY['user','service_account'], ARRAY['ORGANIZATION','PROJECT','DATASET']),
    ('developer', 'Developer',
     'Commit to raw and bronze; create and tag datasets.',
     ARRAY['user'], ARRAY['ORGANIZATION','PROJECT','DATASET']),
    ('data_steward', 'Data Steward',
     'Developer plus dataset policy; shapes silver/gold via pipelines only.',
     ARRAY['user'], ARRAY['ORGANIZATION','PROJECT','DATASET']),
    ('project_admin', 'Project Admin',
     'Administer projects and their bindings; no data writes.',
     ARRAY['user'], ARRAY['ORGANIZATION','PROJECT']),
    ('organization_admin', 'Organization Admin',
     'Administer one organization, its service accounts and bindings.',
     ARRAY['user'], ARRAY['ORGANIZATION']),
    ('platform_owner', 'Platform Owner',
     'Platform-wide administration. Deliberately no data.write.',
     ARRAY['user'], ARRAY['SYSTEM']),
    ('pipeline', 'Pipeline',
     'The only role that writes silver and gold. Service accounts only.',
     ARRAY['service_account'], ARRAY['PROJECT','DATASET']);

INSERT INTO role_capabilities (role_code, capability_code, layers) VALUES
    ('reader', 'dataset.discover', NULL),
    ('reader', 'data.read', NULL),

    ('developer', 'dataset.discover', NULL),
    ('developer', 'dataset.create', NULL),
    ('developer', 'dataset.update', NULL),
    ('developer', 'release.create', NULL),
    ('developer', 'data.read', NULL),
    ('developer', 'data.write', ARRAY['raw','bronze']),

    ('data_steward', 'dataset.discover', NULL),
    ('data_steward', 'dataset.create', NULL),
    ('data_steward', 'dataset.update', NULL),
    ('data_steward', 'dataset.policy_attach', NULL),
    ('data_steward', 'release.create', NULL),
    ('data_steward', 'data.read', NULL),
    ('data_steward', 'data.write', ARRAY['raw','bronze']),

    ('project_admin', 'dataset.discover', NULL),
    ('project_admin', 'project.update', NULL),
    ('project_admin', 'project.policy_attach', NULL),
    ('project_admin', 'dataset.create', NULL),
    ('project_admin', 'dataset.update', NULL),
    ('project_admin', 'dataset.policy_attach', NULL),
    ('project_admin', 'release.create', NULL),
    ('project_admin', 'rbac.binding_manage', NULL),
    ('project_admin', 'data.read', NULL),

    ('organization_admin', 'dataset.discover', NULL),
    ('organization_admin', 'organization.update', NULL),
    ('organization_admin', 'organization.policy_attach', NULL),
    ('organization_admin', 'project.create', NULL),
    ('organization_admin', 'project.update', NULL),
    ('organization_admin', 'project.policy_attach', NULL),
    ('organization_admin', 'dataset.policy_attach', NULL),
    ('organization_admin', 'service_account.manage', NULL),
    ('organization_admin', 'rbac.binding_manage', NULL),
    ('organization_admin', 'data.read', NULL),

    ('platform_owner', 'organization.create', NULL),
    ('platform_owner', 'organization.update', NULL),
    ('platform_owner', 'organization.delete', NULL),
    ('platform_owner', 'organization.policy_attach', NULL),
    ('platform_owner', 'project.create', NULL),
    ('platform_owner', 'project.update', NULL),
    ('platform_owner', 'project.policy_attach', NULL),
    ('platform_owner', 'dataset.create', NULL),
    ('platform_owner', 'dataset.update', NULL),
    ('platform_owner', 'dataset.policy_attach', NULL),
    ('platform_owner', 'dataset.discover', NULL),
    ('platform_owner', 'release.create', NULL),
    ('platform_owner', 'service_account.manage', NULL),
    ('platform_owner', 'rbac.binding_manage', NULL),
    ('platform_owner', 'data.read', NULL),

    ('pipeline', 'dataset.discover', NULL),
    ('pipeline', 'data.read', NULL),
    ('pipeline', 'data.write', ARRAY['bronze','silver','gold']);
"""


def upgrade() -> None:
    op.execute(DDL)


def downgrade() -> None:
    op.execute("""
    DROP TRIGGER IF EXISTS role_bindings_guard ON role_bindings;
    DROP FUNCTION IF EXISTS role_binding_guard();
    DROP TRIGGER IF EXISTS service_accounts_kind_guard ON service_accounts;
    DROP FUNCTION IF EXISTS service_account_kind_guard();
    ALTER TABLE api_keys DROP COLUMN IF EXISTS owner_kind;
    DROP TABLE IF EXISTS policy_attachments, policies CASCADE;
    ALTER TABLE role_bindings
        DROP CONSTRAINT IF EXISTS role_bindings_no_duplicates,
        DROP CONSTRAINT IF EXISTS role_bindings_principal_format,
        DROP CONSTRAINT IF EXISTS role_bindings_role_fk;
    ALTER TABLE role_bindings RENAME COLUMN role_code TO role;
    ALTER TABLE role_bindings ADD COLUMN capabilities text[] NOT NULL DEFAULT '{}';
    DROP TABLE IF EXISTS role_capabilities, capabilities, roles CASCADE;
    DROP TABLE IF EXISTS service_accounts, principals CASCADE;
    """)
