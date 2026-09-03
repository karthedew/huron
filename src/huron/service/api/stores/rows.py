"""The asyncpg boundary: one ``Record`` becomes one record type.

Every function here is total over the columns its SELECT names and does
nothing else - no I/O, no validation, no error mapping. Keeping them out
of the store modules is what lets each store read as its queries.

This is one store's private decoding of its own SELECT: each function
names exactly the columns the store's query selects, in the store's own
aliases, and nothing outside ``stores`` may import it - the package is
entered only through its public surface, which import-linter enforces.
"""

from __future__ import annotations

import json
from uuid import UUID

import asyncpg

from huron.pkg.auth import ApiKeyRecord, CredentialRecord, PrincipalRecord, SessionRecord
from huron.service.api.records import Policy, RoleBindingRecord, ServiceAccount


def binding_record(row: asyncpg.Record) -> RoleBindingRecord:
    """Decode one ``role_bindings`` row.

    Args:
        row: A row selecting ``id, principal, role_code, scope_type,
            scope_id, created_by, created_at, expires_at``.

    Returns:
        The binding as the API tier stores it; ``scope_type`` stays the
        stored string rather than becoming a ``ScopeType``.
    """
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
    """Decode one ``service_accounts`` row joined to its ``principals`` row.

    Args:
        row: A row selecting ``principal_id, organization_id, name,
            subject, created_by, created_at, disabled_at``; ``subject`` and
            ``disabled_at`` come from the joined principal.

    Returns:
        The account, disabled or not, as the API tier stores it.
    """
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
    """Decode one ``policies`` row, parsing its ``jsonb`` spec.

    asyncpg hands ``jsonb`` back as its text form, so ``spec`` is decoded
    here into the mapping the record carries.

    Args:
        row: A row selecting ``id, policy_type, name, spec, created_by,
            created_at``.

    Returns:
        The policy as the API tier stores it, with ``spec`` as a mapping.
    """
    return Policy(
        id=row["id"],
        policy_type=row["policy_type"],
        name=row["name"],
        spec=json.loads(row["spec"]),
        created_by=row["created_by"],
        created_at=row["created_at"],
    )


def api_key_record(row: asyncpg.Record) -> ApiKeyRecord:
    """Decode one ``api_keys`` row into the record ``ApiKeyResolver`` reads.

    The column names differ from the record's: ``owner_subject`` becomes
    ``subject``, the ``scopes`` array becomes a frozenset, and the uuid
    ``project_id`` becomes the string form the record and the ``Principal``
    built from it carry (or None for a key bound to no project).

    Args:
        row: A row selecting ``key_id, owner_subject, name, secret_sha256,
            scopes, project_id, expires_at, revoked_at, owner_kind``.

    Returns:
        The key record, revoked or not.
    """
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
    """Decode one ``local_credentials`` row.

    Args:
        row: A row selecting ``principal_id, password_hash, updated_at,
            updated_by``.

    Returns:
        The stored password credential, hash included.
    """
    return CredentialRecord(
        principal_id=row["principal_id"],
        password_hash=row["password_hash"],
        updated_at=row["updated_at"],
        updated_by=row["updated_by"],
    )


def session_record(row: asyncpg.Record) -> SessionRecord:
    """Decode one ``sessions`` row, turning the ``groups`` array into a frozenset.

    Args:
        row: A row selecting ``id, secret_sha256, csrf_token, subject,
            groups, authentication_method, created_at, last_seen_at,
            idle_expires_at, absolute_expires_at, revoked_at``.

    Returns:
        The session as stored, whatever its expiry or revocation state;
        judging that is ``SessionResolver``'s job.
    """
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
    """Decode one ``principals`` row.

    Args:
        row: A row selecting ``id, kind, subject, display_name,
            idp_subject, disabled_at, created_at``.

    Returns:
        The principal, user or service account, disabled or not.
    """
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
    """Read the number of rows a statement touched off its command tag.

    asyncpg's ``execute()`` returns a command tag like ``"UPDATE 3"``. The
    count is the final space-separated field, which is what a store returns
    from a bulk revoke.

    Args:
        tag: The command tag ``execute()`` returned for an UPDATE or DELETE.

    Returns:
        The row count the tag ends with.
    """
    return int(tag.rsplit(" ", 1)[-1])
