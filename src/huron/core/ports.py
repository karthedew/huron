"""Consumer-owned persistence contracts for Huron workflows.

Core coordinates catalog transactions, authorization and identity lifecycle through
HierarchyStore, HierarchyWriter, RbacStore and ApiKeyWriter. Adapters conform
structurally without importing core. CredentialStore, SessionStore and
PrincipalStore remain in auth alongside the credential operations that consume them.

Each method specifies guarantees shared by in-memory and PostgreSQL adapters.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from huron.pkg.auth import ApiKeyRecord, ApiKeyStore

if TYPE_CHECKING:
    from collections.abc import Sequence
    from contextlib import AbstractAsyncContextManager
    from datetime import datetime
    from uuid import UUID

    from huron.pkg.catalog.ingest import IngestFile, IngestSession
    from huron.pkg.catalog.models import OutboxEvent, RevisionRecord, RevisionRef
    from huron.pkg.catalog.persistence import IdempotencyClaim, LedgerEntry, Replay, Window
    from huron.pkg.catalog.records import (
        AuditEvent,
        Dataset,
        Organization,
        Policy,
        PolicyAttachment,
        Project,
        Release,
        RoleBindingRecord,
        ServiceAccount,
    )
    from huron.pkg.rbac import Binding, ProjectVisibility, ScopeType, Visibility


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
        its subject stay reserved. Disabling is idempotent: an
        already-disabled account keeps its original ``disabled_at``, and
        the given instant is discarded. An id that names no service account
        raises ``ResourceNotFound``.

        Args:
            principal_id: The account's principal id.
            disabled_at: The moment to record as the disablement time, if
                the account is not already disabled.

        Returns:
            The account with ``disabled_at`` set - to this call's instant on
            a first disable, or to the original instant if it was already
            disabled.
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
        """Revoke every still-active key a subject owns, regardless of ``owner_kind``.

        Called today when a service account is disabled, so its keys stop
        resolving with it. Keys already revoked keep their original
        ``revoked_at`` and are not counted.

        Args:
            subject: The owner whose keys are revoked.
            revoked_at: The moment to record on each key.

        Returns:
            How many keys this call revoked.
        """
        ...


class HierarchyWriter(Protocol):
    """One transaction's write surface; obtained from ``HierarchyStore.transaction()``.

    Every method runs inside the same transaction; nothing is visible to a
    reader until the ``async with`` block exits without an exception. No
    method here validates a slug, a tag, a classification code or an entry
    layer, and none writes a file: everything a write refuses, it refuses
    because the database refused it, and every other rule belongs to the
    caller assembling the item this writer is given.
    """

    async def claim(self, claim: IdempotencyClaim) -> Replay | None:
        """Stake this transaction's claim to a principal-scoped idempotency key.

        A key with no live claim for ``(claim.principal, claim.key)``, or
        one whose previous claim has expired, is silently taken over and
        this call returns ``None`` - the caller goes on to perform the
        write and later calls ``remember``. A live claim for the same
        pair with an identical ``request_sha256`` returns the ``Replay``
        already recorded for it, so the caller can skip the write and
        return the original resource instead. A live claim for the same
        pair with a different ``request_sha256`` raises
        ``IdempotencyKeyReused``, because the same key is being reused
        for a different request.

        Args:
            claim: The principal, key and request digest to stake.

        Returns:
            The replay already remembered for an identical live claim,
            or ``None`` when the claim is now this transaction's to
            fulfil.
        """
        ...

    async def remember(self, claim: IdempotencyClaim, replay: Replay) -> None:
        """Record what this transaction's write produced, for a later replay of the same claim.

        Called once, after the write ``claim`` authorized has succeeded
        and before the transaction commits. A claim that is never
        remembered - because the transaction raised before reaching this
        call - leaves no trace: a retry with the same principal, key and
        request digest finds no live claim and starts over.

        Args:
            claim: The claim staked earlier in this transaction by
                ``claim``.
            replay: What the write produced, to return on a future
                replay of the same claim.
        """
        ...

    async def insert_organization(self, item: Organization) -> None:
        """Insert one organization row.

        A second organization with the same ``item.slug`` raises
        ``SlugExists``; the database's own uniqueness key is what is
        enforced, not a precondition this method checks itself.

        Args:
            item: The organization to insert, fully formed.
        """
        ...

    async def insert_project(self, item: Project) -> None:
        """Insert one project row under its organization.

        A second project with the same ``item.slug`` under
        ``item.organization_id`` raises ``SlugExists``.

        Args:
            item: The project to insert, fully formed.
        """
        ...

    async def insert_dataset(self, item: Dataset, *, data_classification: str) -> None:
        """Insert one dataset row under its project.

        A second dataset with the same ``item.slug`` under
        ``item.project_id`` raises ``SlugExists``. ``data_classification``
        is stored beside the row but is not a field of ``Dataset`` itself;
        the caller has already resolved it from the owning project.

        Args:
            item: The dataset to insert, fully formed.
            data_classification: The classification code inherited from
                the owning project at creation time.
        """
        ...

    async def insert_release(self, item: Release) -> None:
        """Insert one release row, tagging a dataset revision.

        A second release with the same ``item.tag`` under
        ``item.dataset_id`` raises ``TagExists``. A release naming a
        revision that ``revision_ref`` cannot resolve for
        ``item.dataset_id`` raises ``ResourceNotFound``; a caller that
        resolved the revision through ``revision_ref`` first will not
        observe this.

        Args:
            item: The release to insert, fully formed.
        """
        ...

    async def update_organization(self, item: Organization, *, expected_version: int) -> None:
        """Apply an update to one organization, guarded by optimistic concurrency.

        The write lands only when the stored ``version`` equals
        ``expected_version``; it then advances to ``item.version``. Any
        other stored version - including the organization not
        existing - raises ``PreconditionFailed``.

        Args:
            item: The organization as it should read after the update.
            expected_version: The version the caller last read; the
                update is refused unless this still matches what is
                stored.
        """
        ...

    async def update_project(self, item: Project, *, expected_version: int) -> None:
        """Apply an update to one project, guarded by optimistic concurrency.

        The write lands only when the stored ``version`` equals
        ``expected_version``; it then advances to ``item.version``. Any
        other stored version - including the project not existing -
        raises ``PreconditionFailed``.

        Args:
            item: The project as it should read after the update.
            expected_version: The version the caller last read; the
                update is refused unless this still matches what is
                stored.
        """
        ...

    async def update_dataset(self, item: Dataset, *, expected_version: int) -> None:
        """Apply an update to one dataset, guarded by optimistic concurrency.

        The write lands only when the stored ``version`` equals
        ``expected_version``; it then advances to ``item.version``. Any
        other stored version - including the dataset not existing -
        raises ``PreconditionFailed``.

        Args:
            item: The dataset as it should read after the update.
            expected_version: The version the caller last read; the
                update is refused unless this still matches what is
                stored.
        """
        ...

    async def insert_revision(self, record: RevisionRecord) -> None:
        """Insert the row a COMMITTING session publishes when its commit lands.

        Identical content is allowed in distinct revision identities.

        Args:
            record: The revision to insert, fully formed.
        """
        ...

    async def insert_audit_event(self, event: AuditEvent) -> None:
        """Append one audit row.

        Args:
            event: The audit row to append, fully formed.
        """
        ...

    async def insert_outbox_event(self, event: OutboxEvent) -> None:
        """Append one outbox row, unprocessed.

        Args:
            event: The event to append, fully formed.
        """
        ...

    async def begin_ingest(
        self,
        dataset_id: UUID,
        manifest_sha256: str,
        *,
        created_by: str,
        files: Sequence[IngestFile],
    ) -> IngestSession:
        """Open an ingest session in ``PREPARING`` and reserve the revision it will commit as.

        The revision id and number are allocated here, before any byte is
        uploaded, so the final storage path is known from the start. The number
        is ``max(committed) + 1`` for the dataset, taken under the per-dataset
        ingest lock: exactly one non-terminal session may exist per dataset, and
        the number is held only while the session is open or committed. A session
        that ends ``ABORTED`` or ``FAILED`` never redeemed its reservation, so its
        number returns to the pool and the next session takes it again; the dead
        row stays as the record of the attempt. This is what keeps a dataset's
        numbering gap-free across retries. The manifest identity is recorded with
        the session so the commit can be checked against what was declared.
        Refuses with ``DatasetLocked`` while another session for the dataset is
        not yet terminal, whether or not its lease has lapsed.

        Args:
            dataset_id: The dataset the revision is being added to.
            manifest_sha256: The content identity of the declared manifest.
            created_by: The principal opening the session; the only one, besides a
                project admin aborting it, allowed to drive it.
            files: The upload plan's per-file ledger entries, in the order the
                manifest declares them, reserved alongside the session.

        Returns:
            The session in ``PREPARING`` with its lease: the reserved revision id
            and number, and when the lease lapses unless renewed.
        """
        ...

    async def update_ingest_session(self, session: IngestSession, *, expected_etag: int) -> None:
        """Persist one state edge, guarded by optimistic concurrency on the session's etag.

        The write lands only when the stored etag equals ``expected_etag``; it
        then advances to ``session.etag``. The store is agnostic to which edge
        this is - the domain's ``TRANSITIONS`` already decided that - so it
        persists whatever state and etag the caller hands it. Any other stored
        etag - including no session at all - raises ``PreconditionFailed``.

        Args:
            session: The session as it should read after the edge, with its
                etag already bumped by the domain operation that produced it.
            expected_etag: The etag the caller last read; the write is refused
                unless this still matches what is stored.
        """
        ...

    async def renew_ingest_session(self, session: IngestSession) -> None:
        """Move a session's lease forward, never backward, leaving its state and etag untouched.

        The stored ``expires_at`` becomes the later of itself and
        ``session.lease.expires_at``, so two concurrent renewals - or a renewal
        racing an older instant - are commutative and never move the lease
        backward. A session that does not exist, or is already terminal,
        raises ``IngestSessionExpired``.

        Args:
            session: The session carrying the candidate new lease; only its
                ``lease.ingest_id`` and ``lease.expires_at`` are consulted.
        """
        ...

    async def expire_ingest_session(
        self, session: IngestSession, *, expected_etag: int, now: datetime
    ) -> None:
        """Persist the sweep's ``expire`` edge, fenced on both the etag and the lease.

        Lands only when the stored etag equals ``expected_etag``, the stored
        state is still PREPARING, UPLOADING or VERIFYING, and the stored lease
        is still lapsed at ``now`` - so a session renewed or flipped after the
        sweep read it is left untouched rather than expired out from under
        whatever happened next. Failing any of those raises
        ``PreconditionFailed``.

        Args:
            session: The session as it should read after the edge, already
                advanced to ABORTED by the domain's ``expire`` operation.
            expected_etag: The etag the sweep last read; the write is refused
                unless this still matches what is stored.
            now: The instant the sweep is running at, re-checked against the
                stored lease so a renewal that landed after the read wins.
        """
        ...

    async def update_ingest_file(
        self, ingest_id: UUID, file: IngestFile, *, expected_parts: frozenset[int]
    ) -> None:
        """Persist one ledger step, fenced on the file still being PENDING with expected parts.

        Fencing on ``completed_parts`` rather than the session's etag is what
        lets parts of different files - and even different parts of the same
        file - land without serializing on a single counter; a write that
        raises never leaves the ledger short of an accepted byte, because the
        caller re-reads and re-applies the same step. No PENDING file
        matching ``file.file_id`` under ``ingest_id`` with exactly
        ``expected_parts`` recorded raises ``PreconditionFailed``.

        Args:
            ingest_id: The session the file's ledger row belongs to.
            file: The file as it should read after the step, already advanced
                by the domain operation that produced it.
            expected_parts: The parts the caller last read for this file; the
                write is refused unless the stored row still agrees.
        """
        ...


class HierarchyStore(Protocol):
    """The hierarchy's durable state and the ingest workflow that extends it.

    A point read raises ``ResourceNotFound`` both when the id names
    nothing and when it names something the caller's ``visibility`` does
    not admit - the two cases are indistinguishable to a caller with no
    grant on the resource, by design. A window is ordered by its level's
    cursor key, filtered by ``visibility`` before ``limit`` is applied, and
    ``after`` - when given - excludes the row it names, so a cursor walk
    never repeats or skips a row.
    """

    def transaction(self) -> AbstractAsyncContextManager[HierarchyWriter]:
        """Open one write transaction.

        Every write the returned ``HierarchyWriter`` performs is invisible
        to every read on this store until the ``async with`` block exits
        without raising; an exception inside the block discards every
        write made through it.

        Returns:
            An async context manager yielding the transaction's writer.
        """
        ...

    async def organization(self, organization_id: UUID, visibility: Visibility) -> Organization:
        """Return one organization, if ``visibility`` admits it.

        Args:
            organization_id: The organization to read.
            visibility: The caller's discovery rights.

        Returns:
            The stored organization.
        """
        ...

    async def project(self, project_id: UUID, visibility: Visibility) -> Project:
        """Return one project, if ``visibility`` admits it.

        Args:
            project_id: The project to read.
            visibility: The caller's discovery rights.

        Returns:
            The stored project.
        """
        ...

    async def dataset(self, dataset_id: UUID, visibility: Visibility) -> Dataset:
        """Return one dataset, if ``visibility`` admits it.

        Args:
            dataset_id: The dataset to read.
            visibility: The caller's discovery rights.

        Returns:
            The stored dataset.
        """
        ...

    async def release(self, dataset_id: UUID, tag: str, visibility: Visibility) -> Release:
        """Return one release by its dataset and tag, if ``visibility`` admits the dataset.

        Args:
            dataset_id: The dataset the release belongs to.
            tag: The release's tag, unique within the dataset.
            visibility: The caller's discovery rights.

        Returns:
            The stored release.
        """
        ...

    async def revision_ref(self, dataset_id: UUID, revision_number: int) -> RevisionRef:
        """Return the identity of one committed revision by its dataset and sequential number.

        Unlike the other point reads, this one carries no ``visibility``:
        a revision is resolved only in service of a release the caller has
        already been authorized to create on ``dataset_id``.

        Args:
            dataset_id: The dataset the revision belongs to.
            revision_number: The revision's 1-based position within the
                dataset.

        Returns:
            The revision's identity and manifest digest.
        """
        ...

    async def organizations(
        self, visibility: Visibility, *, limit: int, after: tuple[str, UUID] | None
    ) -> Window[Organization]:
        """Return a window of organizations ordered by ``(slug, id)``.

        Args:
            visibility: The caller's discovery rights; only admitted
                organizations are counted toward ``limit``.
            limit: The maximum number of organizations to return.
            after: The ``(slug, id)`` of the last organization already
                seen, excluded from the window, or ``None`` to start from
                the beginning.

        Returns:
            The next window of admitted organizations.
        """
        ...

    async def projects(
        self,
        organization_id: UUID,
        visibility: Visibility,
        *,
        limit: int,
        after: tuple[str, UUID] | None,
    ) -> Window[Project]:
        """Return a window of one organization's projects ordered by ``(slug, id)``.

        Args:
            organization_id: The owning organization.
            visibility: The caller's discovery rights; only admitted
                projects are counted toward ``limit``.
            limit: The maximum number of projects to return.
            after: The ``(slug, id)`` of the last project already seen,
                excluded from the window, or ``None`` to start from the
                beginning.

        Returns:
            The next window of admitted projects.
        """
        ...

    async def datasets(
        self,
        project_id: UUID,
        visibility: Visibility,
        *,
        limit: int,
        after: tuple[str, UUID] | None,
    ) -> Window[Dataset]:
        """Return a window of one project's datasets ordered by ``(slug, id)``.

        Args:
            project_id: The owning project.
            visibility: The caller's discovery rights; only admitted
                datasets are counted toward ``limit``.
            limit: The maximum number of datasets to return.
            after: The ``(slug, id)`` of the last dataset already seen,
                excluded from the window, or ``None`` to start from the
                beginning.

        Returns:
            The next window of admitted datasets.
        """
        ...

    async def releases(
        self, dataset_id: UUID, visibility: Visibility, *, limit: int, after: tuple[str] | None
    ) -> Window[Release]:
        """Return a window of one dataset's releases ordered by ``tag``.

        Args:
            dataset_id: The dataset the releases belong to.
            visibility: The caller's discovery rights, checked against the
                dataset itself; every release of an admitted dataset is
                returned.
            limit: The maximum number of releases to return.
            after: The tag of the last release already seen, excluded
                from the window, or ``None`` to start from the beginning.

        Returns:
            The next window of the dataset's releases.
        """
        ...

    async def project_visibilities(self) -> list[ProjectVisibility]:
        """Return every project's identity, owning organization and classification.

        This is the input a caller reduces bindings against to compute a
        principal's ``Visibility``; the store applies no filtering of its
        own here.

        Returns:
            Every project, in no particular order.
        """
        ...

    async def dataset_parents(self, dataset_ids: frozenset[UUID]) -> dict[UUID, UUID]:
        """Return each requested dataset's owning project id.

        This is the second input a caller needs to compute
        ``Visibility.dataset_ids``: which project's classification and
        bindings a dataset-scope grant is evaluated against.

        Args:
            dataset_ids: The datasets to resolve.

        Returns:
            A mapping from dataset id to project id, holding an entry for
            every id in ``dataset_ids`` that exists; an id that names no
            dataset is simply absent, not an error.
        """
        ...

    async def revision(self, revision_id: UUID) -> RevisionRecord:
        """Return one revision row in any state.

        Unlike the other point reads, this one carries no ``visibility``:
        a revision is read only in service of an operation the caller has
        already been authorized to perform.

        Args:
            revision_id: The revision to read.

        Returns:
            The stored revision.
        """
        ...

    async def latest_committed_revision(self, dataset_id: UUID) -> RevisionRecord | None:
        """Return the dataset's highest-numbered committed revision.

        Distinct revisions may contain identical manifests.

        Args:
            dataset_id: The dataset to read.

        Returns:
            The dataset's highest-numbered revision in state COMMITTED, or
            None if it has never committed one.
        """
        ...

    async def ingest_session(self, session_id: UUID) -> IngestSession:
        """Return one session by id, in whatever state it currently holds.

        An id that names no session raises ``ResourceNotFound``.

        Args:
            session_id: The session to read.

        Returns:
            The stored session.
        """
        ...

    async def ingest_files(self, session_id: UUID) -> tuple[IngestFile, ...]:
        """Return a session's ledger, one entry per planned file, in manifest order.

        Args:
            session_id: The session whose ledger to read.

        Returns:
            The session's files ordered by path; empty if the session names
            no files or does not exist.
        """
        ...

    async def ingest_file(self, file_id: UUID) -> LedgerEntry:
        """Return one ledger entry together with the id of the session it belongs to.

        An id that names no file raises ``ResourceNotFound``.

        Args:
            file_id: The file to read.

        Returns:
            The file's current ledger state and the id of its session.
        """
        ...

    async def lapsed_ingest_sessions(
        self, now: datetime, *, limit: int
    ) -> tuple[IngestSession, ...]:
        """Return the oldest lapsed, still-open sessions, for the expiry sweep to reap.

        Never returns a COMMITTING session: once a commit has begun, storage
        leads and only the driver that started it may finish or fail it.

        Args:
            now: The instant a session's lease is judged lapsed against.
            limit: The maximum number of sessions to return.

        Returns:
            Up to ``limit`` sessions in PREPARING, UPLOADING or VERIFYING
            whose lease has lapsed at or before ``now``, oldest lease first.
        """
        ...
