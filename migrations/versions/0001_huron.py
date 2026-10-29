"""The version-1 Huron schema: catalog, registry, grants, files, audit and keys.

Revision ID: 0001_huron
Revises:
Create Date: 2026-10-29 02:46:40.758782
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_huron"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SIBLING_EXCLUSION = [
    """
    create function huron.namespace_rules() returns trigger language plpgsql as $$
    begin
        if new.parent_id is not null and not exists (
            select 1 from huron.namespaces p
            where p.id = new.parent_id and p.catalog_id = new.catalog_id
        ) then
            raise exception 'parent namespace belongs to another catalog'
                using errcode = 'foreign_key_violation';
        end if;
        if new.parent_id is not null and exists (
            select 1 from huron.collections c
            where c.namespace_id = new.parent_id and c.name = new.name
        ) then
            raise exception 'a collection named % exists here', new.name
                using errcode = 'unique_violation', constraint = 'sibling_exclusion';
        end if;
        return new;
    end $$
    """,
    """
    create function huron.collection_rules() returns trigger language plpgsql as $$
    begin
        if exists (
            select 1 from huron.namespaces n
            where n.parent_id = new.namespace_id and n.name = new.name
        ) then
            raise exception 'a namespace named % exists here', new.name
                using errcode = 'unique_violation', constraint = 'sibling_exclusion';
        end if;
        return new;
    end $$
    """,
    """
    create trigger namespace_rules before insert or update of parent_id, name
    on huron.namespaces for each row execute function huron.namespace_rules()
    """,
    """
    create trigger collection_rules before insert or update of namespace_id, name
    on huron.collections for each row execute function huron.collection_rules()
    """,
]

DROP_SIBLING_EXCLUSION = [
    "drop trigger if exists collection_rules on huron.collections",
    "drop trigger if exists namespace_rules on huron.namespaces",
    "drop function if exists huron.collection_rules()",
    "drop function if exists huron.namespace_rules()",
]


def upgrade() -> None:
    """Apply this revision."""
    op.create_table(
        "audit",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("object_type", sa.Text(), nullable=False),
        sa.Column("object_id", sa.Uuid(), nullable=True),
        sa.Column("catalog_id", sa.Uuid(), nullable=True),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit")),
        schema="huron",
    )
    op.create_index(
        op.f("ix_audit_catalog_id_id"), "audit", ["catalog_id", "id"], unique=False, schema="huron"
    )
    op.create_index(
        op.f("ix_audit_object_id_id"), "audit", ["object_id", "id"], unique=False, schema="huron"
    )
    op.create_table(
        "grants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scope_type", sa.Text(), nullable=False),
        sa.Column("scope_id", sa.Uuid(), nullable=True),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("ldap_group", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "(role = 'platform_admin' and scope_type = 'platform') or (role = 'org_admin' and scope_type = 'organization') or (role in ('catalog_admin', 'contributor', 'reader') and scope_type = 'catalog')",
            name=op.f("ck_grants_role_scope"),
        ),
        sa.CheckConstraint(
            "(scope_type = 'platform') = (scope_id is null)", name=op.f("ck_grants_scope_id")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_grants")),
        sa.UniqueConstraint(
            "scope_type",
            "scope_id",
            "role",
            "ldap_group",
            name=op.f("uq_grants_scope_type_scope_id_role_ldap_group"),
            postgresql_nulls_not_distinct=True,
        ),
        schema="huron",
    )
    op.create_index(
        op.f("ix_grants_ldap_group"), "grants", ["ldap_group"], unique=False, schema="huron"
    )
    op.create_index(
        op.f("ix_grants_scope_type_scope_id"),
        "grants",
        ["scope_type", "scope_id"],
        unique=False,
        schema="huron",
    )
    op.create_table(
        "organizations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organizations")),
        sa.UniqueConstraint("name", name=op.f("uq_organizations_name")),
        schema="huron",
    )
    op.create_table(
        "signing_keys",
        sa.Column("kid", sa.Text(), nullable=False),
        sa.Column("private_pem", sa.Text(), nullable=False),
        sa.Column("public_jwk", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("kid", name=op.f("pk_signing_keys")),
        schema="huron",
    )
    op.create_table(
        "schemas",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("extends_id", sa.Uuid(), nullable=True),
        sa.Column("document", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["extends_id"], ["huron.schemas.id"], name=op.f("fk_schemas_extends_id")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["huron.organizations.id"], name=op.f("fk_schemas_organization_id")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_schemas")),
        sa.UniqueConstraint(
            "organization_id",
            "name",
            "version",
            name=op.f("uq_schemas_organization_id_name_version"),
            postgresql_nulls_not_distinct=True,
        ),
        schema="huron",
    )
    op.create_table(
        "catalogs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("schema_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["huron.organizations.id"],
            name=op.f("fk_catalogs_organization_id"),
        ),
        sa.ForeignKeyConstraint(
            ["schema_id"], ["huron.schemas.id"], name=op.f("fk_catalogs_schema_id")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_catalogs")),
        sa.UniqueConstraint("name", name=op.f("uq_catalogs_name")),
        schema="huron",
    )
    op.create_index(
        op.f("ix_catalogs_organization_id"),
        "catalogs",
        ["organization_id"],
        unique=False,
        schema="huron",
    )
    op.create_table(
        "namespaces",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("catalog_id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("collections_allowed", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["catalog_id"], ["huron.catalogs.id"], name=op.f("fk_namespaces_catalog_id")
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"], ["huron.namespaces.id"], name=op.f("fk_namespaces_parent_id")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_namespaces")),
        sa.UniqueConstraint("catalog_id", "path", name=op.f("uq_namespaces_catalog_id_path")),
        schema="huron",
    )
    op.create_index(
        op.f("ix_namespaces_catalog_id_parent_id"),
        "namespaces",
        ["catalog_id", "parent_id"],
        unique=False,
        schema="huron",
    )
    op.create_index(
        op.f("ix_namespaces_parent_id"), "namespaces", ["parent_id"], unique=False, schema="huron"
    )
    op.create_table(
        "collections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("catalog_id", sa.Uuid(), nullable=False),
        sa.Column("namespace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("identifier", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("schema_override", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("file_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state in ('draft', 'active', 'incomplete')", name=op.f("ck_collections_state")
        ),
        sa.CheckConstraint("file_count >= 0", name=op.f("ck_collections_file_count")),
        sa.ForeignKeyConstraint(
            ["catalog_id"], ["huron.catalogs.id"], name=op.f("fk_collections_catalog_id")
        ),
        sa.ForeignKeyConstraint(
            ["namespace_id"], ["huron.namespaces.id"], name=op.f("fk_collections_namespace_id")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_collections")),
        sa.UniqueConstraint("identifier", name=op.f("uq_collections_identifier")),
        sa.UniqueConstraint("namespace_id", "name", name=op.f("uq_collections_namespace_id_name")),
        schema="huron",
    )
    op.create_index(
        op.f("ix_collections_catalog_id_state"),
        "collections",
        ["catalog_id", "state"],
        unique=False,
        schema="huron",
    )
    op.create_index(
        "ix_collections_metadata",
        "collections",
        ["metadata"],
        unique=False,
        schema="huron",
        postgresql_using="gin",
        postgresql_ops={"metadata": "jsonb_path_ops"},
    )
    op.create_table(
        "commits",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("collection_id", sa.Uuid(), nullable=False),
        sa.Column("base_version", sa.Integer(), nullable=False),
        sa.Column("new_version", sa.Integer(), nullable=False),
        sa.Column("adds", sa.Integer(), nullable=False),
        sa.Column("removes", sa.Integer(), nullable=False),
        sa.Column("host", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["huron.collections.id"],
            name=op.f("fk_commits_collection_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_commits")),
        schema="huron",
    )
    op.create_index(
        op.f("ix_commits_collection_id_id"),
        "commits",
        ["collection_id", "id"],
        unique=False,
        schema="huron",
    )
    op.create_table(
        "files",
        sa.Column("collection_id", sa.Uuid(), nullable=False),
        sa.Column("rel_path", sa.Text(), nullable=False),
        sa.Column("rel_path_key", sa.Text(), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_by", sa.Text(), nullable=False),
        sa.Column("commit_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("size >= 0", name=op.f("ck_files_size")),
        sa.ForeignKeyConstraint(
            ["collection_id"], ["huron.collections.id"], name=op.f("fk_files_collection_id")
        ),
        sa.ForeignKeyConstraint(
            ["commit_id"], ["huron.commits.id"], name=op.f("fk_files_commit_id")
        ),
        sa.PrimaryKeyConstraint("collection_id", "rel_path_key", name=op.f("pk_files")),
        schema="huron",
    )
    op.create_index(
        op.f("ix_files_commit_id"), "files", ["commit_id"], unique=False, schema="huron"
    )
    for statement in SIBLING_EXCLUSION:
        op.execute(statement)


def downgrade() -> None:
    """Revert this revision."""
    for statement in DROP_SIBLING_EXCLUSION:
        op.execute(statement)
    op.drop_index(op.f("ix_files_commit_id"), table_name="files", schema="huron")
    op.drop_table("files", schema="huron")
    op.drop_index(op.f("ix_commits_collection_id_id"), table_name="commits", schema="huron")
    op.drop_table("commits", schema="huron")
    op.drop_index(
        "ix_collections_metadata",
        table_name="collections",
        schema="huron",
        postgresql_using="gin",
        postgresql_ops={"metadata": "jsonb_path_ops"},
    )
    op.drop_index(op.f("ix_collections_catalog_id_state"), table_name="collections", schema="huron")
    op.drop_table("collections", schema="huron")
    op.drop_index(op.f("ix_namespaces_parent_id"), table_name="namespaces", schema="huron")
    op.drop_index(
        op.f("ix_namespaces_catalog_id_parent_id"), table_name="namespaces", schema="huron"
    )
    op.drop_table("namespaces", schema="huron")
    op.drop_index(op.f("ix_catalogs_organization_id"), table_name="catalogs", schema="huron")
    op.drop_table("catalogs", schema="huron")
    op.drop_table("schemas", schema="huron")
    op.drop_table("signing_keys", schema="huron")
    op.drop_table("organizations", schema="huron")
    op.drop_index(op.f("ix_grants_scope_type_scope_id"), table_name="grants", schema="huron")
    op.drop_index(op.f("ix_grants_ldap_group"), table_name="grants", schema="huron")
    op.drop_table("grants", schema="huron")
    op.drop_index(op.f("ix_audit_object_id_id"), table_name="audit", schema="huron")
    op.drop_index(op.f("ix_audit_catalog_id_id"), table_name="audit", schema="huron")
    op.drop_table("audit", schema="huron")
