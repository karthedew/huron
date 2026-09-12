"""Internal release publication and governance coordination.

Release publication claims its retry identity, inserts the pinned tag, writes
its durable document off the event loop, and records the receipt before database
commit. Governance operations validate their scope and delegate to RBAC storage.
Catalog identity creation and descriptive updates have their own authorized
workflow modules and use the hierarchy adapter directly.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from asyncer import asyncify

from huron.pkg.catalog.errors import (
    TagExists,
)
from huron.pkg.catalog.ids import uuid7
from huron.pkg.catalog.manifest import canonical_bytes
from huron.pkg.catalog.paths import (
    release_tag_file,
    validate_slug,
    validate_tag,
)
from huron.pkg.catalog.persistence import Replay
from huron.pkg.catalog.records import (
    Policy,
    PolicyAttachment,
    Release,
    RoleBindingRecord,
    ServiceAccount,
    jsonable,
)
from huron.pkg.rbac import ScopeType, Visibility

from .catalog_claims import claimed_result

if TYPE_CHECKING:
    from uuid import UUID

    from huron.pkg.catalog.ports import RawStore

    from .ports import HierarchyStore, RbacStore
from huron.pkg.catalog.persistence import IdempotencyClaim, Window


class HierarchyRepository:
    """Remaining release and governance operations plus Raw storage initialization.

    Release rows and retry claims share the hierarchy transaction; roles,
    service accounts and policies use the injected RBAC adapter. Release reads
    enforce the supplied discovery context, while governance scope validation
    uses committed hierarchy readers. Actor-bound workflows enforce authority
    before invoking these internal operations.

    Attributes:
        raw_store: Initialized storage for durable documents.
        hierarchy: The committed hierarchy and transaction adapter.
        rbac: Role, policy and service-account persistence.
    """

    def __init__(
        self,
        raw_store: RawStore,
        hierarchy: HierarchyStore,
        *,
        rbac_store: RbacStore,
    ):
        """Wire the repository over its raw store, hierarchy store and RBAC storage port.

        Construction initializes the raw store's directory layout, so the
        data root must be writable and its staging and ``organization``
        directories must sit on one filesystem.

        Args:
            raw_store: The store that holds every durable generation
                and release-tag document; it is initialized here.
            hierarchy: Durable storage for the organization/project/dataset/
                release hierarchy and its idempotency claims.
            rbac_store: Storage for role bindings, service accounts and
                policies.
        """
        self.raw_store = raw_store
        self.raw_store.initialize()
        self.hierarchy = hierarchy
        self.rbac = rbac_store

    @property
    def data_root(self) -> PurePosixPath:
        """Return the raw store's root in the form the layout functions take.

        Every ``organization/...`` directory and release-tag file is derived
        from this root by :mod:`huron.pkg.catalog.paths`.

        Returns:
            The raw store's root directory as a ``PurePosixPath``.
        """
        return PurePosixPath(self.raw_store.root)

    async def create_release(
        self,
        dataset_id: UUID,
        visibility: Visibility,
        *,
        tag: str,
        revision_number: int,
        title: str | None,
        created_by: str,
        claim: IdempotencyClaim,
    ) -> Release:
        """Pin a release tag to a registered revision of a dataset.

        ``tag`` must satisfy the tag rules (``validate_tag`` raises
        ``PathRuleViolation`` otherwise) and is unique within the dataset for
        all time: the release is stored as a write-once file under the
        dataset's ``releases/`` directory, so a tag is refused both when the
        store already holds it and when the file already exists on disk.
        The dataset is read with ``visibility``, so an invisible or absent
        dataset is ``ResourceNotFound``; its project and organization are
        then read with unrestricted visibility purely to build the storage
        path, and the revision is resolved by ``revision_number`` - an
        unregistered number is ``ResourceNotFound``. Creation is idempotent
        per ``claim``: staking an identical claim returns the original
        release without writing, and staking one whose key was used for a
        different request is refused with ``IdempotencyKeyReused``. The tag
        file is written after the row is inserted and before the
        transaction commits.

        Args:
            dataset_id: The dataset the tag belongs to.
            visibility: The caller's discovery rights, used to resolve
                ``dataset_id``.
            tag: The release tag; 2 to 63 characters of lowercase letters,
                digits, dots, underscores and hyphens.
            revision_number: The number of a revision already registered for
                the dataset.
            title: An optional human-readable name for the release.
            created_by: The subject of the principal creating the release.
            claim: The caller's idempotency claim for this request.

        Returns:
            The stored release, pinned to the revision's id and number.

        Raises:
            TagExists: If the dataset already has a release with ``tag``,
                in the store or on disk.
        """
        validate_tag(tag)
        async with self.hierarchy.transaction() as writer:
            dataset = await self.hierarchy.datasets.get(dataset_id, visibility)
            project = await self.hierarchy.projects.get(dataset.project_id, Visibility.ALL)
            organization = await self.hierarchy.organizations.get(
                project.organization_id, Visibility.ALL
            )
            revision = await self.hierarchy.revision_ref(dataset_id, revision_number)
            replayed = await claimed_result(
                writer, claim, lambda _: self.release(dataset_id, tag, Visibility.ALL)
            )
            if replayed is not None:
                return replayed
            item = Release(
                uuid7(),
                dataset_id,
                tag,
                revision.id,
                revision.number,
                title,
                created_by,
                datetime.now(UTC),
            )
            await writer.insert_release(item)
            payload = canonical_bytes(jsonable(item))
            tag_path = release_tag_file(self.data_root, organization, project, dataset, tag)
            try:
                await asyncify(self.raw_store.write_tag_once)(tag_path, payload)
            except FileExistsError as exc:
                raise TagExists(f"release tag already exists: {tag}") from exc
            await writer.remember(claim, Replay(kind="release", resource_id=item.id))
            return item

    async def release(self, dataset_id: UUID, tag: str, visibility: Visibility) -> Release:
        """Return the release a dataset publishes under a tag, if ``visibility`` admits the dataset.

        Args:
            dataset_id: The dataset the tag belongs to.
            tag: The release tag to resolve.
            visibility: The caller's discovery rights.

        Returns:
            The release created under that tag. The store raises
            ``ResourceNotFound`` when the dataset has no release with
            ``tag``, or ``visibility`` does not admit the dataset.
        """
        return await self.hierarchy.release(dataset_id, tag, visibility)

    async def releases(
        self, dataset_id: UUID, visibility: Visibility, *, limit: int, after: tuple[str] | None
    ) -> Window[Release]:
        """Return a window of one dataset's releases ordered by ``tag``.

        The dataset is read with ``visibility`` first, so an invisible or
        absent dataset is ``ResourceNotFound`` rather than an empty window.

        Args:
            dataset_id: The dataset whose releases to list.
            visibility: The caller's discovery rights, checked against the
                dataset itself.
            limit: The maximum number of releases to return.
            after: The tag of the last release already seen, excluded from
                the window, or ``None`` to start from the beginning.

        Returns:
            The next window of the dataset's releases.
        """
        await self.hierarchy.datasets.get(dataset_id, visibility)
        return await self.hierarchy.releases(dataset_id, visibility, limit=limit, after=after)

    # -- RBAC ------------------------------------------------------------
    # Every method below delegates to ``self.rbac``; the only logic
    # kept here is what depends on the hierarchy the RBAC store deliberately
    # knows nothing about (existence checks, and the service-account
    # subject derived from the org slug).

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
        """Grant a role to a principal at a scope that is known to exist.

        The scope pair is checked first: ``_require_scope`` raises
        ``ValueError`` for an inconsistent pair (a caller bug) and
        ``ResourceNotFound`` when the organization, project or dataset does
        not exist, so a binding can never point at nothing. Everything else
        is the store's: it validates the grant against the role model
        (``compile_binding`` raises a ``RoleError`` for an unknown role, a
        principal kind the role does not admit, or a scope level the role
        cannot bind at) and refuses an identical existing binding with
        ``BindingExists``.

        Args:
            principal: The ``kind:subject`` identifier the role is granted
                to: ``user:...``, ``group:...`` or ``sa:...``.
            role_code: A role code from :mod:`huron.pkg.rbac.roles`.
            scope_type: The level the role applies at.
            scope_id: The organization, project or dataset id, or ``None``
                for ``SYSTEM`` scope.
            created_by: The subject of the principal making the grant.
            expires_at: When the grant lapses, or ``None`` for no expiry.

        Returns:
            The stored binding, with its generated id and timestamp.
        """
        await self._require_scope(scope_type, scope_id)
        return await self.rbac.grant_role(
            principal=principal,
            role_code=role_code,
            scope_type=scope_type,
            scope_id=scope_id,
            created_by=created_by,
            expires_at=expires_at,
        )

    async def revoke_role(self, binding_id: UUID) -> RoleBindingRecord:
        """Delete one role binding and return what was removed.

        The store raises ``ResourceNotFound`` when no such binding exists, so
        revoking twice is refused rather than silently succeeding.

        Args:
            binding_id: The binding's id.

        Returns:
            The binding as it was before removal.
        """
        return await self.rbac.revoke_role(binding_id)

    async def get_role_binding(self, binding_id: UUID) -> RoleBindingRecord:
        """Return one role binding by id.

        The store raises ``ResourceNotFound`` when no such binding exists.

        Args:
            binding_id: The binding's id.

        Returns:
            The stored binding.
        """
        return await self.rbac.get_role_binding(binding_id)

    async def bindings_at(
        self, scope_type: ScopeType, scope_id: UUID | None
    ) -> list[RoleBindingRecord]:
        """Return the role bindings granted at exactly one scope.

        Only bindings stored at this scope are returned; inheritance from
        enclosing scopes is ``decide()``'s concern, not a listing's. The
        scope's existence is checked first, through ``_require_scope``, so
        an unknown ``scope_id`` is ``ResourceNotFound`` rather than an
        empty list.

        Args:
            scope_type: The level to list.
            scope_id: The organization, project or dataset id, or ``None``
                for ``SYSTEM`` scope.

        Returns:
            The bindings at that scope, ordered by ``(principal, role_code)``.
        """
        await self._require_scope(scope_type, scope_id)
        return await self.rbac.bindings_at(scope_type, scope_id)

    async def create_service_account(
        self, organization_id: UUID, *, name: str, created_by: str
    ) -> ServiceAccount:
        """Create a service account whose subject derives from the organization slug.

        ``name`` is validated as a slug with the organization/project length
        limit (``validate_slug`` raises ``PathRuleViolation`` otherwise) and
        the organization must exist, read with unrestricted visibility since
        this is RBAC provisioning rather than a discovery decision - the
        granting principal's own visibility is already checked by the
        ``require_*`` guard before the handler runs. The account's subject
        is ``{organization slug}/{name}``: that is what its API keys
        authenticate as, and it is stable for the account's lifetime because
        organization slugs are immutable. The store refuses a second account
        with the same name in the same organization with
        ``ServiceAccountExists``.

        Args:
            organization_id: The owning organization.
            name: The account's name, unique within the organization; 2 to
                62 characters of lowercase letters, digits and hyphens, with
                no doubled hyphen.
            created_by: The subject of the principal creating the account.

        Returns:
            The stored account, with its generated principal id and subject.
            ``organization_id`` not naming an organization surfaces here as
            the ``ResourceNotFound`` the read raises.
        """
        validate_slug(name, 62)
        organization = await self.hierarchy.organizations.get(organization_id, Visibility.ALL)
        subject = f"{organization.slug}/{name}"
        return await self.rbac.create_service_account(
            organization_id, name=name, subject=subject, created_by=created_by
        )

    async def get_service_account(self, principal_id: UUID) -> ServiceAccount:
        """Return one service account by its principal id.

        The store raises ``ResourceNotFound`` when no such account exists.

        Args:
            principal_id: The account's principal id.

        Returns:
            The stored account, disabled or not.
        """
        return await self.rbac.get_service_account(principal_id)

    async def list_service_accounts(self, organization_id: UUID) -> list[ServiceAccount]:
        """Return every service account of one organization, ordered by name.

        The organization's existence is checked first, through
        ``_require_scope``, so an unknown organization is
        ``ResourceNotFound`` rather than an empty list.

        Args:
            organization_id: The organization whose accounts to list.

        Returns:
            The organization's accounts, sorted by name.
        """
        await self._require_scope(ScopeType.ORGANIZATION, organization_id)
        return await self.rbac.list_service_accounts(organization_id)

    async def disable_service_account(
        self, principal_id: UUID, *, disabled_at: datetime
    ) -> ServiceAccount:
        """Mark a service account disabled as of a moment.

        Disabling is recorded, not deleted: the account stays resolvable by
        id and by subject with ``disabled_at`` set, and a disabled account
        resolves to no bindings. Disabling is idempotent: an
        already-disabled account keeps its original ``disabled_at`` and
        ``disabled_at`` is discarded. Revoking the account's existing API
        keys is the caller's job, not this method's. The store raises
        ``ResourceNotFound`` when no such account exists.

        Args:
            principal_id: The account's principal id.
            disabled_at: The instant recorded as the disabling time, if the
                account is not already disabled.

        Returns:
            The account with ``disabled_at`` set - to this call's instant on
            a first disable, or to the original instant if it was already
            disabled.
        """
        return await self.rbac.disable_service_account(principal_id, disabled_at=disabled_at)

    async def create_policy(
        self, *, policy_type: str, name: str, spec: dict[str, object], created_by: str
    ) -> Policy:
        """Store a policy definition.

        Nothing here inspects ``spec`` or checks ``name`` for uniqueness - a
        policy is identified by the id the store generates, and several
        policies may share a name.

        Args:
            policy_type: The kind of policy ``spec`` describes.
            name: A human-readable label; not required to be unique.
            spec: The policy body, stored as given.
            created_by: The subject of the principal creating the policy.

        Returns:
            The stored policy, with its generated id and timestamp.
        """
        return await self.rbac.create_policy(
            policy_type=policy_type, name=name, spec=spec, created_by=created_by
        )

    async def attach_policy(
        self, policy_id: UUID, *, scope_type: ScopeType, scope_id: UUID, attached_by: str
    ) -> PolicyAttachment:
        """Attach a policy at a scope that is known to exist.

        The scope pair is checked first: ``_require_scope`` raises
        ``ValueError`` for an inconsistent pair and ``ResourceNotFound`` when
        the organization, project or dataset does not exist. ``scope_id`` is
        required, so a policy cannot be attached at ``SYSTEM`` scope. The
        store raises ``ResourceNotFound`` when the policy does not exist and
        ``AttachmentExists`` when it is already attached at that scope.

        Args:
            policy_id: The policy to attach.
            scope_type: The level the policy applies at; never ``SYSTEM``.
            scope_id: The organization, project or dataset id.
            attached_by: The subject of the principal attaching the policy.

        Returns:
            The stored attachment, with its timestamp.
        """
        await self._require_scope(scope_type, scope_id)
        return await self.rbac.attach_policy(
            policy_id, scope_type=scope_type, scope_id=scope_id, attached_by=attached_by
        )

    async def list_policies(self) -> list[Policy]:
        """Return every policy, ordered by ``(name, id)``.

        The order is the key the listing route pages by; ``id`` breaks ties
        because names are not unique.

        Returns:
            All policies, sorted by name and then id.
        """
        return await self.rbac.list_policies()

    async def _require_scope(self, scope_type: ScopeType, scope_id: UUID | None) -> None:
        """Reject an internally inconsistent scope/id pair.

        No request can produce one of these - each binding route passes
        the pair its own path supplies, and the SYSTEM route passes ``None``
        literally - so this is a caller bug, not a client contract, and its
        honest answer is the 500 the unhandled-exception path produces.

        A consistent pair is then checked for existence, with unrestricted
        visibility: the organization, project or dataset ``scope_id`` names
        must be known, and the matching read raises ``ResourceNotFound``
        when it is not. That one is a client contract - a grant or
        attachment cannot point at nothing - and it is independent of the
        granting principal's own visibility, which the ``require_*`` guard
        already checked before the handler ran. ``SYSTEM`` scope has
        nothing to look up.

        Args:
            scope_type: The level a grant or attachment applies at.
            scope_id: The organization, project or dataset id, or ``None``
                for ``SYSTEM`` scope.

        Raises:
            ValueError: If ``SYSTEM`` comes with an id, or any other level
                comes without one.
        """
        if scope_type is ScopeType.SYSTEM:
            if scope_id is not None:
                raise ValueError("SYSTEM scope takes no scope_id")
            return
        if scope_id is None:
            raise ValueError(f"{scope_type.value} scope requires a scope_id")
        if scope_type is ScopeType.ORGANIZATION:
            await self.hierarchy.organizations.get(scope_id, Visibility.ALL)
        elif scope_type is ScopeType.PROJECT:
            await self.hierarchy.projects.get(scope_id, Visibility.ALL)
        else:
            await self.hierarchy.datasets.get(scope_id, Visibility.ALL)
