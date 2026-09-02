"""The asyncpg boundary: one ``Record`` becomes one record type.

Every function here is total over the columns its SELECT names and does
nothing else - no I/O, no validation, no error mapping. Keeping them out
of the store modules is what lets each store read as its queries.
"""

from __future__ import annotations

import json
from uuid import UUID

import asyncpg

from huron.pkg.auth import ApiKeyRecord, CredentialRecord, PrincipalRecord, SessionRecord
from huron.service.api.records import Policy, RoleBindingRecord, ServiceAccount


def binding_record(row: asyncpg.Record) -> RoleBindingRecord:
    return RoleBindingRecord(
        id=row["id"],
        principal=row["principal"],
        role_code=row["role_code"],
        scope_type=row["scope_type"],
        scope_id=row["scope_id"],
        created_by=row["created_by"],
        created_at=row["created_at"],
        expires_at=row["expires_at"],
    )


def service_account(row: asyncpg.Record) -> ServiceAccount:
    return ServiceAccount(
        principal_id=row["principal_id"],
        organization_id=row["organization_id"],
        name=row["name"],
        subject=row["subject"],
        created_by=row["created_by"],
        created_at=row["created_at"],
        disabled_at=row["disabled_at"],
    )


def policy(row: asyncpg.Record) -> Policy:
    return Policy(
        id=row["id"],
        policy_type=row["policy_type"],
        name=row["name"],
        spec=json.loads(row["spec"]),
        created_by=row["created_by"],
        created_at=row["created_at"],
    )


def api_key_record(row: asyncpg.Record) -> ApiKeyRecord:
    project_id: UUID | None = row["project_id"]
    return ApiKeyRecord(
        key_id=row["key_id"],
        subject=row["owner_subject"],
        name=row["name"],
        secret_sha256=row["secret_sha256"],
        scopes=frozenset(row["scopes"]),
        project_id=str(project_id) if project_id is not None else None,
        expires_at=row["expires_at"],
        revoked_at=row["revoked_at"],
        owner_kind=row["owner_kind"],
    )


def credential_record(row: asyncpg.Record) -> CredentialRecord:
    return CredentialRecord(
        principal_id=row["principal_id"],
        password_hash=row["password_hash"],
        updated_at=row["updated_at"],
        updated_by=row["updated_by"],
    )


def session_record(row: asyncpg.Record) -> SessionRecord:
    return SessionRecord(
        id=row["id"],
        secret_sha256=row["secret_sha256"],
        csrf_token=row["csrf_token"],
        subject=row["subject"],
        groups=frozenset(row["groups"]),
        authentication_method=row["authentication_method"],
        created_at=row["created_at"],
        last_seen_at=row["last_seen_at"],
        idle_expires_at=row["idle_expires_at"],
        absolute_expires_at=row["absolute_expires_at"],
        revoked_at=row["revoked_at"],
    )


def principal_record(row: asyncpg.Record) -> PrincipalRecord:
    return PrincipalRecord(
        id=row["id"],
        kind=row["kind"],
        subject=row["subject"],
        display_name=row["display_name"],
        idp_subject=row["idp_subject"],
        disabled_at=row["disabled_at"],
        created_at=row["created_at"],
    )


def affected_row_count(tag: str) -> int:
    """asyncpg's ``execute()`` returns a command tag like ``"UPDATE 3"``."""
    return int(tag.rsplit(" ", 1)[-1])
