"""What the API tier needs from a storage backend, and nothing about how it is stored.

Two Protocols, consumer-owned in the sense that matters: no implementation
in this package names one in its bases, and conformance is structural.
``HierarchyRepository`` declares ``RbacStore``; ``HierarchyRepository`` and
``authorization.credentials`` declare ``ApiKeyWriter``. The other three
stores here satisfy ``CredentialStore``, ``SessionStore`` and
``PrincipalStore``, which belong to ``huron.pkg.auth`` and are declared
there, beside their in-process implementations.

Every method is a contract: what an implementation must guarantee, what it
returns, and which domain error it raises - the same for the in-memory
store the unit tests run against and the Postgres store a deployment wires.
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
    ) -> RoleBindingRecord:
        """Validate one role grant against the role model and store it.

        An implementation checks the grant with ``compile_binding`` before
        anything is written, so a role that does not exist, a principal
        kind the role does not allow (any ``sa:`` principal - service
        accounts hold no roles) or a scope level the role cannot be bound
        at raises the matching ``RoleError`` subclass and leaves nothing
        behind. A binding is unique per ``(principal, role_code,
        scope_type, scope_id)``; storing the same quadruple twice raises
        ``BindingExists`` rather than succeeding as a no-op, because the
        second grant almost always means two administrators acted on stale
        views of the same list.

        Args:
            principal: The ``kind:subject`` identifier the binding is for,
                ``user:`` or ``group:``.
            role_code: The code of a role in ``huron.pkg.rbac.roles.ROLES``.
            scope_type: The level the role applies at.
            scope_id: The organization, project or dataset id, or None only
                for SYSTEM scope.
            created_by: The subject of the actor making the grant, kept on
                the record for audit.
            expires_at: When the grant stops applying, or None for a grant
                that never expires.

        Returns:
            The stored binding, with its generated id and creation time.
        """
        ...

    async def revoke_role(self, binding_id: UUID) -> RoleBindingRecord:
        """Delete one binding and return it as it was.

        Revocation is a hard delete, not a tombstone: the id names nothing
        afterwards, so revoking twice raises ``ResourceNotFound`` the second
        time, as does an id that never existed.

        Args:
            binding_id: The id of the binding to remove.

        Returns:
            The binding exactly as it was stored before removal.
        """
        ...

    async def get_role_binding(self, binding_id: UUID) -> RoleBindingRecord:
        """Return one binding by id, raising ``ResourceNotFound`` if there is none.

        Args:
            binding_id: The id of the binding to read.

        Returns:
            The stored binding.
        """
        ...

    async def bindings_for(self, identifiers: frozenset[str]) -> tuple[Binding, ...]:
        """Return the compiled capability bindings held by any of the identifiers.

        This is the read ``decide()`` consumes. The result has the shape
        ``compile_binding`` produces: for each stored grant, one binding
        carrying the role's control-plane capabilities plus one binding per
        layer-scoped capability with that grant's ``layers``. Scope
        inheritance and the expiry check at decision time belong to
        ``decide()``, so an implementation applies neither - it may only
        drop bindings that have already expired. Order carries no meaning.

        Args:
            identifiers: The caller's ``user:`` and ``group:`` identifiers;
                a binding is included when its principal is any of them.

        Returns:
            Every matching binding, or an empty tuple when ``identifiers``
            is empty or nothing is bound to any of them.
        """
        ...

    async def bindings_at(
        self, scope_type: ScopeType, scope_id: UUID | None
    ) -> list[RoleBindingRecord]:
        """Return every binding made at exactly this scope.

        No inheritance: an ORGANIZATION-scope grant is not listed under the
        organization's projects. The list is ordered by ``(principal,
        role_code)`` compared byte by byte, which is the key the bindings
        routes paginate by, so a page boundary computed in Python lands on
        the same row in every implementation.

        Args:
            scope_type: The level to list.
            scope_id: The organization, project or dataset id, or None for
                SYSTEM scope.

        Returns:
            The bindings at that scope, expired ones included, in
            ``(principal, role_code)`` byte order.
        """
        ...

    async def create_service_account(
        self, organization_id: UUID, *, name: str, subject: str, created_by: str
    ) -> ServiceAccount:
        """Create a service-account principal owned by one organization.

        ``name`` is unique within the organization: a second account with
        the same name there raises ``ServiceAccountExists``. The caller
        supplies ``subject`` (``HierarchyRepository`` derives it from the
        organization's slug and ``name``) and is responsible for the
        organization existing; an implementation that can tell it does not
        raises ``ResourceNotFound``.

        Args:
            organization_id: The organization that owns the account.
            name: The account's name, a slug unique within the organization.
            subject: The principal subject the account authenticates as.
            created_by: The subject of the actor creating the account.

        Returns:
            The new account, enabled, with its generated principal id and
            creation time.
        """
        ...

    async def get_service_account(self, principal_id: UUID) -> ServiceAccount:
        """Return one service account by principal id.

        Disabled accounts are returned like any other; ``disabled_at`` says
        so. An id that names no service account raises ``ResourceNotFound``.

        Args:
            principal_id: The account's principal id.

        Returns:
            The stored account.
        """
        ...

    async def service_account_by_subject(self, subject: str) -> ServiceAccount:
        """Return one service account by its principal subject.

        This is the lookup authorization makes for an authenticated ``sa:``
        caller, so it must return a disabled account too - the caller
        decides what ``disabled_at`` means. A subject that names no service
        account raises ``ResourceNotFound``.

        Args:
            subject: The principal subject the account authenticates as.

        Returns:
            The stored account.
        """
        ...

    async def list_service_accounts(self, organization_id: UUID) -> list[ServiceAccount]:
        """Return every service account an organization owns.

        Disabled accounts are included. The list is ordered by ``name``
        compared byte by byte - the key the service-account route paginates
        by, and a total order because ``name`` is unique per organization.

        Args:
            organization_id: The owning organization.

        Returns:
            The organization's accounts in ``name`` byte order; empty for an
            organization with none, or one that does not exist.
        """
        ...

    async def disable_service_account(
        self, principal_id: UUID, *, disabled_at: datetime
    ) -> ServiceAccount:
        """Mark a service account disabled and return it as it now is.

        Disabling is a timestamp, not a deletion: the account, its name and
        its subject stay reserved. Disabling an already-disabled account
        replaces the timestamp. An id that names no service account raises
        ``ResourceNotFound``.

        Args:
            principal_id: The account's principal id.
            disabled_at: The moment to record as the disablement time.

        Returns:
            The account with ``disabled_at`` set.
        """
        ...

    async def create_policy(
        self, *, policy_type: str, name: str, spec: dict[str, object], created_by: str
    ) -> Policy:
        """Store one policy definition.

        Policy names carry no uniqueness constraint, so two policies may
        share a ``name``; only the generated id identifies one.

        Args:
            policy_type: The policy kind, an identifier the type's consumer
                interprets.
            name: A human-readable label for the policy.
            spec: The policy's JSON-object body, stored verbatim.
            created_by: The subject of the actor creating the policy.

        Returns:
            The stored policy, with its generated id and creation time.
        """
        ...

    async def attach_policy(
        self, policy_id: UUID, *, scope_type: ScopeType, scope_id: UUID, attached_by: str
    ) -> PolicyAttachment:
        """Attach an existing policy at one organization, project or dataset.

        A policy is attached at most once per scope: repeating the same
        ``(policy_id, scope_type, scope_id)`` raises ``AttachmentExists``. A
        ``policy_id`` that names no policy raises ``ResourceNotFound``. The
        scope's own existence is the caller's concern, as for every scope
        this store sees.

        Args:
            policy_id: The policy to attach.
            scope_type: The level the policy applies at; never SYSTEM.
            scope_id: The organization, project or dataset id.
            attached_by: The subject of the actor making the attachment.

        Returns:
            The attachment, with the time it was made.
        """
        ...

    async def list_policies(self) -> list[Policy]:
        """Return every policy, ordered by ``(name, id)`` compared byte by byte.

        That is the key the policies route paginates by, and the only key
        ``policies`` can offer, since ``name`` carries no uniqueness
        constraint and ``id`` alone is not how anyone browses.

        Returns:
            All policies in ``(name, id)`` byte order.
        """
        ...


class ApiKeyWriter(ApiKeyStore, Protocol):
    """``ApiKeyStore`` plus the write path the API routes and auth need.

    ``add``/``touch_last_used`` are not part of the read-only
    ``pkg.auth.ApiKeyStore`` Protocol that ``ApiKeyResolver`` depends on
    (that module only ever reads keys); they are the repository's own
    extension, satisfied structurally by both ``MemoryApiKeyStore`` and
    ``PostgresApiKeyStore``.
    """

    async def add(self, record: ApiKeyRecord) -> None:
        """Persist a freshly issued key.

        ``record`` is what ``create_api_key`` returned: the secret is
        already reduced to its SHA-256, and ``key_id`` is the unique public
        handle a later ``get`` looks the key up by. An implementation that
        can tell ``record.project_id`` names no project raises
        ``ResourceNotFound``.

        Args:
            record: The key to store, keyed by its ``key_id``.
        """
        ...

    async def touch_last_used(self, key_id: str) -> None:
        """Record that the key was just used to authenticate a request.

        Bookkeeping only: it never affects whether the key resolves, an
        unknown ``key_id`` is silently ignored, and the caller treats a
        failure here as non-fatal.

        Args:
            key_id: The public handle of the key that was presented.
        """
        ...

    async def revoke_all_for(self, subject: str, revoked_at: datetime) -> int:
        """Revoke every still-active key a subject owns.

        Called when a service account is disabled, so its keys stop
        resolving with it. Keys already revoked keep their original
        ``revoked_at`` and are not counted.

        Args:
            subject: The owner whose keys are revoked.
            revoked_at: The moment to record on each key.

        Returns:
            How many keys this call revoked.
        """
        ...
