"""The ``commit_requests`` and ``commit_entries`` tables."""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from huron.core.metastore.tables import metadata

__all__ = ["commit_entries", "commit_requests"]

commit_requests = Table(
    "commit_requests",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("subject", Text, nullable=False),
    Column("request_id", Uuid, nullable=False),
    Column(
        "collection_id",
        Uuid,
        ForeignKey("huron.collections.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("body_digest", Text, nullable=False),
    Column("base_version", Integer, nullable=False),
    Column("host", Text, nullable=False),
    Column("message", Text, nullable=True),
    Column("state", Text, nullable=False),
    Column("version", Integer, nullable=True),
    Column("file_count", Integer, nullable=True),
    Column("commit_id", Uuid, ForeignKey("huron.commits.id", ondelete="SET NULL"), nullable=True),
    Column("refusal", JSONB, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("subject", "request_id"),
    CheckConstraint(
        "state in ('rejected', 'accepted', 'blocked', 'succeeded', 'abandoned')", name="state"
    ),
    CheckConstraint("body_digest ~ '^[0-9a-f]{64}$'", name="body_digest"),
    CheckConstraint("base_version >= 0", name="base_version"),
    CheckConstraint("version >= 0", name="version"),
    CheckConstraint("file_count >= 0", name="file_count"),
    CheckConstraint(
        "state <> 'succeeded' or (version is not null and file_count is not null)",
        name="succeeded",
    ),
    CheckConstraint("state not in ('rejected', 'blocked') or refusal is not null", name="refusal"),
    Index(None, "collection_id"),
    Index(None, "commit_id"),
    Index(
        "ix_commit_requests_pending",
        "created_at",
        postgresql_where=text("state in ('accepted', 'blocked')"),
    ),
)
"""One row for each commit request, keyed by its creator's subject and its request ID."""

commit_entries = Table(
    "commit_entries",
    metadata,
    Column(
        "commit_request_id",
        Uuid,
        ForeignKey("huron.commit_requests.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("ordinal", Integer, nullable=False),
    Column("action", Text, nullable=False),
    Column("rel_path", Text, nullable=False),
    Column("upload_id", Uuid, ForeignKey("huron.staged_upload_ids.upload_id"), nullable=True),
    Column("done_at", DateTime(timezone=True), nullable=True),
    PrimaryKeyConstraint("commit_request_id", "ordinal"),
    CheckConstraint("ordinal >= 0", name="ordinal"),
    CheckConstraint(
        "action in ('remove_file', 'remove_directory', 'prune_directory', 'make_directory',"
        " 'add_file')",
        name="action",
    ),
    CheckConstraint("(action = 'add_file') = (upload_id is not null)", name="upload"),
    Index(None, "upload_id"),
)
"""The filesystem changes of an accepted request, in the order of ``ordinal``."""
