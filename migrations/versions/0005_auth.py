"""Local password credentials, server-side browser sessions, and the
``user.manage`` capability that guards admin-provisioned user accounts.

``principals`` (0002) already carries ``idp_subject`` and its
``kind = 'user' OR idp_subject IS NULL`` guard, so the OIDC upsert needs no
schema change here - only the two credential surfaces a session-based login
adds on top of the existing bearer paths.

``local_credentials`` holds at most one password per principal, users only;
``local_credentials_kind_guard`` backstops that at the database level so a
row written outside the guarded v1 user routes - a migration, a support
script, psql - still cannot attach a password to a service account.

``sessions`` is the server-side half of the cookie login: the browser holds
an opaque ``hs_{id}_{secret}`` value, the table keeps only the secret's
SHA-256. Expiry is double-bounded (idle slides forward on activity, absolute
is fixed at login) and enforced in application code; the CHECK below only
guards the ordering between the two so a bad idle extension can never exceed
the session's absolute lifetime.

The seed mirrors ``huron.pkg.rbac.roles.ROLES`` (changed there first, same
convention as 0002/0004): ``user.manage`` lets ``platform_owner`` alone
create and administer password users - provisioning humans is a platform
act, distinct from an organization admin's service-account authority.
"""

from migrations._ddl import execute_sql

revision = "0005_auth"
down_revision = "0004_entry_layers"
branch_labels = None
depends_on = None


DDL = r"""
-- ------------------------------------------------------- local credentials
-- At most one password per principal; users only. Password hashes are
-- argon2id strings (self-describing parameters). Admin-provisioned: rows are
-- written exclusively through the guarded v1 user routes.
CREATE TABLE local_credentials (
    principal_id uuid PRIMARY KEY REFERENCES principals(id),
    password_hash text NOT NULL CHECK (password_hash LIKE '$argon2id$%'),
    updated_at timestamptz NOT NULL,
    updated_by text NOT NULL
);

CREATE FUNCTION local_credentials_kind_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE principal_kind text;
BEGIN
    SELECT kind INTO principal_kind FROM principals WHERE id = NEW.principal_id;
    IF principal_kind IS DISTINCT FROM 'user' THEN
        RAISE EXCEPTION 'local_credentials.principal_id must reference a user principal';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER local_credentials_kind_guard BEFORE INSERT OR UPDATE ON local_credentials
FOR EACH ROW EXECUTE FUNCTION local_credentials_kind_guard();

-- ------------------------------------------------------------------ sessions
-- One row per interactive browser session. The cookie carries the secret;
-- only its SHA-256 lands here. subject/groups are a login-time snapshot.
CREATE TABLE sessions (
    id uuid PRIMARY KEY,
    secret_sha256 text NOT NULL CHECK (secret_sha256 ~ '^[0-9a-f]{64}$'),
    csrf_token text NOT NULL,
    subject text NOT NULL,
    groups text[] NOT NULL DEFAULT '{}',
    authentication_method text NOT NULL CHECK (authentication_method IN ('oidc', 'password')),
    created_at timestamptz NOT NULL,
    last_seen_at timestamptz NOT NULL,
    idle_expires_at timestamptz NOT NULL,
    absolute_expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    CHECK (idle_expires_at <= absolute_expires_at)
);
CREATE INDEX sessions_subject_active ON sessions (subject) WHERE revoked_at IS NULL;

-- ---------------------------------------------------------------------- seed
-- Mirrors huron.pkg.rbac.roles.ROLES. Change that module first, then write a
-- follow-up migration; a contract test diffs the two.
INSERT INTO capabilities (code, description) VALUES
    ('user.manage', 'Create and administer password users');

INSERT INTO role_capabilities (role_code, capability_code, layers) VALUES
    ('platform_owner', 'user.manage', NULL);
"""


def upgrade() -> None:
    execute_sql(DDL)


def downgrade() -> None:
    execute_sql("""
    DELETE FROM role_capabilities
     WHERE role_code = 'platform_owner' AND capability_code = 'user.manage';
    DELETE FROM capabilities WHERE code = 'user.manage';
    DROP TRIGGER IF EXISTS local_credentials_kind_guard ON local_credentials;
    DROP FUNCTION IF EXISTS local_credentials_kind_guard();
    DROP TABLE IF EXISTS sessions;
    DROP TABLE IF EXISTS local_credentials;
    """)
