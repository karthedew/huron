"""Postgres-backed RBAC storage: role bindings, service accounts, policies, API keys.

Every write here is preceded by the same Python-level validation the
in-memory store performs (``compile_binding`` for grants). The database
triggers (``role_bindings_guard``, ``service_accounts_kind_guard``) exist so
a row inserted outside the API - a migration, a support script, psql - is
still refused; in the normal request path they never fire, because a bad
grant never reaches the INSERT.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from uuid import UUID

import asyncpg

from huron.pkg.auth import ApiKeyRecord
from huron.pkg.catalog.errors import DomainError
from huron.pkg.catalog.ids import uuid7
from huron.pkg.rbac import Binding, Effect, ScopeType
from huron.pkg.rbac.roles import LAYER_SCOPED_CAPABILITIES, compile_binding
from huron.service.api.repository import (
    Policy,
    PolicyAttachment,
    ResourceNotFound,
    RoleBindingRecord,
    ServiceAccount,
)


def _binding_record_from_row(row: asyncpg.Record) -> RoleBindingRecord:
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


def _service_account_from_row(row: asyncpg.Record) -> ServiceAccount:
    return ServiceAccount(
        principal_id=row["principal_id"],
        organization_id=row["organization_id"],
        name=row["name"],
        subject=row["subject"],
        created_by=row["created_by"],
        created_at=row["created_at"],
    )


def _policy_from_row(row: asyncpg.Record) -> Policy:
    return Policy(
        id=row["id"],
        policy_type=row["policy_type"],
        name=row["name"],
        spec=json.loads(row["spec"]),
        created_by=row["created_by"],
        created_at=row["created_at"],
    )


class PostgresRbacStore:
    """Real storage for the tables ``migrations/versions/0002_rbac.py`` creates."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def grant_role(
        self,
        *,
        principal: str,
        role_code: str,
        scope_type: ScopeType,
        scope_id: UUID | None,
        created_by: str,
        expires_at: datetime | None = None,
    ) -> RoleBindingRecord:
        principal_kind = "service_account" if principal.startswith("sa:") else "user"
        # The return value is discarded - what matters is that an invalid
        # role/kind/scope combination raises a RoleError here, before the
        # database is touched at all. role_bindings_guard checks the same
        # invariants; it backstops rows written outside this store.
        compile_binding(
            role_code,
            principal_identifier=principal,
            principal_kind=principal_kind,
            scope_type=scope_type,
            scope_id=scope_id,
            expires_at=expires_at,
        )
        record = RoleBindingRecord(
            id=uuid7(),
            principal=principal,
            role_code=role_code,
            scope_type=scope_type.value,
            scope_id=scope_id,
            created_by=created_by,
            created_at=datetime.now(UTC),
            expires_at=expires_at,
        )
        try:
            await self._pool.execute(
                """
                INSERT INTO role_bindings
                    (id, principal, role_code, scope_type, scope_id, effect,
                     expires_at, created_by, created_at)
                VALUES ($1, $2, $3, $4, $5, 'ALLOW', $6, $7, $8)
                """,
                record.id,
                record.principal,
                record.role_code,
                record.scope_type,
                record.scope_id,
                record.expires_at,
                record.created_by,
                record.created_at,
            )
        except asyncpg.UniqueViolationError as exc:
            raise DomainError("an identical role binding already exists") from exc
        return record

    async def revoke_role(self, binding_id: UUID) -> RoleBindingRecord:
        row = await self._pool.fetchrow(
            """
            DELETE FROM role_bindings WHERE id = $1
            RETURNING id, principal, role_code, scope_type, scope_id,
                      created_by, created_at, expires_at
            """,
            binding_id,
        )
        if row is None:
            raise ResourceNotFound(f"role binding does not exist: {binding_id}")
        return _binding_record_from_row(row)

    async def get_role_binding(self, binding_id: UUID) -> RoleBindingRecord:
        row = await self._pool.fetchrow(
            """
            SELECT id, principal, role_code, scope_type, scope_id,
                   created_by, created_at, expires_at
            FROM role_bindings WHERE id = $1
            """,
            binding_id,
        )
        if row is None:
            raise ResourceNotFound(f"role binding does not exist: {binding_id}")
        return _binding_record_from_row(row)

    async def bindings_for(self, identifiers: frozenset[str]) -> tuple[Binding, ...]:
        """Reconstruct compiled ``Binding`` values by joining the grant to its role.

        Scope inheritance and expiry-at-check-time stay in ``decide()``; only
        the "hasn't expired yet" filter runs here, to keep the row count (and
        therefore the per-request cache entry) small. The shape mirrors
        ``compile_binding``: one binding for the role's non-layer capabilities,
        plus one binding per ``data.read``/``data.write`` row, each carrying
        that row's own ``layers`` (NULL meaning every layer).
        """
        if not identifiers:
            return ()
        rows = await self._pool.fetch(
            """
            SELECT rb.id, rb.principal, rb.scope_type, rb.scope_id, rb.effect,
                   rb.expires_at, rc.capability_code, rc.layers
            FROM role_bindings rb
            JOIN role_capabilities rc ON rc.role_code = rb.role_code
            WHERE rb.principal = ANY($1::text[])
              AND (rb.expires_at IS NULL OR rb.expires_at > now())
            """,
            list(identifiers),
        )
        grouped: dict[UUID, list[asyncpg.Record]] = defaultdict(list)
        for row in rows:
            grouped[row["id"]].append(row)

        bindings: list[Binding] = []
        for entries in grouped.values():
            head = entries[0]
            scope_type = ScopeType(head["scope_type"])
            effect = Effect(head["effect"])
            control_capabilities = frozenset(
                entry["capability_code"]
                for entry in entries
                if entry["capability_code"] not in LAYER_SCOPED_CAPABILITIES
            )
            if control_capabilities:
                bindings.append(
                    Binding(
                        principal=head["principal"],
                        capabilities=control_capabilities,
                        scope_type=scope_type,
                        scope_id=head["scope_id"],
                        effect=effect,
                        expires_at=head["expires_at"],
                    )
                )
            for entry in entries:
                if entry["capability_code"] not in LAYER_SCOPED_CAPABILITIES:
                    continue
                layers = entry["layers"]
                bindings.append(
                    Binding(
                        principal=head["principal"],
                        capabilities=frozenset({entry["capability_code"]}),
                        scope_type=scope_type,
                        scope_id=head["scope_id"],
                        effect=effect,
                        expires_at=head["expires_at"],
                        layers=frozenset(layers) if layers is not None else None,
                    )
                )
        return tuple(bindings)

    async def bindings_at(
        self, scope_type: ScopeType, scope_id: UUID | None
    ) -> list[RoleBindingRecord]:
        rows = await self._pool.fetch(
            """
            SELECT id, principal, role_code, scope_type, scope_id,
                   created_by, created_at, expires_at
            FROM role_bindings
            WHERE scope_type = $1 AND scope_id IS NOT DISTINCT FROM $2
            ORDER BY principal COLLATE "C", role_code COLLATE "C"
            """,
            scope_type.value,
            scope_id,
        )
        return [_binding_record_from_row(row) for row in rows]

    async def create_service_account(
        self, organization_id: UUID, *, name: str, subject: str, created_by: str
    ) -> ServiceAccount:
        principal_id = uuid7()
        created_at = datetime.now(UTC)
        # One transaction: a service_accounts row must never exist without its
        # principals row, or vice versa. service_accounts_kind_guard checks the
        # kind is right; it cannot check that the principal row exists at all,
        # since a crash between the two inserts is exactly what the trigger
        # can't see.
        try:
            async with self._pool.acquire() as connection, connection.transaction():
                await connection.execute(
                    """
                    INSERT INTO principals (id, kind, subject, created_at)
                    VALUES ($1, 'service_account', $2, $3)
                    """,
                    principal_id,
                    subject,
                    created_at,
                )
                await connection.execute(
                    """
                    INSERT INTO service_accounts
                        (principal_id, organization_id, name, created_by, created_at)
                    VALUES ($1, $2, $3, $4, $5)
                    """,
                    principal_id,
                    organization_id,
                    name,
                    created_by,
                    created_at,
                )
        except asyncpg.ForeignKeyViolationError as exc:
            raise ResourceNotFound(f"organization does not exist: {organization_id}") from exc
        except asyncpg.UniqueViolationError as exc:
            raise DomainError(f"service account already exists: {name}") from exc
        return ServiceAccount(principal_id, organization_id, name, subject, created_by, created_at)

    async def get_service_account(self, principal_id: UUID) -> ServiceAccount:
        row = await self._pool.fetchrow(
            """
            SELECT sa.principal_id, sa.organization_id, sa.name, p.subject,
                   sa.created_by, sa.created_at
            FROM service_accounts sa JOIN principals p ON p.id = sa.principal_id
            WHERE sa.principal_id = $1
            """,
            principal_id,
        )
        if row is None:
            raise ResourceNotFound(f"service account does not exist: {principal_id}")
        return _service_account_from_row(row)

    async def list_service_accounts(self, organization_id: UUID) -> list[ServiceAccount]:
        rows = await self._pool.fetch(
            """
            SELECT sa.principal_id, sa.organization_id, sa.name, p.subject,
                   sa.created_by, sa.created_at
            FROM service_accounts sa JOIN principals p ON p.id = sa.principal_id
            WHERE sa.organization_id = $1
            ORDER BY sa.name
            """,
            organization_id,
        )
        return [_service_account_from_row(row) for row in rows]

    async def create_policy(
        self, *, policy_type: str, name: str, spec: dict[str, object], created_by: str
    ) -> Policy:
        record = Policy(
            id=uuid7(),
            policy_type=policy_type,
            name=name,
            spec=spec,
            created_by=created_by,
            created_at=datetime.now(UTC),
        )
        await self._pool.execute(
            """
            INSERT INTO policies (id, policy_type, name, spec, created_by, created_at)
            VALUES ($1, $2, $3, $4::jsonb, $5, $6)
            """,
            record.id,
            record.policy_type,
            record.name,
            json.dumps(record.spec),
            record.created_by,
            record.created_at,
        )
        return record

    async def attach_policy(
        self, policy_id: UUID, *, scope_type: ScopeType, scope_id: UUID, attached_by: str
    ) -> PolicyAttachment:
        attached_at = datetime.now(UTC)
        try:
            await self._pool.execute(
                """
                INSERT INTO policy_attachments
                    (policy_id, scope_type, scope_id, attached_by, attached_at)
                VALUES ($1, $2, $3, $4, $5)
                """,
                policy_id,
                scope_type.value,
                scope_id,
                attached_by,
                attached_at,
            )
        except asyncpg.ForeignKeyViolationError as exc:
            raise ResourceNotFound(f"policy does not exist: {policy_id}") from exc
        except asyncpg.UniqueViolationError as exc:
            raise DomainError("policy is already attached at this scope") from exc
        return PolicyAttachment(policy_id, scope_type.value, scope_id, attached_by, attached_at)

    async def list_policies(self) -> list[Policy]:
        rows = await self._pool.fetch(
            "SELECT id, policy_type, name, spec, created_by, created_at FROM policies ORDER BY name"
        )
        return [_policy_from_row(row) for row in rows]


class PostgresApiKeyStore:
    """The ``api_keys`` table behind ``pkg.auth.ApiKeyStore``."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def get(self, key_id: str) -> ApiKeyRecord | None:
        row = await self._pool.fetchrow(
            """
            SELECT key_id, owner_subject, name, secret_sha256, scopes, project_id,
                   expires_at, revoked_at, owner_kind
            FROM api_keys WHERE key_id = $1
            """,
            key_id,
        )
        if row is None:
            return None
        return _api_key_record_from_row(row)

    async def add(self, record: ApiKeyRecord) -> None:
        project_id = UUID(record.project_id) if record.project_id is not None else None
        try:
            await self._pool.execute(
                """
                INSERT INTO api_keys
                    (id, key_id, owner_subject, name, secret_sha256, scopes,
                     project_id, expires_at, revoked_at, owner_kind, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                """,
                uuid7(),
                record.key_id,
                record.subject,
                record.name,
                record.secret_sha256,
                list(record.scopes),
                project_id,
                record.expires_at,
                record.revoked_at,
                record.owner_kind,
                datetime.now(UTC),
            )
        except asyncpg.ForeignKeyViolationError as exc:
            raise ResourceNotFound(f"project does not exist: {project_id}") from exc

    async def touch_last_used(self, key_id: str) -> None:
        await self._pool.execute(
            "UPDATE api_keys SET last_used_at = now() WHERE key_id = $1", key_id
        )


def _api_key_record_from_row(row: asyncpg.Record) -> ApiKeyRecord:
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
