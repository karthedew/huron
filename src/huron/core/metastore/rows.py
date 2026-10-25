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
from typing import TYPE_CHECKING

from huron.core.hierarchy.types import (
    Dataset,
    Organization,
    Project,
)
from huron.core.security.apikeys import ApiKeyRecord
from huron.core.security.principals import PrincipalRecord
from huron.core.security.types import Policy, RoleBindingRecord, ServiceAccount

if TYPE_CHECKING:
    from uuid import UUID

    import asyncpg


def binding_record(row: asyncpg.Record) -> RoleBindingRecord:
    """Decode one ``role_bindings`` row.

    Args:
        row: A row selecting ``id, principal, role_code, scope_type,
            scope_id, created_by, created_at, expires_at``.

    Returns:
        The binding as the catalog stores it; ``scope_type`` stays the
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
        The account, disabled or not, as the catalog stores it.
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
        The policy as the catalog stores it, with ``spec`` as a mapping.
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


def organization(row: asyncpg.Record) -> Organization:
    """Decode one ``organizations`` row.

    Args:
        row: A row selecting ``id, slug, title, description, generation,
            version, created_at``.

    Returns:
        The organization as the catalog stores it.
    """
    return Organization(
        id=row["id"],
        slug=row["slug"],
        title=row["title"],
        description=row["description"],
        generation=row["generation"],
        version=row["version"],
        created_at=row["created_at"],
    )


def project(row: asyncpg.Record) -> Project:
    """Decode one ``projects`` row.

    ``classification_default`` becomes ``Project.data_classification``:
    the column and the record field are the same value under different
    names, the column's naming a fact about the table, the field's a fact
    about what the rest of the tier calls it.

    Args:
        row: A row selecting ``id, organization_id, slug, title,
            description, classification_default, generation, version,
            created_at``.

    Returns:
        The project as the catalog stores it.
    """
    return Project(
        id=row["id"],
        organization_id=row["organization_id"],
        slug=row["slug"],
        title=row["title"],
        description=row["description"],
        data_classification=row["classification_default"],
        generation=row["generation"],
        version=row["version"],
        created_at=row["created_at"],
    )


def dataset(row: asyncpg.Record) -> Dataset:
    """Decode one ``datasets`` row.

    The row's own ``data_classification`` column is not decoded here:
    nothing in the ``HierarchyStore`` port ever reads a dataset's
    classification back, only its owning project's.

    Args:
        row: A row selecting ``id, project_id, slug, title, description,
            profile_name, profile_version, entry_layer, lifecycle_state,
            generation, version, created_at``.

    Returns:
        The dataset as the catalog stores it.
    """
    return Dataset(
        id=row["id"],
        project_id=row["project_id"],
        slug=row["slug"],
        title=row["title"],
        description=row["description"],
        profile_name=row["profile_name"],
        profile_version=row["profile_version"],
        entry_layer=row["entry_layer"],
        lifecycle_state=row["lifecycle_state"],
        generation=row["generation"],
        version=row["version"],
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
