"""Both implementations of ``RbacStore``: role bindings, service accounts, policies.

Every write in ``PostgresRbacStore`` is preceded by the same Python-level
validation ``InMemoryRbacStore`` performs (``compile_binding`` for grants).
The database triggers (``role_bindings_guard``, ``service_accounts_kind_guard``)
exist so a row inserted outside the API - a migration, a support script,
psql - is still refused; in the normal request path they never fire,
because a bad grant never reaches the INSERT.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from threading import RLock
from typing import TYPE_CHECKING

import asyncpg

from huron.core.foundation.errors import ResourceNotFound
from huron.core.foundation.identifiers import uuid7
from huron.core.security.errors import (
    AttachmentExists,
    BindingExists,
    ServiceAccountExists,
    UsernameTaken,
)
from huron.core.security.roles import LAYER_SCOPED_CAPABILITIES, ScopeNotBindable, compile_binding
from huron.core.security.rules import Binding, Effect, ScopeType
from huron.core.security.types import Policy, PolicyAttachment, RoleBindingRecord, ServiceAccount

from .rows import binding_record, policy, service_account

if TYPE_CHECKING:
    from uuid import UUID

#: Postgres's name for ``service_accounts``' table-level UNIQUE constraint,
#: absent an explicit ``CONSTRAINT`` clause in the migration.
_SERVICE_ACCOUNT_NAME_CONSTRAINT = "service_accounts_organization_id_name_key"

#: Postgres's name for ``principals.subject``'s column-level UNIQUE
#: constraint, absent an explicit ``CONSTRAINT`` clause in the migration.
_PRINCIPAL_SUBJECT_CONSTRAINT = "principals_subject_key"


class InMemoryRbacStore:
    """The reference RBAC store: precompiled bindings held in process memory.

    This is what every unit test runs against; a composition root wires
    ``PostgresRbacStore`` instead for a real deployment.

    Each grant is compiled once, when it is stored, so ``bindings_for`` is a
    lookup rather than a recompilation. Nothing here survives the process.
    """

    def __init__(self) -> None:
        """Start with no bindings, service accounts, policies or attachments.

        One re-entrant lock serialises the writes; the compiled-binding map
        is keyed by binding id so a revoke drops exactly its own bindings.
        """
        self._role_bindings: dict[UUID, RoleBindingRecord] = {}
        self._service_accounts: dict[UUID, ServiceAccount] = {}
        self._policies: dict[UUID, Policy] = {}
        self._policy_attachments: list[PolicyAttachment] = []
        self._compiled: dict[UUID, tuple[Binding, ...]] = {}
        self._lock = RLock()

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
        """Validate against the role model, compile, and store one grant.

        ``compile_binding`` raises RoleError subclasses when the role does
        not exist, the principal kind is not allowed (e.g. a service account
        for any role), or the scope level is not bindable. The principal
        kind is read off the identifier's prefix: ``sa:`` is a service
        account, anything else a user. Validation happens before the
        duplicate check, so an invalid grant is refused as invalid even when
        an identical one is already stored.

        Args:
            principal: The ``kind:subject`` identifier the binding is for.
            role_code: The code of a role in ``huron.core.security.roles.ROLES``.
            scope_type: The level the role applies at.
            scope_id: The organization, project or dataset id, or None for
                SYSTEM scope.
            created_by: The subject of the actor making the grant.
            expires_at: When the grant stops applying, or None for never.

        Returns:
            The stored binding, with a fresh id and the current time.

        Raises:
            BindingExists: If a binding with the same principal, role and
                scope is already stored.
        """
        principal_kind = "service_account" if principal.startswith("sa:") else "user"
        compiled = compile_binding(
            role_code,
            principal_identifier=principal,
            principal_kind=principal_kind,
            scope_type=scope_type,
            scope_id=scope_id,
            expires_at=expires_at,
        )
        with self._lock:
            if any(
                item.principal == principal
                and item.role_code == role_code
                and item.scope_type == scope_type.value
                and item.scope_id == scope_id
                for item in self._role_bindings.values()
            ):
                raise BindingExists("an identical role binding already exists")
            record = RoleBindingRecord(
                uuid7(),
                principal,
                role_code,
                scope_type.value,
                scope_id,
                created_by,
                datetime.now(UTC),
                expires_at,
            )
            self._role_bindings[record.id] = record
            self._compiled[record.id] = compiled
            return record

    async def revoke_role(self, binding_id: UUID) -> RoleBindingRecord:
        """Delete one binding, and its compiled capabilities with it.

        The compiled bindings go in the same locked step, so ``bindings_for``
        never sees a revoked grant.

        Args:
            binding_id: The id of the binding to remove.

        Returns:
            The binding as it was stored.

        Raises:
            ResourceNotFound: If no binding has this id.
        """
        with self._lock:
            record = self._role_bindings.pop(binding_id, None)
            if record is None:
                raise ResourceNotFound(f"role binding does not exist: {binding_id}")
            self._compiled.pop(binding_id, None)
            return record

    async def get_role_binding(self, binding_id: UUID) -> RoleBindingRecord:
        """Return one binding by id.

        Args:
            binding_id: The id of the binding to read.

        Returns:
            The stored binding.

        Raises:
            ResourceNotFound: If no binding has this id.
        """
        record = self._role_bindings.get(binding_id)
        if record is None:
            raise ResourceNotFound(f"role binding does not exist: {binding_id}")
        return record

    async def bindings_for(self, identifiers: frozenset[str]) -> tuple[Binding, ...]:
        """Return every compiled capability binding whose principal the caller is.

        Nothing is filtered beyond the principal match - not even an expired
        grant - because scope inheritance and expiry are ``decide()``'s to
        judge.

        Args:
            identifiers: The caller's ``user:`` and ``group:`` identifiers.

        Returns:
            The compiled bindings of every stored grant to any of them, in
            grant order.
        """
        return tuple(
            binding
            for record_id, bindings in self._compiled.items()
            if self._role_bindings[record_id].principal in identifiers
            for binding in bindings
        )

    async def bindings_at(
        self, scope_type: ScopeType, scope_id: UUID | None
    ) -> list[RoleBindingRecord]:
        """Return every binding made at exactly this scope.

        Sorted by ``(principal, role_code)`` with Python's own string order,
        which for these ASCII identifiers is byte order - the same order the
        Postgres store's ``COLLATE "C"`` produces, so a page cursor computed
        against either store continues correctly on the other.

        Args:
            scope_type: The level to list.
            scope_id: The organization, project or dataset id, or None for
                SYSTEM scope.

        Returns:
            The bindings at that scope in ``(principal, role_code)`` order.
        """
        return sorted(
            (
                item
                for item in self._role_bindings.values()
                if item.scope_type == scope_type.value and item.scope_id == scope_id
            ),
            key=lambda item: (item.principal, item.role_code),
        )

    async def create_service_account(
        self, organization_id: UUID, *, name: str, subject: str, created_by: str
    ) -> ServiceAccount:
        """Store a service account owned by one organization.

        The organization's existence is taken on faith, as every scope is
        here; ``ServiceAccounts`` has already resolved it to derive
        ``subject``.

        Args:
            organization_id: The organization that owns the account.
            name: The account's name, unique within the organization.
            subject: The principal subject the account authenticates as.
            created_by: The subject of the actor creating the account.

        Returns:
            The new account, enabled, with a fresh principal id and the
            current time.

        Raises:
            ServiceAccountExists: If the organization already has an account
                with this ``name``.
        """
        with self._lock:
            if any(
                item.organization_id == organization_id and item.name == name
                for item in self._service_accounts.values()
            ):
                raise ServiceAccountExists(f"service account already exists: {name}")
            record = ServiceAccount(
                uuid7(), organization_id, name, subject, created_by, datetime.now(UTC)
            )
            self._service_accounts[record.principal_id] = record
            return record

    async def get_service_account(self, principal_id: UUID) -> ServiceAccount:
        """Return one service account by principal id, disabled or not.

        Args:
            principal_id: The account's principal id.

        Returns:
            The stored account.

        Raises:
            ResourceNotFound: If no service account has this principal id.
        """
        record = self._service_accounts.get(principal_id)
        if record is None:
            raise ResourceNotFound(f"service account does not exist: {principal_id}")
        return record

    async def service_account_by_subject(self, subject: str) -> ServiceAccount:
        """Return one service account by subject, disabled or not.

        Args:
            subject: The principal subject the account authenticates as.

        Returns:
            The stored account.

        Raises:
            ResourceNotFound: If no service account has this subject.
        """
        with self._lock:
            for record in self._service_accounts.values():
                if record.subject == subject:
                    return record
        raise ResourceNotFound(f"service account does not exist: {subject}")

    async def list_service_accounts(self, organization_id: UUID) -> list[ServiceAccount]:
        """Return every service account an organization owns, disabled ones included.

        Args:
            organization_id: The owning organization.

        Returns:
            The organization's accounts sorted by ``name``, which is byte
            order for the lowercase slugs names are restricted to.
        """
        items = [
            item
            for item in self._service_accounts.values()
            if item.organization_id == organization_id
        ]
        return sorted(items, key=lambda item: item.name)

    async def disable_service_account(
        self, principal_id: UUID, *, disabled_at: datetime
    ) -> ServiceAccount:
        """Mark a service account disabled and return it.

        The stored record is updated in place, so a ``ServiceAccount``
        handed out earlier by ``get_service_account`` shows the change too.
        Disabling is idempotent: an already-disabled account keeps its
        original timestamp, and ``disabled_at`` is discarded.

        Args:
            principal_id: The account's principal id.
            disabled_at: The moment to record as the disablement time, if
                the account is not already disabled.

        Returns:
            The account with ``disabled_at`` set - to this call's instant
            on a first disable, or unchanged if it was already disabled.

        Raises:
            ResourceNotFound: If no service account has this principal id.
        """
        with self._lock:
            record = self._service_accounts.get(principal_id)
            if record is None:
                raise ResourceNotFound(f"service account does not exist: {principal_id}")
            if record.disabled_at is None:
                record.disabled_at = disabled_at
            return record

    async def create_policy(
        self, *, policy_type: str, name: str, spec: dict[str, object], created_by: str
    ) -> Policy:
        """Store one policy definition under a fresh id.

        Args:
            policy_type: The policy kind.
            name: A human-readable label; not required to be unique.
            spec: The policy's JSON-object body, kept as given.
            created_by: The subject of the actor creating the policy.

        Returns:
            The stored policy, with a fresh id and the current time.
        """
        with self._lock:
            record = Policy(uuid7(), policy_type, name, spec, created_by, datetime.now(UTC))
            self._policies[record.id] = record
            return record

    async def attach_policy(
        self, policy_id: UUID, *, scope_type: ScopeType, scope_id: UUID, attached_by: str
    ) -> PolicyAttachment:
        """Attach an existing policy at one scope, once.

        Args:
            policy_id: The policy to attach.
            scope_type: The level the policy applies at.
            scope_id: The organization, project or dataset id.
            attached_by: The subject of the actor making the attachment.

        Returns:
            The attachment, stamped with the current time.

        Raises:
            ResourceNotFound: If no policy has this id.
            AttachmentExists: If the policy is already attached at exactly
                this scope.
        """
        if policy_id not in self._policies:
            raise ResourceNotFound(f"policy does not exist: {policy_id}")
        with self._lock:
            if any(
                item.policy_id == policy_id
                and item.scope_type == scope_type.value
                and item.scope_id == scope_id
                for item in self._policy_attachments
            ):
                raise AttachmentExists("policy is already attached at this scope")
            attachment = PolicyAttachment(
                policy_id, scope_type.value, scope_id, attached_by, datetime.now(UTC)
            )
            self._policy_attachments.append(attachment)
            return attachment

    async def list_policies(self) -> list[Policy]:
        """Return every policy, ordered by ``(name, id)``.

        That is the same key the cursor advances by, and the only key
        ``policies`` can offer, since ``name`` carries no uniqueness
        constraint. The id compares as its canonical string, which orders
        the same as the uuid bytes Postgres compares, so both stores agree.

        Returns:
            All policies in ``(name, id)`` order.
        """
        return sorted(self._policies.values(), key=lambda item: (item.name, str(item.id)))


class PostgresRbacStore:
    """Real storage for the tables ``migrations/versions/0002_rbac.py`` creates.

    Shares one ``asyncpg`` pool with the other Postgres stores and holds no
    state of its own. ``service_accounts.organization_id`` is a foreign key
    to ``organizations``, so this store is only wired once the hierarchy's
    rows are real Postgres rows too. Every constraint violation a request
    can legitimately hit is translated into the same domain error the
    in-memory store raises; the guard triggers repeat the same checks for
    rows written outside the API. Ids and creation times are generated in
    Python before the INSERT, so the returned record is exactly what was
    written; only expiry filtering reads the database clock.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        """Bind the store to a connection pool.

        Args:
            pool: The pool every statement acquires from; the store never
                closes it, its owner does.
        """
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
        """Validate one grant against the role model, then insert it.

        ``compile_binding`` runs first for its checks alone, so a role that
        does not exist, a principal kind the role does not allow (any
        ``sa:`` principal) or an unbindable scope level raises the matching
        RoleError subclass before the database is touched; the
        ``role_bindings_guard`` trigger repeats the same checks only for
        rows written outside this store. The row is stored with effect
        ``ALLOW``. Duplicates are refused by ``role_bindings_no_duplicates``,
        which compares NULLs as equal so two SYSTEM grants of one role to
        one principal collide like any other pair.

        Args:
            principal: The ``kind:subject`` identifier the binding is for.
            role_code: The code of a role in ``huron.core.security.roles.ROLES``.
            scope_type: The level the role applies at.
            scope_id: The organization, project or dataset id, or None for
                SYSTEM scope.
            created_by: The subject of the actor making the grant.
            expires_at: When the grant stops applying, or None for never.

        Returns:
            The binding as inserted, with a fresh id and creation time.

        Raises:
            BindingExists: If the unique constraint refused the row because
                the same principal already holds this role at this scope.
        """
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
            raise BindingExists("an identical role binding already exists") from exc
        return record

    async def revoke_role(self, binding_id: UUID) -> RoleBindingRecord:
        """Delete one binding row and return what it held.

        One ``DELETE ... RETURNING``, so the read and the delete cannot
        disagree about whether the row existed.

        Args:
            binding_id: The id of the binding to remove.

        Returns:
            The binding as it was stored.

        Raises:
            ResourceNotFound: If no row had this id.
        """
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
        return binding_record(row)

    async def get_role_binding(self, binding_id: UUID) -> RoleBindingRecord:
        """Return one binding row by id.

        Args:
            binding_id: The id of the binding to read.

        Returns:
            The stored binding.

        Raises:
            ResourceNotFound: If no row has this id.
        """
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
        return binding_record(row)

    async def bindings_for(self, identifiers: frozenset[str]) -> tuple[Binding, ...]:
        """Reconstruct compiled ``Binding`` values by joining the grant to its role.

        Scope inheritance and expiry-at-check-time stay in ``decide()``; only
        the "hasn't expired yet" filter runs here, to keep the row count (and
        therefore the per-request cache entry) small. The shape mirrors
        ``compile_binding``: one binding for the role's non-layer capabilities,
        plus one binding per ``data.read``/``data.write`` row, each carrying
        that row's own ``layers`` (NULL meaning every layer).

        The expiry filter compares against the database's ``now()``, not the
        process clock. Rows are grouped by binding id, and each group's
        principal, scope, effect and expiry are read from the row itself -
        so a ``DENY`` row written outside this store is reproduced as one.
        An empty identifier set returns without querying.

        Args:
            identifiers: The caller's ``user:`` and ``group:`` identifiers.

        Returns:
            The compiled bindings of every unexpired grant to any of them;
            empty when there are none or ``identifiers`` is empty.
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
        """Return every binding row made at exactly this scope.

        ``IS NOT DISTINCT FROM`` lets the SYSTEM scope's NULL ``scope_id``
        match. The ordering uses ``COLLATE "C"`` so rows come back in byte
        order - the cluster's default collation folds case and treats a
        hyphen as insignificant - which makes the order identical to
        Python's ``sorted()`` on ``(principal, role_code)``, the comparison
        the bindings routes' keyset cursor assumes.

        Args:
            scope_type: The level to list.
            scope_id: The organization, project or dataset id, or None for
                SYSTEM scope.

        Returns:
            The bindings at that scope, expired ones included, in
            ``(principal, role_code)`` byte order.
        """
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
        return [binding_record(row) for row in rows]

    async def create_service_account(
        self, organization_id: UUID, *, name: str, subject: str, created_by: str
    ) -> ServiceAccount:
        """Insert the principal and its service-account row in one transaction.

        A ``service_accounts`` row must never exist without its
        ``principals`` row or vice versa, and only a transaction can promise
        that across a crash between the two inserts. The principal is
        created with kind ``service_account``, which is what the
        ``service_accounts_kind_guard`` trigger requires. ``name`` must
        already satisfy the table's slug CHECK; the repository validates it
        before calling.

        Args:
            organization_id: The organization that owns the account; must
                be a real ``organizations`` row.
            name: The account's name, unique within the organization.
            subject: The principal subject, unique across every principal.
            created_by: The subject of the actor creating the account.

        Returns:
            The new account, enabled, with a fresh principal id and the
            creation time both rows were stamped with.

        Raises:
            ResourceNotFound: If ``organization_id`` names no organization
                (the foreign key refused the row).
            ServiceAccountExists: If the organization already has an
                account with this ``name`` (the ``service_accounts``
                unique constraint refused the row).
            UsernameTaken: If some other principal - a password user, an
                OIDC login, or another organization's service account -
                already holds ``subject`` (the ``principals.subject``
                unique constraint refused the row).
            asyncpg.UniqueViolationError: If some other unique constraint
                refused the row - not expected against the current schema.
        """
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
            constraint = getattr(exc, "constraint_name", None)
            if constraint == _SERVICE_ACCOUNT_NAME_CONSTRAINT:
                raise ServiceAccountExists(f"service account already exists: {name}") from exc
            if constraint == _PRINCIPAL_SUBJECT_CONSTRAINT:
                raise UsernameTaken(f"a principal already exists for subject: {subject}") from exc
            raise
        return ServiceAccount(principal_id, organization_id, name, subject, created_by, created_at)

    async def get_service_account(self, principal_id: UUID) -> ServiceAccount:
        """Return one service account by principal id, disabled or not.

        ``subject`` and ``disabled_at`` live on the joined ``principals``
        row, which is why every service-account read is a join.

        Args:
            principal_id: The account's principal id.

        Returns:
            The stored account.

        Raises:
            ResourceNotFound: If no service account has this principal id.
        """
        row = await self._pool.fetchrow(
            """
            SELECT sa.principal_id, sa.organization_id, sa.name, p.subject,
                   sa.created_by, sa.created_at, p.disabled_at
            FROM service_accounts sa JOIN principals p ON p.id = sa.principal_id
            WHERE sa.principal_id = $1
            """,
            principal_id,
        )
        if row is None:
            raise ResourceNotFound(f"service account does not exist: {principal_id}")
        return service_account(row)

    async def service_account_by_subject(self, subject: str) -> ServiceAccount:
        """Return one service account by its principal subject, disabled or not.

        Args:
            subject: The principal subject the account authenticates as.

        Returns:
            The stored account.

        Raises:
            ResourceNotFound: If no service-account principal has this
                subject.
        """
        row = await self._pool.fetchrow(
            """
            SELECT sa.principal_id, sa.organization_id, sa.name, p.subject,
                   sa.created_by, sa.created_at, p.disabled_at
            FROM service_accounts sa JOIN principals p ON p.id = sa.principal_id
            WHERE p.subject = $1
            """,
            subject,
        )
        if row is None:
            raise ResourceNotFound(f"service account does not exist: {subject}")
        return service_account(row)

    async def list_service_accounts(self, organization_id: UUID) -> list[ServiceAccount]:
        """Return every service account an organization owns, disabled ones included.

        ``ORDER BY sa.name COLLATE "C"`` gives byte order, matching Python's
        ``sorted()`` on ``name`` - the key the service-account route's
        cursor compares by. Under the default collation a hyphen is
        ignorable, which would put ``a-count`` and ``ab-count`` in a
        different order than Python does.

        Args:
            organization_id: The owning organization.

        Returns:
            The organization's accounts in ``name`` byte order; empty when
            it owns none or does not exist.
        """
        rows = await self._pool.fetch(
            """
            SELECT sa.principal_id, sa.organization_id, sa.name, p.subject,
                   sa.created_by, sa.created_at, p.disabled_at
            FROM service_accounts sa JOIN principals p ON p.id = sa.principal_id
            WHERE sa.organization_id = $1
            ORDER BY sa.name COLLATE "C"
            """,
            organization_id,
        )
        return [service_account(row) for row in rows]

    async def disable_service_account(
        self, principal_id: UUID, *, disabled_at: datetime
    ) -> ServiceAccount:
        """Set ``disabled_at`` on the account's principal and return the account.

        The UPDATE is restricted to ``kind = 'service_account'`` and to a
        principal not already disabled, so a user's principal id is
        reported as no such service account rather than being disabled
        through the wrong door, and disabling an already-disabled account
        is a no-op that leaves its original timestamp untouched. The
        account is re-read through ``get_service_account`` either way, so
        the result reflects the row as it now stands - freshly disabled, or
        unchanged - and an id that names no service account raises
        ``ResourceNotFound`` there.

        Args:
            principal_id: The account's principal id.
            disabled_at: The moment to record as the disablement time, if
                the account is not already disabled.

        Returns:
            The account as stored after the call.
        """
        await self._pool.execute(
            """
            UPDATE principals
            SET disabled_at = $2
            WHERE id = $1 AND kind = 'service_account' AND disabled_at IS NULL
            """,
            principal_id,
            disabled_at,
        )
        return await self.get_service_account(principal_id)

    async def create_policy(
        self, *, policy_type: str, name: str, spec: dict[str, object], created_by: str
    ) -> Policy:
        """Insert one policy row, with ``spec`` serialised to ``jsonb``.

        Args:
            policy_type: The policy kind; must satisfy the column's
                identifier CHECK.
            name: A human-readable label; not required to be unique.
            spec: The policy's JSON-object body.
            created_by: The subject of the actor creating the policy.

        Returns:
            The policy as inserted, with a fresh id and creation time.

        Raises:
            ValueError: If ``policy_type`` fails the column's identifier
                CHECK - unreachable through the API, where
                ``schema/policies.py``'s field pattern already enforces the
                same shape before a request ever reaches this store.
        """
        record = Policy(
            id=uuid7(),
            policy_type=policy_type,
            name=name,
            spec=spec,
            created_by=created_by,
            created_at=datetime.now(UTC),
        )
        try:
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
        except asyncpg.exceptions.CheckViolationError as exc:
            raise ValueError(f"invalid policy_type: {policy_type!r}") from exc
        return record

    async def attach_policy(
        self, policy_id: UUID, *, scope_type: ScopeType, scope_id: UUID, attached_by: str
    ) -> PolicyAttachment:
        """Insert one ``policy_attachments`` row.

        The table's primary key is ``(policy_id, scope_type, scope_id)``, so
        the database is what makes an attachment unique per scope; its
        foreign key is what makes the policy's existence a precondition.

        Args:
            policy_id: The policy to attach.
            scope_type: The level the policy applies at; ORGANIZATION,
                PROJECT or DATASET.
            scope_id: The organization, project or dataset id.
            attached_by: The subject of the actor making the attachment.

        Returns:
            The attachment as inserted, stamped with the current time.

        Raises:
            ResourceNotFound: If ``policy_id`` names no policy (the foreign
                key refused the row).
            AttachmentExists: If the policy is already attached at exactly
                this scope (the primary key refused the row).
            ScopeNotBindable: If ``scope_type`` is SYSTEM (the column's
                CHECK allows only ORGANIZATION, PROJECT and DATASET) -
                unreachable through the API, where every route that attaches
                a policy passes a fixed, already-valid scope type.
        """
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
            raise AttachmentExists("policy is already attached at this scope") from exc
        except asyncpg.exceptions.CheckViolationError as exc:
            raise ScopeNotBindable(
                f"a policy cannot be attached at {scope_type.value} scope"
            ) from exc
        return PolicyAttachment(policy_id, scope_type.value, scope_id, attached_by, attached_at)

    async def list_policies(self) -> list[Policy]:
        """Return every policy row, ordered by ``(name, id)`` in byte order.

        ``COLLATE "C"`` on ``name`` overrides the cluster's default
        collation, which folds case and treats hyphens and accents as
        insignificant; byte order is exactly Python's ``str`` order, which
        is what the policies route's keyset cursor compares by. ``id``
        breaks ties because ``name`` carries no uniqueness constraint, and a
        uuid's byte order is its canonical string's order.

        Returns:
            All policies in ``(name, id)`` byte order.
        """
        rows = await self._pool.fetch(
            """
            SELECT id, policy_type, name, spec, created_by, created_at
            FROM policies
            ORDER BY name COLLATE "C", id
            """
        )
        return [policy(row) for row in rows]
