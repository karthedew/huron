"""What the API tier needs from a storage backend, and nothing about how it is stored.

Two Protocols, consumer-owned in the sense that matters: no implementation
in this package names one in its bases, and conformance is structural.
``HierarchyRepository`` declares ``RbacStore``; ``HierarchyRepository`` and
``authorization.credentials`` declare ``ApiKeyWriter``. The other three
stores here satisfy ``CredentialStore``, ``SessionStore`` and
``PrincipalStore``, which belong to ``huron.pkg.auth`` and are declared
there, beside their in-process implementations.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from huron.pkg.auth import ApiKeyRecord, ApiKeyStore
from huron.pkg.rbac import Binding, ScopeType
from huron.service.api.records import Policy, PolicyAttachment, RoleBindingRecord, ServiceAccount


class RbacStore(Protocol):
    """What ``HierarchyRepository`` needs from an RBAC storage backend.

    ``InMemoryRbacStore`` and ``PostgresRbacStore`` both conform
    structurally - neither imports the other, following the same
    consumer-owned-Protocol idiom as ``pkg/catalog/ports.py``. Scope
    existence (does this organization/project/dataset actually exist) is a
    hierarchy concern and stays on ``HierarchyRepository``; a store only
    ever sees a ``scope_type``/``scope_id`` pair it takes on faith.
    """

    async def grant_role(
        self,
        *,
        principal: str,
        role_code: str,
        scope_type: ScopeType,
        scope_id: UUID | None,
        created_by: str,
        expires_at: datetime | None = None,
    ) -> RoleBindingRecord: ...

    async def revoke_role(self, binding_id: UUID) -> RoleBindingRecord: ...

    async def get_role_binding(self, binding_id: UUID) -> RoleBindingRecord: ...

    async def bindings_for(self, identifiers: frozenset[str]) -> tuple[Binding, ...]: ...

    async def bindings_at(
        self, scope_type: ScopeType, scope_id: UUID | None
    ) -> list[RoleBindingRecord]: ...

    async def create_service_account(
        self, organization_id: UUID, *, name: str, subject: str, created_by: str
    ) -> ServiceAccount: ...

    async def get_service_account(self, principal_id: UUID) -> ServiceAccount: ...

    async def service_account_by_subject(self, subject: str) -> ServiceAccount: ...

    async def list_service_accounts(self, organization_id: UUID) -> list[ServiceAccount]: ...

    async def disable_service_account(
        self, principal_id: UUID, *, disabled_at: datetime
    ) -> ServiceAccount: ...

    async def create_policy(
        self, *, policy_type: str, name: str, spec: dict[str, object], created_by: str
    ) -> Policy: ...

    async def attach_policy(
        self, policy_id: UUID, *, scope_type: ScopeType, scope_id: UUID, attached_by: str
    ) -> PolicyAttachment: ...

    async def list_policies(self) -> list[Policy]: ...


class ApiKeyWriter(ApiKeyStore, Protocol):
    """``ApiKeyStore`` plus the write path the API routes and auth need.

    ``add``/``touch_last_used`` are not part of the read-only
    ``pkg.auth.ApiKeyStore`` Protocol that ``ApiKeyResolver`` depends on
    (that module only ever reads keys); they are the repository's own
    extension, satisfied structurally by both ``MemoryApiKeyStore`` and
    ``PostgresApiKeyStore``.
    """

    async def add(self, record: ApiKeyRecord) -> None: ...

    async def touch_last_used(self, key_id: str) -> None: ...

    async def revoke_all_for(self, subject: str, revoked_at: datetime) -> int: ...
