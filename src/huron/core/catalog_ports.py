"""Consumer-owned catalog reads and current authorization facts."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager
    from uuid import UUID

    from huron.pkg.catalog.models import RevisionRef
    from huron.pkg.catalog.persistence import IdempotencyClaim, PlatformRoot, Replay, Window
    from huron.pkg.catalog.records import Dataset, Organization, Project, Release, ServiceAccount
    from huron.pkg.rbac import Binding, ProjectVisibility, Visibility


class CollectionReader[ItemT, ParentT](Protocol):
    """Discoverable point reads and visible keyset windows of one fixed entity kind."""

    async def get(self, resource_id: UUID, visibility: Visibility) -> ItemT:
        """Read one admitted resource or raise ResourceNotFound.

        Args:
            resource_id: The exact resource to resolve.
            visibility: Discovery rights, applied before returning the record.

        Returns:
            The stored entity, preserving its concrete type.
        """
        ...

    async def browse(
        self,
        parent: ParentT,
        visibility: Visibility,
        *,
        limit: int,
        after: tuple[str, UUID] | None,
    ) -> Window[ItemT]:
        """Page visible children using C-collated slug and UUID ordering.

        The caller checks parent discovery. Filtering precedes limiting, and
        has_more counts only visible records; absent parents yield no rows.

        Args:
            parent: The owning resource, or the explicit platform root.
            visibility: The caller's discovery rights.
            limit: Maximum returned records.
            after: Exclusive slug and UUID cursor, or None for the first page.

        Returns:
            The visible window with an accurate further-row flag.
        """
        ...


class CatalogReaders(Protocol):
    """The fixed typed readers needed to resolve authoritative hierarchy ancestry."""

    @property
    def organizations(self) -> CollectionReader[Organization, PlatformRoot]:
        """Return the organization reader."""
        ...

    @property
    def projects(self) -> CollectionReader[Project, UUID]:
        """Return the project reader."""
        ...

    @property
    def datasets(self) -> CollectionReader[Dataset, UUID]:
        """Return the dataset reader."""
        ...


class HierarchyFacts(CatalogReaders, Protocol):
    """Internal classification and parent facts needed before discovery is decided."""

    async def project_visibilities(self) -> list[ProjectVisibility]:
        """Return every project's identity, organization and classification.

        Returns:
            Current project facts without a visibility filter.
        """
        ...

    async def dataset_parents(self, dataset_ids: frozenset[UUID]) -> dict[UUID, UUID]:
        """Resolve the parents of exactly the requested dataset grants.

        Args:
            dataset_ids: Dataset identifiers mentioned by current bindings.

        Returns:
            Existing dataset identifiers mapped to their owning projects.
        """
        ...


class BindingFacts(Protocol):
    """Current human grants and service-account authority used by authorization."""

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


class DescriptionWriter[ItemT](Protocol):
    """CAS persistence for one fixed hierarchy entity kind in the current transaction."""

    async def describe(self, item: ItemT, *, expected_version: int) -> None:
        """Stage descriptive fields only when the stored version matches.

        Args:
            item: The descriptive successor to persist.
            expected_version: Required current version; mismatch or absence
                raises PreconditionFailed and leaves the entity unchanged.
        """
        ...


class DescriptionTransaction(Protocol):
    """Typed description writers sharing one atomic transaction."""

    @property
    def organizations(self) -> DescriptionWriter[Organization]:
        """Return the organization's CAS writer."""
        ...

    @property
    def projects(self) -> DescriptionWriter[Project]:
        """Return the project's CAS writer."""
        ...

    @property
    def datasets(self) -> DescriptionWriter[Dataset]:
        """Return the dataset's CAS writer."""
        ...


class DescriptionStore(CatalogReaders, Protocol):
    """Committed ancestry readers and atomic description persistence."""

    def transaction(self) -> AbstractAsyncContextManager[DescriptionTransaction]:
        """Open a transaction whose writes commit only on successful exit.

        Returns:
            Writers sharing one acquired connection or staged memory transaction.
        """
        ...


class RetryTransaction(Protocol):
    """An atomic claim and replay receipt in the enclosing mutation transaction."""

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


class CreationTransaction(RetryTransaction, Protocol):
    """Identity inserts sharing the claimed creation transaction."""

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


class CreationStore(CatalogReaders, Protocol):
    """Committed ancestry and transaction-scoped identity creation."""

    def transaction(self) -> AbstractAsyncContextManager[CreationTransaction]:
        """Open one atomic identity creation and retry transaction.

        Returns:
            A context whose mutation and receipt commit only on clean exit.
        """
        ...


class ReleaseTransaction(RetryTransaction, Protocol):
    """A release insert sharing the claimed release-publication transaction."""

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


class ReleaseStore(CatalogReaders, Protocol):
    """Committed ancestry, release resolution and transaction-scoped tag publication."""

    def transaction(self) -> AbstractAsyncContextManager[ReleaseTransaction]:
        """Open one atomic release creation and retry transaction.

        Returns:
            A context whose insert and receipt commit only on clean exit.
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
