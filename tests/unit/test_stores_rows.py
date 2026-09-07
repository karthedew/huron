"""The row-mapping helpers in ``stores/rows.py`` are pure functions over a mapping.

Exercised here with plain dicts standing in for ``asyncpg.Record``, the same
duck-typed access (``row["column"]``) either provides. The store classes
that own the SQL are covered by ``tests/contract/`` against a real database
instead.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from huron.pkg.catalog.ingest import FileState, IngestState, UploadAction
from huron.service.api.stores.rows import (
    affected_row_count,
    api_key_record,
    binding_record,
    credential_record,
    dataset,
    ingest_file,
    ingest_session,
    organization,
    policy,
    principal_record,
    project,
    release,
    revision_record,
    revision_ref,
    service_account,
    session_record,
)

pytestmark = pytest.mark.unit


def test_binding_record_maps_every_column_including_a_null_expiry() -> None:
    """``binding_record`` maps every column of a row, including a null ``expires_at``."""
    binding_id = uuid4()
    scope_id = uuid4()
    now = datetime.now(UTC)
    row = {
        "id": binding_id,
        "principal": "user:alice",
        "role_code": "platform_owner",
        "scope_type": "organization",
        "scope_id": scope_id,
        "created_by": "admin",
        "created_at": now,
        "expires_at": None,
    }
    record = binding_record(row)
    assert record.id == binding_id
    assert record.principal == "user:alice"
    assert record.scope_id == scope_id
    assert record.expires_at is None


def test_service_account_maps_every_column_including_a_null_disabled_at() -> None:
    """``service_account`` maps every column of a row, including a null ``disabled_at``."""
    principal_id = uuid4()
    organization_id = uuid4()
    now = datetime.now(UTC)
    row = {
        "principal_id": principal_id,
        "organization_id": organization_id,
        "name": "ingest-bot",
        "subject": "org/ingest-bot",
        "created_by": "admin",
        "created_at": now,
        "disabled_at": None,
    }
    record = service_account(row)
    assert record.principal_id == principal_id
    assert record.organization_id == organization_id
    assert record.name == "ingest-bot"
    assert record.disabled_at is None


def test_policy_decodes_the_jsonb_spec_column() -> None:
    """``policy`` decodes the JSONB ``spec`` column from a string into a dict."""
    policy_id = uuid4()
    now = datetime.now(UTC)
    row = {
        "id": policy_id,
        "policy_type": "layer_mask",
        "name": "pii-mask",
        "spec": json.dumps({"layers": ["raw"]}),
        "created_by": "admin",
        "created_at": now,
    }
    record = policy(row)
    assert record.id == policy_id
    assert record.spec == {"layers": ["raw"]}


def test_api_key_record_maps_scopes_to_a_frozenset_and_a_present_project_id() -> None:
    """``api_key_record`` maps ``scopes`` to a frozenset and stringifies ``project_id``."""
    project_id = uuid4()
    now = datetime.now(UTC)
    row = {
        "key_id": "hk_abc123",
        "owner_subject": "alice",
        "name": "ci key",
        "secret_sha256": "0" * 64,
        "scopes": ["datasets:read", "datasets:write"],
        "project_id": project_id,
        "expires_at": now,
        "revoked_at": None,
        "owner_kind": "user",
    }
    record = api_key_record(row)
    assert record.scopes == frozenset({"datasets:read", "datasets:write"})
    assert record.project_id == str(project_id)
    assert record.revoked_at is None


def test_api_key_record_leaves_project_id_none_when_the_key_is_unscoped() -> None:
    """``api_key_record`` leaves ``project_id`` as None when the key is unscoped."""
    now = datetime.now(UTC)
    row = {
        "key_id": "hk_abc123",
        "owner_subject": "alice",
        "name": "ci key",
        "secret_sha256": "0" * 64,
        "scopes": [],
        "project_id": None,
        "expires_at": now,
        "revoked_at": None,
        "owner_kind": "user",
    }
    record = api_key_record(row)
    assert record.project_id is None


def test_credential_record_maps_every_column() -> None:
    """``credential_record`` maps every column of a row onto the record."""
    principal_id = uuid4()
    now = datetime.now(UTC)
    row = {
        "principal_id": principal_id,
        "password_hash": "$argon2id$v=19$...",
        "updated_at": now,
        "updated_by": "admin",
    }
    record = credential_record(row)
    assert record.principal_id == principal_id
    assert record.password_hash == "$argon2id$v=19$..."
    assert record.updated_at == now
    assert record.updated_by == "admin"


def test_session_record_maps_groups_to_a_frozenset() -> None:
    """``session_record`` maps ``groups`` to a frozenset."""
    session_id = uuid4()
    now = datetime.now(UTC)
    row = {
        "id": session_id,
        "secret_sha256": "0" * 64,
        "csrf_token": "csrf",
        "subject": "alice",
        "groups": ["physics", "leads"],
        "authentication_method": "password",
        "created_at": now,
        "last_seen_at": now,
        "idle_expires_at": now,
        "absolute_expires_at": now,
        "revoked_at": None,
    }
    record = session_record(row)
    assert record.id == session_id
    assert record.groups == frozenset({"physics", "leads"})
    assert record.revoked_at is None


def test_principal_record_maps_every_column() -> None:
    """``principal_record`` maps every column of a row onto the record."""
    principal_id = uuid4()
    now = datetime.now(UTC)
    row = {
        "id": principal_id,
        "kind": "user",
        "subject": "idp-sub-1",
        "display_name": "Alice",
        "idp_subject": "idp-sub-1",
        "disabled_at": None,
        "created_at": now,
    }
    record = principal_record(row)
    assert record.id == principal_id
    assert record.kind == "user"
    assert record.idp_subject == "idp-sub-1"


def test_organization_maps_every_column() -> None:
    """``organization`` maps every column of a row onto the record."""
    organization_id = uuid4()
    now = datetime.now(UTC)
    row = {
        "id": organization_id,
        "slug": "helio",
        "title": "Heliophysics",
        "description": "Solar and space physics",
        "generation": 1,
        "version": 1,
        "created_at": now,
    }
    record = organization(row)
    assert record.id == organization_id
    assert record.slug == "helio"
    assert record.generation == 1
    assert record.created_at == now


def test_project_maps_classification_default_to_data_classification() -> None:
    """``project`` renames the ``classification_default`` column to ``data_classification``."""
    project_id = uuid4()
    organization_id = uuid4()
    now = datetime.now(UTC)
    row = {
        "id": project_id,
        "organization_id": organization_id,
        "slug": "corona",
        "title": "Corona",
        "description": "",
        "classification_default": "restricted",
        "generation": 2,
        "version": 3,
        "created_at": now,
    }
    record = project(row)
    assert record.id == project_id
    assert record.organization_id == organization_id
    assert record.data_classification == "restricted"
    assert record.generation == 2
    assert record.version == 3


def test_dataset_maps_every_column_and_ignores_data_classification() -> None:
    """``dataset`` maps every ``Dataset`` field and never reads back a classification column."""
    dataset_id = uuid4()
    project_id = uuid4()
    now = datetime.now(UTC)
    row = {
        "id": dataset_id,
        "project_id": project_id,
        "slug": "flare-catalog",
        "title": "Flare Catalog",
        "description": "",
        "profile_name": "timeseries",
        "profile_version": "1.0",
        "entry_layer": "raw",
        "lifecycle_state": "ACTIVE",
        "generation": 1,
        "version": 1,
        "created_at": now,
    }
    record = dataset(row)
    assert record.id == dataset_id
    assert record.project_id == project_id
    assert record.profile_name == "timeseries"
    assert record.entry_layer == "raw"
    assert record.lifecycle_state == "ACTIVE"


def test_release_maps_the_joined_revision_number_and_a_null_title() -> None:
    """``release`` maps the joined ``revision_number`` column, and a null ``title`` to None."""
    release_id = uuid4()
    dataset_id = uuid4()
    revision_id = uuid4()
    now = datetime.now(UTC)
    row = {
        "id": release_id,
        "dataset_id": dataset_id,
        "tag": "v1",
        "revision_id": revision_id,
        "revision_number": 1,
        "title": None,
        "created_by": "user:alice",
        "created_at": now,
    }
    record = release(row)
    assert record.id == release_id
    assert record.revision_id == revision_id
    assert record.revision_number == 1
    assert record.title is None


def test_revision_ref_maps_revision_number_to_number() -> None:
    """``revision_ref`` renames the ``revision_number`` column to ``RevisionRef.number``."""
    revision_id = uuid4()
    dataset_id = uuid4()
    row = {
        "id": revision_id,
        "dataset_id": dataset_id,
        "revision_number": 3,
        "manifest_sha256": "a" * 64,
    }
    record = revision_ref(row)
    assert record.id == revision_id
    assert record.dataset_id == dataset_id
    assert record.number == 3
    assert record.manifest_sha256 == "a" * 64


def test_revision_record_maps_revision_number_to_number() -> None:
    """``revision_record`` decodes every column, renaming ``revision_number`` to ``number``."""
    revision_id = uuid4()
    dataset_id = uuid4()
    now = datetime.now(UTC)
    row = {
        "id": revision_id,
        "dataset_id": dataset_id,
        "revision_number": 3,
        "manifest_sha256": "a" * 64,
        "metadata_sha256": "b" * 64,
        "revision_path": "revisions/000003--" + str(revision_id),
        "file_count": 5,
        "total_bytes": 1024,
        "committed_by": "user:alice",
        "committed_at": now,
    }
    record = revision_record(row)
    assert record.id == revision_id
    assert record.dataset_id == dataset_id
    assert record.number == 3
    assert record.manifest_sha256 == "a" * 64
    assert record.metadata_sha256 == "b" * 64
    assert record.revision_path == row["revision_path"]
    assert record.file_count == 5
    assert record.total_bytes == 1024
    assert record.committed_by == "user:alice"
    assert record.committed_at == now


def test_ingest_session_decodes_the_lease_and_declared_identity() -> None:
    """``ingest_session`` decodes a full row into the lease, state and declared manifest."""
    session_id = uuid4()
    dataset_id = uuid4()
    revision_id = uuid4()
    parent_id = uuid4()
    now = datetime.now(UTC)
    row = {
        "id": session_id,
        "dataset_id": dataset_id,
        "revision_id": revision_id,
        "revision_number": 3,
        "manifest_sha256": "a" * 64,
        "state": "UPLOADING",
        "etag": 2,
        "expires_at": now,
        "created_by": "user:alice",
        "parent_revision_id": parent_id,
    }
    session = ingest_session(row)
    assert session.lease.ingest_id == session_id
    assert session.lease.dataset_id == dataset_id
    assert session.lease.revision_id == revision_id
    assert session.lease.revision_number == 3
    assert session.lease.expires_at == now
    assert session.state is IngestState.UPLOADING
    assert session.manifest_sha256 == "a" * 64
    assert session.created_by == "user:alice"
    assert session.parent_revision_id == parent_id
    assert session.etag == 2


def test_ingest_session_decodes_a_null_parent_revision() -> None:
    """``ingest_session`` decodes a first revision's null ``parent_revision_id`` as None."""
    row = {
        "id": uuid4(),
        "dataset_id": uuid4(),
        "revision_id": uuid4(),
        "revision_number": 1,
        "manifest_sha256": "a" * 64,
        "state": "PREPARING",
        "etag": 1,
        "expires_at": datetime.now(UTC),
        "created_by": "user:alice",
        "parent_revision_id": None,
    }
    assert ingest_session(row).parent_revision_id is None


def test_ingest_file_decodes_action_state_and_completed_parts() -> None:
    """``ingest_file`` decodes the action, state and completed_parts from their stored forms."""
    file_id = uuid4()
    row = {
        "file_id": file_id,
        "path": "payload/a.bin",
        "size": 20,
        "expected_sha256": "b" * 64,
        "action": "upload",
        "part_count": 2,
        "state": "PENDING",
        "completed_parts": json.dumps([1]),
    }
    file = ingest_file(row)
    assert file.file_id == file_id
    assert file.path == "payload/a.bin"
    assert file.size == 20
    assert file.expected_sha256 == "b" * 64
    assert file.action is UploadAction.UPLOAD
    assert file.part_count == 2
    assert file.state is FileState.PENDING
    assert file.completed_parts == frozenset({1})


def test_ingest_file_decodes_a_hardlink_file_with_no_parts() -> None:
    """``ingest_file`` decodes a hardlink file's empty ``completed_parts`` array."""
    row = {
        "file_id": uuid4(),
        "path": "payload/b.bin",
        "size": 5,
        "expected_sha256": "c" * 64,
        "action": "hardlink",
        "part_count": 0,
        "state": "COMPLETE",
        "completed_parts": json.dumps([]),
    }
    file = ingest_file(row)
    assert file.action is UploadAction.HARDLINK
    assert file.state is FileState.COMPLETE
    assert file.completed_parts == frozenset()


@pytest.mark.parametrize(
    ("tag", "expected"),
    [("UPDATE 0", 0), ("UPDATE 1", 1), ("UPDATE 42", 42)],
)
def test_affected_row_count_parses_the_asyncpg_command_tag(tag: str, expected: int) -> None:
    """``affected_row_count`` parses the row count from an asyncpg ``UPDATE`` command tag."""
    assert affected_row_count(tag) == expected
