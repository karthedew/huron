"""Safe publication: upload attempts, sealed objects, commit requests and their entries.

Revision ID: 0004_publication
Revises: 0003_uploads
Create Date: 2026-11-10 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_publication"
down_revision: str | None = "0003_uploads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the publication tables. Add ``files.object_id`` and ``pending_request_id``."""
    _create_commit_requests()
    _create_staged_uploads()
    _create_objects()
    _create_commit_entries()
    op.add_column("files", sa.Column("object_id", sa.Uuid(), nullable=True), schema="huron")
    op.create_unique_constraint(op.f("uq_files_object_id"), "files", ["object_id"], schema="huron")
    op.create_foreign_key(
        op.f("fk_files_object_id"),
        "files",
        "objects",
        ["object_id"],
        ["id"],
        source_schema="huron",
        referent_schema="huron",
    )
    op.add_column(
        "collections", sa.Column("pending_request_id", sa.Uuid(), nullable=True), schema="huron"
    )
    op.create_unique_constraint(
        op.f("uq_collections_pending_request_id"),
        "collections",
        ["pending_request_id"],
        schema="huron",
    )
    op.create_foreign_key(
        op.f("fk_collections_pending_request_id"),
        "collections",
        "commit_requests",
        ["pending_request_id"],
        ["id"],
        source_schema="huron",
        referent_schema="huron",
    )


def downgrade() -> None:
    """Drop the two added columns and the publication tables."""
    op.drop_constraint(
        op.f("fk_collections_pending_request_id"), "collections", schema="huron", type_="foreignkey"
    )
    op.drop_column("collections", "pending_request_id", schema="huron")
    op.drop_constraint(op.f("fk_files_object_id"), "files", schema="huron", type_="foreignkey")
    op.drop_column("files", "object_id", schema="huron")
    op.drop_index(op.f("ix_commit_entries_upload_id"), table_name="commit_entries", schema="huron")
    op.drop_table("commit_entries", schema="huron")
    op.drop_table("objects", schema="huron")
    op.drop_constraint(
        "fk_staged_uploads_current_upload_id", "staged_uploads", schema="huron", type_="foreignkey"
    )
    op.drop_table("staged_upload_ids", schema="huron")
    for index in ("state_active_at", "commit_request_id", "collection_id"):
        op.drop_index(
            op.f(f"ix_staged_uploads_{index}"), table_name="staged_uploads", schema="huron"
        )
    op.drop_table("staged_uploads", schema="huron")
    op.drop_index("ix_commit_requests_pending", table_name="commit_requests", schema="huron")
    for index in ("commit_id", "collection_id"):
        op.drop_index(
            op.f(f"ix_commit_requests_{index}"), table_name="commit_requests", schema="huron"
        )
    op.drop_table("commit_requests", schema="huron")


def _create_commit_requests() -> None:
    op.create_table(
        "commit_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("collection_id", sa.Uuid(), nullable=True),
        sa.Column("body_digest", sa.Text(), nullable=False),
        sa.Column("base_version", sa.Integer(), nullable=False),
        sa.Column("host", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=True),
        sa.Column("file_count", sa.Integer(), nullable=True),
        sa.Column("commit_id", sa.Uuid(), nullable=True),
        sa.Column("refusal", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state in ('rejected', 'accepted', 'blocked', 'succeeded', 'abandoned')",
            name=op.f("ck_commit_requests_state"),
        ),
        sa.CheckConstraint(
            "body_digest ~ '^[0-9a-f]{64}$'", name=op.f("ck_commit_requests_body_digest")
        ),
        sa.CheckConstraint("base_version >= 0", name=op.f("ck_commit_requests_base_version")),
        sa.CheckConstraint("version >= 0", name=op.f("ck_commit_requests_version")),
        sa.CheckConstraint("file_count >= 0", name=op.f("ck_commit_requests_file_count")),
        sa.CheckConstraint(
            "state <> 'succeeded' or (version is not null and file_count is not null)",
            name=op.f("ck_commit_requests_succeeded"),
        ),
        sa.CheckConstraint(
            "state not in ('rejected', 'blocked') or refusal is not null",
            name=op.f("ck_commit_requests_refusal"),
        ),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["huron.collections.id"],
            name=op.f("fk_commit_requests_collection_id"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["commit_id"],
            ["huron.commits.id"],
            name=op.f("fk_commit_requests_commit_id"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_commit_requests")),
        sa.UniqueConstraint(
            "subject", "request_id", name=op.f("uq_commit_requests_subject_request_id")
        ),
        schema="huron",
    )
    for column in ("collection_id", "commit_id"):
        op.create_index(
            op.f(f"ix_commit_requests_{column}"), "commit_requests", [column], schema="huron"
        )
    op.create_index(
        "ix_commit_requests_pending",
        "commit_requests",
        ["created_at"],
        schema="huron",
        postgresql_where=sa.text("state in ('accepted', 'blocked')"),
    )


def _create_staged_uploads() -> None:
    op.create_table(
        "staged_uploads",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("collection_id", sa.Uuid(), nullable=True),
        sa.Column("rel_path", sa.Text(), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("current_upload_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("active_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("commit_request_id", sa.Uuid(), nullable=True),
        sa.Column("failure", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.CheckConstraint(
            "state in ('receiving', 'sealing', 'ready', 'consumed', 'failed', 'cancelled',"
            " 'expired')",
            name=op.f("ck_staged_uploads_state"),
        ),
        sa.CheckConstraint("size >= 0", name=op.f("ck_staged_uploads_size")),
        sa.CheckConstraint(
            "state <> 'failed' or failure is not null", name=op.f("ck_staged_uploads_failure")
        ),
        sa.CheckConstraint(
            "state <> 'consumed' or commit_request_id is not null",
            name=op.f("ck_staged_uploads_consumed"),
        ),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["huron.collections.id"],
            name=op.f("fk_staged_uploads_collection_id"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["commit_request_id"],
            ["huron.commit_requests.id"],
            name=op.f("fk_staged_uploads_commit_request_id"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_staged_uploads")),
        sa.UniqueConstraint(
            "subject", "attempt_id", name=op.f("uq_staged_uploads_subject_attempt_id")
        ),
        schema="huron",
    )
    for columns in (["collection_id"], ["commit_request_id"], ["state", "active_at"]):
        op.create_index(
            op.f(f"ix_staged_uploads_{'_'.join(columns)}"),
            "staged_uploads",
            columns,
            schema="huron",
        )
    op.create_table(
        "staged_upload_ids",
        sa.Column("upload_id", sa.Uuid(), nullable=False),
        sa.Column("staged_upload_id", sa.Uuid(), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["staged_upload_id"],
            ["huron.staged_uploads.id"],
            name=op.f("fk_staged_upload_ids_staged_upload_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("upload_id", name=op.f("pk_staged_upload_ids")),
        sa.UniqueConstraint(
            "staged_upload_id",
            "upload_id",
            name=op.f("uq_staged_upload_ids_staged_upload_id_upload_id"),
        ),
        schema="huron",
    )
    op.create_foreign_key(
        "fk_staged_uploads_current_upload_id",
        "staged_uploads",
        "staged_upload_ids",
        ["id", "current_upload_id"],
        ["staged_upload_id", "upload_id"],
        source_schema="huron",
        referent_schema="huron",
        deferrable=True,
        initially="DEFERRED",
    )


def _create_objects() -> None:
    op.create_table(
        "objects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("upload_id", sa.Uuid(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=True),
        sa.Column("sha256", sa.Text(), nullable=True),
        sa.Column("inode", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state in ('sealing', 'sealed', 'removed')", name=op.f("ck_objects_state")
        ),
        sa.CheckConstraint("size >= 0", name=op.f("ck_objects_size")),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_objects_sha256")),
        sa.CheckConstraint(
            "state <> 'sealed' or (size is not null and sha256 is not null"
            " and inode is not null and sealed_at is not null)",
            name=op.f("ck_objects_sealed"),
        ),
        sa.ForeignKeyConstraint(
            ["upload_id"],
            ["huron.staged_upload_ids.upload_id"],
            name=op.f("fk_objects_upload_id"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_objects")),
        sa.UniqueConstraint("path", name=op.f("uq_objects_path")),
        sa.UniqueConstraint("upload_id", name=op.f("uq_objects_upload_id")),
        schema="huron",
    )


def _create_commit_entries() -> None:
    op.create_table(
        "commit_entries",
        sa.Column("commit_request_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("rel_path", sa.Text(), nullable=False),
        sa.Column("upload_id", sa.Uuid(), nullable=True),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("ordinal >= 0", name=op.f("ck_commit_entries_ordinal")),
        sa.CheckConstraint(
            "action in ('remove_file', 'remove_directory', 'prune_directory', 'make_directory',"
            " 'add_file')",
            name=op.f("ck_commit_entries_action"),
        ),
        sa.CheckConstraint(
            "(action = 'add_file') = (upload_id is not null)",
            name=op.f("ck_commit_entries_upload"),
        ),
        sa.ForeignKeyConstraint(
            ["commit_request_id"],
            ["huron.commit_requests.id"],
            name=op.f("fk_commit_entries_commit_request_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["upload_id"],
            ["huron.staged_upload_ids.upload_id"],
            name=op.f("fk_commit_entries_upload_id"),
        ),
        sa.PrimaryKeyConstraint("commit_request_id", "ordinal", name=op.f("pk_commit_entries")),
        schema="huron",
    )
    op.create_index(
        op.f("ix_commit_entries_upload_id"), "commit_entries", ["upload_id"], schema="huron"
    )
