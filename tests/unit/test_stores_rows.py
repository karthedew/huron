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

from huron.service.api.stores.rows import (
    affected_row_count,
    api_key_record,
    binding_record,
    credential_record,
    policy,
    principal_record,
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


@pytest.mark.parametrize(
    ("tag", "expected"),
    [("UPDATE 0", 0), ("UPDATE 1", 1), ("UPDATE 42", 42)],
)
def test_affected_row_count_parses_the_asyncpg_command_tag(tag: str, expected: int) -> None:
    """``affected_row_count`` parses the row count from an asyncpg ``UPDATE`` command tag."""
    assert affected_row_count(tag) == expected
