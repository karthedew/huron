"""The upload attempts with their objects.

``staged_uploads`` holds one row for each upload attempt, ``staged_upload_ids`` every upload ID
that Huron issued for an attempt, and ``objects`` the private copies that the seals make.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from huron.core.metastore.tables import metadata

__all__ = ["objects", "staged_upload_ids", "staged_uploads"]

staged_uploads = Table(
    "staged_uploads",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("subject", Text, nullable=False),
    Column("attempt_id", Uuid, nullable=False),
    Column(
        "collection_id",
        Uuid,
        ForeignKey("huron.collections.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("rel_path", Text, nullable=False),
    Column("size", BigInteger, nullable=False),
    Column("state", Text, nullable=False),
    Column("current_upload_id", Uuid, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("active_at", DateTime(timezone=True), nullable=False),
    Column("commit_request_id", Uuid, ForeignKey("huron.commit_requests.id"), nullable=True),
    Column("failure", JSONB, nullable=True),
    UniqueConstraint("subject", "attempt_id"),
    ForeignKeyConstraint(
        ["id", "current_upload_id"],
        ["huron.staged_upload_ids.staged_upload_id", "huron.staged_upload_ids.upload_id"],
        name="fk_staged_uploads_current_upload_id",
        deferrable=True,
        initially="DEFERRED",
        use_alter=True,
    ),
    CheckConstraint(
        "state in ('receiving', 'sealing', 'ready', 'consumed', 'failed', 'cancelled', 'expired')",
        name="state",
    ),
    CheckConstraint("size >= 0", name="size"),
    CheckConstraint("state <> 'failed' or failure is not null", name="failure"),
    CheckConstraint("state <> 'consumed' or commit_request_id is not null", name="consumed"),
    Index(None, "collection_id"),
    Index(None, "commit_request_id"),
    Index(None, "state", "active_at"),
)
"""One row for each upload attempt. The current upload ID is one of the attempt's issued IDs."""

staged_upload_ids = Table(
    "staged_upload_ids",
    metadata,
    Column("upload_id", Uuid, primary_key=True),
    Column(
        "staged_upload_id",
        Uuid,
        ForeignKey("huron.staged_uploads.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("issued_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("staged_upload_id", "upload_id"),
)
"""Every upload ID that Huron issued, for one attempt each: no ID is issued two times."""

objects = Table(
    "objects",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column(
        "upload_id",
        Uuid,
        ForeignKey("huron.staged_upload_ids.upload_id"),
        nullable=False,
        unique=True,
    ),
    Column("path", Text, nullable=False, unique=True),
    Column("state", Text, nullable=False),
    Column("size", BigInteger, nullable=True),
    Column("sha256", Text, nullable=True),
    Column("inode", BigInteger, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("sealed_at", DateTime(timezone=True), nullable=True),
    CheckConstraint("state in ('sealing', 'sealed', 'removed')", name="state"),
    CheckConstraint("size >= 0", name="size"),
    CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256"),
    CheckConstraint(
        "state <> 'sealed' or (size is not null and sha256 is not null"
        " and inode is not null and sealed_at is not null)",
        name="sealed",
    ),
    Index("ix_objects_present", "id", postgresql_where=text("state <> 'removed'")),
)
"""The private copy that the seal of one upload ID makes, at ``path`` in the API's form.

``ix_objects_present`` holds the objects that are not ``removed``, so that a cleanup reads only
those and not every object that it removed before."""
