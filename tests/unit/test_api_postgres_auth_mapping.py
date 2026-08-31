"""The row-mapping helpers in ``postgres_auth.py`` are pure functions over a
mapping - exercised here with plain dicts standing in for ``asyncpg.Record``,
the same duck-typed access (``row["column"]``) either provides. The store
classes that own the SQL are covered by ``tests/contract/test_auth_store.py``
against a real database instead."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from huron.service.api.postgres_auth import (
    _affected_row_count,
    _credential_record_from_row,
    _principal_record_from_row,
    _session_record_from_row,
)

pytestmark = pytest.mark.unit


def test_credential_record_from_row_maps_every_column() -> None:
    principal_id = uuid4()
    now = datetime.now(UTC)
    row = {
        "principal_id": principal_id,
        "password_hash": "$argon2id$v=19$...",
        "updated_at": now,
        "updated_by": "admin",
    }
    record = _credential_record_from_row(row)
    assert record.principal_id == principal_id
    assert record.password_hash == "$argon2id$v=19$..."
    assert record.updated_at == now
    assert record.updated_by == "admin"


def test_session_record_from_row_maps_groups_to_a_frozenset() -> None:
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
    record = _session_record_from_row(row)
    assert record.id == session_id
    assert record.groups == frozenset({"physics", "leads"})
    assert record.revoked_at is None


def test_principal_record_from_row_maps_every_column() -> None:
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
    record = _principal_record_from_row(row)
    assert record.id == principal_id
    assert record.kind == "user"
    assert record.idp_subject == "idp-sub-1"


@pytest.mark.parametrize(
    ("tag", "expected"),
    [("UPDATE 0", 0), ("UPDATE 1", 1), ("UPDATE 42", 42)],
)
def test_affected_row_count_parses_the_asyncpg_command_tag(tag: str, expected: int) -> None:
    assert _affected_row_count(tag) == expected
