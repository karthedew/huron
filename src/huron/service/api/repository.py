"""Hierarchy application service used by the HTTP composition root.

The production structural adapter is PostgreSQL; this small repository keeps
the use-case sequencing independently testable. Filesystem generation/release
documents are always written before the result is made visible through this
repository.

The module holds :class:`HierarchyRepository` - the service tier's facade over
the organization/project/dataset/release/revision hierarchy, which it keeps in
process memory, and over the injected RBAC, API-key, credential, session and
principal stores - together with the private helpers behind idempotency-key
replay: request fingerprinting and the replay/remember pair every creation
method runs under the repository lock.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import PurePosixPath
from threading import RLock
from uuid import UUID

from huron.pkg.auth import (
    CredentialStore,
    MemoryApiKeyStore,
    MemoryCredentialStore,
    MemoryPrincipalStore,
    MemorySessionStore,
    PrincipalStore,
    SessionStore,
)
from huron.pkg.catalog.errors import (
    ClassificationUnknown,
    IdempotencyKeyReused,
    PreconditionFailed,
    ResourceNotFound,
    SlugImmutable,
    TagExists,
)
from huron.pkg.catalog.ids import uuid7
from huron.pkg.catalog.layers import Layer, parse_entry_layer
from huron.pkg.catalog.lifecycle import DatasetLifecycle
from huron.pkg.catalog.manifest import canonical_bytes
from huron.pkg.catalog.paths import (
    dataset_dir,
    organization_dir,
    project_dir,
    release_tag_file,
    validate_org_slug,
    validate_slug,
    validate_tag,
)
from huron.pkg.rawstore import PosixRawStore
from huron.pkg.rbac import Binding, ScopeType

from .errors import SlugExists
from .records import (
    Dataset,
    Organization,
    Policy,
    PolicyAttachment,
    Project,
    Release,
    RevisionSeed,
    RoleBindingRecord,
    ServiceAccount,
    jsonable,
)
from .stores import ApiKeyWriter, InMemoryRbacStore, RbacStore


class HierarchyRepository:
    """The service tier's facade over the catalog hierarchy and its stores.

    One instance is wired per application, and every route reaches the
    hierarchy - organizations, projects, datasets, revisions and releases -
    through it. The hierarchy itself is held in process memory and does not
    survive a restart; role bindings, service accounts, policies, API keys,
    credentials, sessions and principals live in the injected stores, and
    the raw store holds the durable generation and release-tag documents.

    Invariants every method keeps:

    - A created record becomes visible only after its durable document is on
      disk: the generation file (or release-tag file) is written first, then
      the in-memory map is updated.
    - A slug is immutable once created, because it is baked into the storage
      path; no role can change it, and the patch methods refuse a different
      slug before the version precondition is even compared.
    - Every mutation, and every idempotency-key lookup, runs under one
      re-entrant lock, so a replayed request never observes a half-applied
      one.
    - Creation is idempotent per ``idempotency_key``: replaying a key with the
      same request returns the original record without writing again, and
      reusing it for a different request is refused. Keys are global to the
      repository, not per resource kind.

    Attributes:
        raw_store: The POSIX raw store holding the durable documents.
        organizations: Every organization, by id.
        projects: Every project, by id.
        datasets: Every dataset, by id.
        revisions: The registered revision seeds, by ``(dataset_id, number)``.
        releases: Every release, by ``(dataset_id, tag)``.
        api_keys: The API-key store the routes and the credential resolver
            share.
        credentials: The password-credential store.
        sessions: The server-side browser-session store.
        principals: The store of user and service-account identities.
    """

    def __init__(
        self,
        raw_store: PosixRawStore,
        *,
        classification_vocabulary: tuple[str, ...],
        rbac_store: RbacStore | None = None,
        api_key_store: ApiKeyWriter | None = None,
        credential_store: CredentialStore | None = None,
        session_store: SessionStore | None = None,
        principal_store: PrincipalStore | None = None,
    ):
        """Wire the repository over a raw store and the tier's storage ports.

        Construction initializes the raw store's directory layout, so the
        data root must be writable and its staging and ``organization``
        directories must sit on one filesystem. Each repository gets its own
        fresh in-memory store for every port that is not injected: a shared
        default instance would leak role bindings and API keys across every
        test and every repository built without one, so the defaults are
        created per instance, never at import time.

        Args:
            raw_store: The POSIX store that holds every durable generation
                and release-tag document; it is initialized here.
            classification_vocabulary: The data-classification codes a
                project may declare; ``create_project`` refuses any other.
            rbac_store: Storage for role bindings, service accounts and
                policies; a fresh ``InMemoryRbacStore`` when omitted.
            api_key_store: Storage for API keys; a fresh ``MemoryApiKeyStore``
                when omitted.
            credential_store: Storage for password credentials; a fresh
                ``MemoryCredentialStore`` when omitted.
            session_store: Storage for browser sessions; a fresh
                ``MemorySessionStore`` when omitted.
            principal_store: Storage for principals; a fresh
                ``MemoryPrincipalStore`` when omitted.
        """
        self.raw_store = raw_store
        self.raw_store.initialize()
        self._classification_vocabulary = frozenset(classification_vocabulary)
        self.organizations: dict[UUID, Organization] = {}
        self.projects: dict[UUID, Project] = {}
        self.datasets: dict[UUID, Dataset] = {}
        self.revisions: dict[tuple[UUID, int], RevisionSeed] = {}
        self.releases: dict[tuple[UUID, str], Release] = {}
        # Each repository gets its own fresh in-memory store when one isn't
        # injected - a shared default instance would leak role bindings and
        # API keys across every test and every HierarchyRepository built
        # without one.
        self._rbac_store: RbacStore = rbac_store if rbac_store is not None else InMemoryRbacStore()
        self.api_keys: ApiKeyWriter = (
            api_key_store if api_key_store is not None else MemoryApiKeyStore()
        )
        self.credentials: CredentialStore = (
            credential_store if credential_store is not None else MemoryCredentialStore()
        )
        self.sessions: SessionStore = (
            session_store if session_store is not None else MemorySessionStore()
        )
        self.principals: PrincipalStore = (
            principal_store if principal_store is not None else MemoryPrincipalStore()
        )
        self._idempotency: dict[str, tuple[str, object]] = {}
        self._lock = RLock()

    @property
    def data_root(self) -> PurePosixPath:
        """Return the raw store's root in the form the layout functions take.

        Every ``organization/...`` directory and release-tag file is derived
        from this root by :mod:`huron.pkg.catalog.paths`.

        Returns:
            The raw store's root directory as a ``PurePosixPath``.
        """
        return PurePosixPath(self.raw_store.root)

    def create_organization(
        self,
        *,
        slug: str,
        title: str,
        description: str,
        idempotency_key: str,
    ) -> Organization:
        """Create an organization and write its first generation document.

        The slug must satisfy the organization slug rules and must not be a
        reserved root slug (``validate_org_slug`` raises ``PathRuleViolation``
        otherwise); it is immutable afterwards because it names the
        organization's storage directory. Creation is idempotent per
        ``idempotency_key``: the request is fingerprinted over the slug,
        title and description, replaying the key with the same fingerprint
        returns the organization created the first time without touching
        storage, and replaying it with a different fingerprint is refused
        with ``IdempotencyKeyReused``. The key is remembered only once the
        organization exists, so a refused attempt may be retried under the
        same key. Generation ``1`` is written to the raw store before the
        record becomes visible.

        Args:
            slug: The URL and path segment identifying the organization; 2 to
                62 characters of lowercase letters, digits and hyphens, with
                no doubled hyphen (the slug/id separator in path components),
                and not one of the reserved root slugs.
            title: The human-readable name.
            description: Free-text description; may be empty.
            idempotency_key: The caller's ``Idempotency-Key``, scoping replay.

        Returns:
            The stored organization, at generation and version ``1``.

        Raises:
            SlugExists: If another organization already uses ``slug``.
        """
        validate_org_slug(slug)
        fingerprint = _fingerprint("organization", slug, title, description)
        with self._lock:
            replay = self._replay(idempotency_key, fingerprint)
            if replay is not None:
                return _expect_type(replay, Organization)
            if any(item.slug == slug for item in self.organizations.values()):
                raise SlugExists(f"organization slug already exists: {slug}")
            item = Organization(uuid7(), slug, title, description, 1, 1, datetime.now(UTC))
            self._write_generation(organization_dir(self.data_root, item), item)
            self.organizations[item.id] = item
            self._remember(idempotency_key, fingerprint, item)
            return item

    def create_project(
        self,
        organization_id: UUID,
        *,
        slug: str,
        title: str,
        description: str,
        data_classification: str,
        idempotency_key: str,
    ) -> Project:
        """Create a project under an organization and write its first generation.

        ``data_classification`` must be one of the codes in the
        classification vocabulary the repository was built with; that check
        runs before the replay lookup, so an unknown classification is
        refused even on a replay. The slug is validated by ``validate_slug``
        (which raises ``PathRuleViolation``) and is immutable afterwards
        because it names the project's storage directory; it must be unique
        within the organization only, so two organizations may each have a
        project with the same slug. The organization must exist
        (``get_organization`` raises ``ResourceNotFound``). Creation is
        idempotent per ``idempotency_key``: the fingerprint covers the
        organization, slug, title and description - not the classification -
        so replaying the key with the same fingerprint returns the original
        project without writing, and replaying it with a different one is
        refused with ``IdempotencyKeyReused``. Generation ``1`` is written to
        the raw store before the record becomes visible.

        Args:
            organization_id: The owning organization.
            slug: The path segment identifying the project within its
                organization; 2 to 62 characters of lowercase letters, digits
                and hyphens, with no doubled hyphen.
            title: The human-readable name.
            description: Free-text description; may be empty.
            data_classification: A code from the configured vocabulary; it
                cannot be changed afterwards, since ``patch_project`` takes
                none.
            idempotency_key: The caller's ``Idempotency-Key``, scoping replay.

        Returns:
            The stored project, at generation and version ``1``.

        Raises:
            ClassificationUnknown: If ``data_classification`` is not in the
                vocabulary.
            SlugExists: If the organization already has a project with
                ``slug``.
        """
        validate_slug(slug, 62)
        if data_classification not in self._classification_vocabulary:
            raise ClassificationUnknown(f"unknown data classification: {data_classification}")
        organization = self.get_organization(organization_id)
        fingerprint = _fingerprint("project", str(organization_id), slug, title, description)
        with self._lock:
            replay = self._replay(idempotency_key, fingerprint)
            if replay is not None:
                return _expect_type(replay, Project)
            if any(
                item.organization_id == organization_id and item.slug == slug
                for item in self.projects.values()
            ):
                raise SlugExists(f"project slug already exists: {slug}")
            item = Project(
                uuid7(),
                organization_id,
                slug,
                title,
                description,
                data_classification,
                1,
                1,
                datetime.now(UTC),
            )
            self._write_generation(
                project_dir(self.data_root, organization, item),
                item,
            )
            self.projects[item.id] = item
            self._remember(idempotency_key, fingerprint, item)
            return item

    def create_dataset(
        self,
        project_id: UUID,
        *,
        slug: str,
        title: str,
        description: str,
        profile_name: str,
        profile_version: str,
        entry_layer: str = Layer.RAW.value,
        idempotency_key: str,
    ) -> Dataset:
        """Create a dataset under a project and write its first generation.

        The slug is validated by ``validate_slug`` (which raises
        ``PathRuleViolation``), may run to 80 characters - longer than an
        organization or project slug - and is immutable afterwards because
        it names the dataset's storage directory; it must be unique within
        the project. ``entry_layer`` is parsed by ``parse_entry_layer``,
        which raises ``LayerWorkflowError`` for an unknown layer and for
        gold: every gold version needs a derivation record, so nothing may
        enter there directly. The project and its organization must exist
        (``ResourceNotFound`` otherwise). Every dataset starts in the
        ``ACTIVE`` lifecycle state.
        Creation is idempotent per ``idempotency_key``: the fingerprint
        covers the project, slug, title, profile name, profile version and
        entry layer - not the description - so replaying the key with the
        same fingerprint returns the original dataset without writing, and
        replaying it with a different one is refused with
        ``IdempotencyKeyReused``. Generation ``1`` is written to the raw
        store before the record becomes visible.

        Args:
            project_id: The owning project.
            slug: The path segment identifying the dataset within its
                project; 2 to 80 characters of lowercase letters, digits and
                hyphens, with no doubled hyphen.
            title: The human-readable name.
            description: Free-text description; may be empty.
            profile_name: The dataset profile the dataset declares; stored
                verbatim, not validated here.
            profile_version: The declared profile's version; stored verbatim.
            entry_layer: The layer at which the dataset's data first arrives:
                ``raw`` (the default), ``bronze`` or ``silver``, never
                ``gold``.
            idempotency_key: The caller's ``Idempotency-Key``, scoping replay.

        Returns:
            The stored dataset, ``ACTIVE`` at generation and version ``1``.

        Raises:
            SlugExists: If the project already has a dataset with ``slug``.
        """
        validate_slug(slug, 80)
        entry = parse_entry_layer(entry_layer)
        project = self.get_project(project_id)
        organization = self.get_organization(project.organization_id)
        fingerprint = _fingerprint(
            "dataset", str(project_id), slug, title, profile_name, profile_version, entry.value
        )
        with self._lock:
            replay = self._replay(idempotency_key, fingerprint)
            if replay is not None:
                return _expect_type(replay, Dataset)
            if any(
                item.project_id == project_id and item.slug == slug
                for item in self.datasets.values()
            ):
                raise SlugExists(f"dataset slug already exists: {slug}")
            item = Dataset(
                uuid7(),
                project_id,
                slug,
                title,
                description,
                profile_name,
                profile_version,
                entry.value,
                DatasetLifecycle.ACTIVE,
                1,
                1,
                datetime.now(UTC),
            )
            self._write_generation(
                dataset_dir(self.data_root, organization, project, item),
                item,
            )
            self.datasets[item.id] = item
            self._remember(idempotency_key, fingerprint, item)
            return item

    def patch_dataset(
        self,
        dataset_id: UUID,
        *,
        expected_version: int,
        slug: str | None,
        title: str | None,
        description: str | None,
    ) -> Dataset:
        """Apply a partial update to a dataset under a version precondition.

        ``expected_version`` is the version the caller last saw - the route
        derives it from the ``If-Match`` header - and the patch is applied
        only while it still matches, so two editors working from the same
        view cannot silently overwrite each other. The dataset must exist
        (``get_dataset`` raises ``ResourceNotFound``). A ``slug`` that
        differs from the current one is refused before the version is even
        compared: the slug is baked into the dataset's storage path, so no
        role may change it; passing the current slug, or ``None``, is
        accepted. ``title`` and ``description`` replace the stored values
        when given and are left alone when ``None``. Every accepted patch,
        including one that names no field, advances both ``generation`` and
        ``version`` by one; the in-memory record is updated in place under
        the repository lock and the new generation document is written
        before it is returned.

        Args:
            dataset_id: The dataset to update.
            expected_version: The version the caller believes is current.
            slug: The current slug or ``None``; any other value is refused.
            title: A replacement title, or ``None`` to keep the current one.
            description: A replacement description, or ``None`` to keep it.

        Returns:
            The same dataset record, with version and generation advanced.

        Raises:
            SlugImmutable: If ``slug`` names a different slug.
            PreconditionFailed: If ``expected_version`` is not the current
                version.
        """
        with self._lock:
            item = self.get_dataset(dataset_id)
            if slug is not None and slug != item.slug:
                raise SlugImmutable("dataset slugs cannot be changed")
            if item.version != expected_version:
                raise PreconditionFailed(
                    f"expected version {expected_version}, current version is {item.version}"
                )
            if title is not None:
                item.title = title
            if description is not None:
                item.description = description
            item.generation += 1
            item.version += 1
            project = self.get_project(item.project_id)
            organization = self.get_organization(project.organization_id)
            self._write_generation(dataset_dir(self.data_root, organization, project, item), item)
            return item

    def create_release(
        self,
        dataset_id: UUID,
        *,
        tag: str,
        revision_number: int,
        title: str | None,
        created_by: str,
        idempotency_key: str,
    ) -> Release:
        """Pin a release tag to a registered revision of a dataset.

        ``tag`` must satisfy the tag rules (``validate_tag`` raises
        ``PathRuleViolation`` otherwise) and is unique within the dataset for
        all time: the release is stored as a write-once file under the
        dataset's ``releases/`` directory, so a tag is refused both when the
        in-memory map already holds it and when the file already exists on
        disk. The revision is resolved from the seeds ``register_revision``
        published, and the release records that revision's id and number.
        The dataset, its project and its organization must exist
        (``ResourceNotFound`` otherwise). Creation is idempotent per
        ``idempotency_key``: the fingerprint covers the dataset, tag,
        revision number and title (a missing title fingerprints as empty),
        replaying the key with the same fingerprint returns the original
        release without writing, and replaying it with a different one is
        refused with ``IdempotencyKeyReused``. The tag file is written before
        the record becomes visible.

        Args:
            dataset_id: The dataset the tag belongs to.
            tag: The release tag; 2 to 63 characters of lowercase letters,
                digits, dots, underscores and hyphens.
            revision_number: The number of a revision already registered for
                the dataset.
            title: An optional human-readable name for the release.
            created_by: The subject of the principal creating the release.
            idempotency_key: The caller's ``Idempotency-Key``, scoping replay.

        Returns:
            The stored release, pinned to the revision's id and number.

        Raises:
            TagExists: If the dataset already has a release with ``tag``,
                in memory or on disk.
            ResourceNotFound: If no revision ``revision_number`` is
                registered for the dataset (the same error propagates when
                the dataset itself does not exist).
        """
        validate_tag(tag)
        dataset = self.get_dataset(dataset_id)
        project = self.get_project(dataset.project_id)
        organization = self.get_organization(project.organization_id)
        fingerprint = _fingerprint(
            "release", str(dataset_id), tag, str(revision_number), title or ""
        )
        with self._lock:
            replay = self._replay(idempotency_key, fingerprint)
            if replay is not None:
                return _expect_type(replay, Release)
            if (dataset_id, tag) in self.releases:
                raise TagExists(f"release tag already exists: {tag}")
            revision = self.revisions.get((dataset_id, revision_number))
            if revision is None:
                raise ResourceNotFound(f"revision {revision_number} does not exist")
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
            payload = canonical_bytes(jsonable(item))
            tag_path = release_tag_file(self.data_root, organization, project, dataset, tag)
            try:
                self.raw_store.write_tag_once(tag_path, payload)
            except FileExistsError as exc:
                raise TagExists(f"release tag already exists: {tag}") from exc
            self.releases[(dataset_id, tag)] = item
            self._remember(idempotency_key, fingerprint, item)
            return item

    def resolve_release(self, dataset_id: UUID, tag: str) -> Release:
        """Return the release a dataset publishes under a tag.

        Lookup is by the exact ``(dataset_id, tag)`` pair, so a dataset that
        does not exist is indistinguishable from a dataset without that tag.

        Args:
            dataset_id: The dataset the tag belongs to.
            tag: The release tag to resolve.

        Returns:
            The release created under that tag.

        Raises:
            ResourceNotFound: If the dataset has no release with ``tag``.
        """
        item = self.releases.get((dataset_id, tag))
        if item is None:
            raise ResourceNotFound(f"release tag does not exist: {tag}")
        return item

    def register_revision(self, revision: RevisionSeed) -> None:
        """Make a committed revision known so a release tag can be pinned to it.

        There is no HTTP route for this: an ingest pipeline that has
        committed a revision publishes its seed through the repository it
        shares with the application, and ``create_release`` resolves
        ``revision_number`` against these seeds. Seeds are keyed by
        ``(dataset_id, number)``; registering the same pair again replaces
        the earlier seed. The dataset's existence is not checked here.

        Args:
            revision: The committed revision's id, dataset, number and
                manifest digest.
        """
        with self._lock:
            self.revisions[(revision.dataset_id, revision.number)] = revision

    def get_organization(self, item_id: UUID) -> Organization:
        """Return one organization by id.

        The result is the live record the repository holds, not a copy;
        callers read it and leave mutation to ``patch_organization``.

        Args:
            item_id: The organization's id.

        Returns:
            The stored organization record.

        Raises:
            ResourceNotFound: If no organization has ``item_id``.
        """
        try:
            return self.organizations[item_id]
        except KeyError as exc:
            raise ResourceNotFound(f"organization does not exist: {item_id}") from exc

    def get_project(self, item_id: UUID) -> Project:
        """Return one project by id.

        The result is the live record the repository holds, not a copy;
        callers read it and leave mutation to ``patch_project``.

        Args:
            item_id: The project's id.

        Returns:
            The stored project record.

        Raises:
            ResourceNotFound: If no project has ``item_id``.
        """
        try:
            return self.projects[item_id]
        except KeyError as exc:
            raise ResourceNotFound(f"project does not exist: {item_id}") from exc

    def get_dataset(self, item_id: UUID) -> Dataset:
        """Return one dataset by id.

        The result is the live record the repository holds, not a copy;
        callers read it and leave mutation to ``patch_dataset``.

        Args:
            item_id: The dataset's id.

        Returns:
            The stored dataset record.

        Raises:
            ResourceNotFound: If no dataset has ``item_id``.
        """
        try:
            return self.datasets[item_id]
        except KeyError as exc:
            raise ResourceNotFound(f"dataset does not exist: {item_id}") from exc

    def list_organizations(self) -> list[Organization]:
        """Return every organization, ordered by ``(slug, id)``.

        The order is the key the listing route pages by. The result is a
        fresh list, so later creations do not appear in it, but its elements
        are the live records the repository holds, not copies.

        Returns:
            All organizations, sorted by slug and then id.
        """
        return sorted(list(self.organizations.values()), key=lambda item: (item.slug, item.id))

    def list_projects(self, organization_id: UUID) -> list[Project]:
        """Return every project of one organization, ordered by ``(slug, id)``.

        ``ResourceNotFound`` propagates from ``get_organization`` when the
        organization does not exist, so a caller cannot read an empty list
        as "no projects" when it means "no such organization".

        Args:
            organization_id: The organization whose projects to list.

        Returns:
            The organization's projects, sorted by slug and then id.
        """
        self.get_organization(organization_id)
        return sorted(
            (
                item
                for item in list(self.projects.values())
                if item.organization_id == organization_id
            ),
            key=lambda item: (item.slug, item.id),
        )

    def list_datasets(self, project_id: UUID) -> list[Dataset]:
        """Return every dataset of one project, ordered by ``(slug, id)``.

        ``ResourceNotFound`` propagates from ``get_project`` when the project
        does not exist, so an empty list always means "no datasets" and never
        "no such project".

        Args:
            project_id: The project whose datasets to list.

        Returns:
            The project's datasets, sorted by slug and then id.
        """
        self.get_project(project_id)
        return sorted(
            (item for item in list(self.datasets.values()) if item.project_id == project_id),
            key=lambda item: (item.slug, item.id),
        )

    def list_releases(self, dataset_id: UUID) -> list[Release]:
        """Return every release of one dataset, ordered by tag.

        Tags are unique within a dataset, so the tag alone is a total order
        and the key the listing route pages by. ``ResourceNotFound``
        propagates from ``get_dataset`` when the dataset does not exist, so
        an empty list always means "no releases" and never "no such dataset".

        Args:
            dataset_id: The dataset whose releases to list.

        Returns:
            The dataset's releases, sorted by tag.
        """
        self.get_dataset(dataset_id)
        return sorted(
            (
                item
                for (item_dataset_id, _), item in list(self.releases.items())
                if item_dataset_id == dataset_id
            ),
            key=lambda item: item.tag,
        )

    def patch_organization(
        self,
        organization_id: UUID,
        *,
        expected_version: int,
        slug: str | None,
        title: str | None,
        description: str | None,
    ) -> Organization:
        """Apply a partial update to an organization under a version precondition.

        ``expected_version`` is the version the caller last saw - the route
        derives it from the ``If-Match`` header - and the patch is applied
        only while it still matches, so two editors working from the same
        view cannot silently overwrite each other. The organization must
        exist (``get_organization`` raises ``ResourceNotFound``). A ``slug``
        that differs from the current one is refused before the version is
        even compared: the slug is baked into the organization's storage
        path, so no role may change it; passing the current slug, or
        ``None``, is accepted. ``title`` and ``description`` replace the
        stored values when given and are left alone when ``None``. Every
        accepted patch, including one that names no field, advances both
        ``generation`` and ``version`` by one; the in-memory record is
        updated in place under the repository lock and the new generation
        document is written before it is returned.

        Args:
            organization_id: The organization to update.
            expected_version: The version the caller believes is current.
            slug: The current slug or ``None``; any other value is refused.
            title: A replacement title, or ``None`` to keep the current one.
            description: A replacement description, or ``None`` to keep it.

        Returns:
            The same organization record, with version and generation
            advanced.

        Raises:
            SlugImmutable: If ``slug`` names a different slug.
            PreconditionFailed: If ``expected_version`` is not the current
                version.
        """
        with self._lock:
            item = self.get_organization(organization_id)
            if slug is not None and slug != item.slug:
                raise SlugImmutable("organization slugs cannot be changed")
            if item.version != expected_version:
                raise PreconditionFailed(
                    f"expected version {expected_version}, current version is {item.version}"
                )
            if title is not None:
                item.title = title
            if description is not None:
                item.description = description
            item.generation += 1
            item.version += 1
            self._write_generation(organization_dir(self.data_root, item), item)
            return item

    def patch_project(
        self,
        project_id: UUID,
        *,
        expected_version: int,
        slug: str | None,
        title: str | None,
        description: str | None,
    ) -> Project:
        """Apply a partial update to a project under a version precondition.

        ``expected_version`` is the version the caller last saw - the route
        derives it from the ``If-Match`` header - and the patch is applied
        only while it still matches, so two editors working from the same
        view cannot silently overwrite each other. The project must exist
        (``get_project`` raises ``ResourceNotFound``). A ``slug`` that
        differs from the current one is refused before the version is even
        compared: the slug is baked into the project's storage path, so no
        role may change it; passing the current slug, or ``None``, is
        accepted. ``title`` and ``description`` replace the stored values
        when given and are left alone when ``None``; the data classification
        has no parameter here and so cannot change. Every accepted patch,
        including one that names no field, advances both ``generation`` and
        ``version`` by one; the in-memory record is updated in place under
        the repository lock and the new generation document is written
        before it is returned.

        Args:
            project_id: The project to update.
            expected_version: The version the caller believes is current.
            slug: The current slug or ``None``; any other value is refused.
            title: A replacement title, or ``None`` to keep the current one.
            description: A replacement description, or ``None`` to keep it.

        Returns:
            The same project record, with version and generation advanced.

        Raises:
            SlugImmutable: If ``slug`` names a different slug.
            PreconditionFailed: If ``expected_version`` is not the current
                version.
        """
        with self._lock:
            item = self.get_project(project_id)
            if slug is not None and slug != item.slug:
                raise SlugImmutable("project slugs cannot be changed")
            if item.version != expected_version:
                raise PreconditionFailed(
                    f"expected version {expected_version}, current version is {item.version}"
                )
            if title is not None:
                item.title = title
            if description is not None:
                item.description = description
            item.generation += 1
            item.version += 1
            organization = self.get_organization(item.organization_id)
            self._write_generation(project_dir(self.data_root, organization, item), item)
            return item

    # -- RBAC ------------------------------------------------------------
    # Every method below delegates to ``self._rbac_store``; the only logic
    # kept here is what depends on the in-memory organization/project/dataset
    # hierarchy the RBAC store deliberately knows nothing about (existence
    # checks, and the service-account subject derived from the org slug).

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
        self._require_scope(scope_type, scope_id)
        return await self._rbac_store.grant_role(
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
        return await self._rbac_store.revoke_role(binding_id)

    async def get_role_binding(self, binding_id: UUID) -> RoleBindingRecord:
        """Return one role binding by id.

        The store raises ``ResourceNotFound`` when no such binding exists.

        Args:
            binding_id: The binding's id.

        Returns:
            The stored binding.
        """
        return await self._rbac_store.get_role_binding(binding_id)

    async def bindings_for(self, identifiers: frozenset[str]) -> tuple[Binding, ...]:
        """Return the compiled capability bindings held by any of some identifiers.

        ``identifiers`` is a principal's whole identifier set - its own
        ``user:`` or ``sa:`` name plus one ``group:`` entry per group - so a
        single call answers "what may this caller do" in the form
        ``decide()`` consumes. The result is whatever the store compiles from
        the stored grants; the per-request binding cache memoizes it by
        identifier set.

        Args:
            identifiers: The ``kind:subject`` strings that count as the
                caller.

        Returns:
            The compiled bindings whose principal is one of ``identifiers``.
        """
        return await self._rbac_store.bindings_for(identifiers)

    async def bindings_at(
        self, scope_type: ScopeType, scope_id: UUID | None
    ) -> list[RoleBindingRecord]:
        """Return the role bindings granted at exactly one scope.

        Only bindings stored at this scope are returned; inheritance from
        enclosing scopes is ``decide()``'s concern, not a listing's. The
        scope's existence is not checked here - an unknown ``scope_id``
        simply has no bindings.

        Args:
            scope_type: The level to list.
            scope_id: The organization, project or dataset id, or ``None``
                for ``SYSTEM`` scope.

        Returns:
            The bindings at that scope, ordered by ``(principal, role_code)``.
        """
        return await self._rbac_store.bindings_at(scope_type, scope_id)

    async def create_service_account(
        self, organization_id: UUID, *, name: str, created_by: str
    ) -> ServiceAccount:
        """Create a service account whose subject derives from the organization slug.

        ``name`` is validated as a slug with the organization/project length
        limit (``validate_slug`` raises ``PathRuleViolation`` otherwise) and
        the organization must exist (``get_organization`` raises
        ``ResourceNotFound``). The account's subject is
        ``{organization slug}/{name}``: that is what its API keys
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
        """
        validate_slug(name, 62)
        organization = self.get_organization(organization_id)
        subject = f"{organization.slug}/{name}"
        return await self._rbac_store.create_service_account(
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
        return await self._rbac_store.get_service_account(principal_id)

    async def service_account_by_subject(self, subject: str) -> ServiceAccount:
        """Return one service account by the subject its API keys carry.

        This is how an authenticated ``sa:`` principal is traced back to its
        owning organization, from which its whole authority is synthesized.
        The store raises ``ResourceNotFound`` when no account has
        ``subject`` - for example a key that outlived its account.

        Args:
            subject: The ``{organization slug}/{name}`` subject.

        Returns:
            The stored account, disabled or not.
        """
        return await self._rbac_store.service_account_by_subject(subject)

    async def list_service_accounts(self, organization_id: UUID) -> list[ServiceAccount]:
        """Return every service account of one organization, ordered by name.

        The organization's existence is not checked here; an unknown
        organization simply has no accounts.

        Args:
            organization_id: The organization whose accounts to list.

        Returns:
            The organization's accounts, sorted by name.
        """
        return await self._rbac_store.list_service_accounts(organization_id)

    async def disable_service_account(
        self, principal_id: UUID, *, disabled_at: datetime
    ) -> ServiceAccount:
        """Mark a service account disabled as of a moment.

        Disabling is recorded, not deleted: the account stays resolvable by
        id and by subject with ``disabled_at`` set, and a disabled account
        resolves to no bindings. Revoking the account's existing API keys is
        the caller's job, not this method's. The store raises
        ``ResourceNotFound`` when no such account exists.

        Args:
            principal_id: The account's principal id.
            disabled_at: The instant recorded as the disabling time.

        Returns:
            The account with ``disabled_at`` set.
        """
        return await self._rbac_store.disable_service_account(principal_id, disabled_at=disabled_at)

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
        return await self._rbac_store.create_policy(
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
        self._require_scope(scope_type, scope_id)
        return await self._rbac_store.attach_policy(
            policy_id, scope_type=scope_type, scope_id=scope_id, attached_by=attached_by
        )

    async def list_policies(self) -> list[Policy]:
        """Return every policy, ordered by ``(name, id)``.

        The order is the key the listing route pages by; ``id`` breaks ties
        because names are not unique.

        Returns:
            All policies, sorted by name and then id.
        """
        return await self._rbac_store.list_policies()

    def _require_scope(self, scope_type: ScopeType, scope_id: UUID | None) -> None:
        """Reject an internally inconsistent scope/id pair.

        No request can produce one of these - each binding route passes
        the pair its own path supplies, and the SYSTEM route passes ``None``
        literally - so this is a caller bug, not a client contract, and its
        honest answer is the 500 the unhandled-exception path produces.

        A consistent pair is then checked for existence: the organization,
        project or dataset ``scope_id`` names must be known, and the
        matching getter raises ``ResourceNotFound`` when it is not. That
        one is a client contract - a grant or attachment cannot point at
        nothing. ``SYSTEM`` scope has nothing to look up.

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
            self.get_organization(scope_id)
        elif scope_type is ScopeType.PROJECT:
            self.get_project(scope_id)
        else:
            self.get_dataset(scope_id)

    def _write_generation(
        self, entity_path: PurePosixPath, item: Organization | Project | Dataset
    ) -> None:
        """Persist one record as its current generation document.

        The record is rendered with ``jsonable``, stamped with the
        ``urn:huron:generation:1`` schema and serialized canonically, then
        handed to the raw store, which writes
        ``generations/{generation:06d}.json`` exactly once and atomically
        repoints ``CURRENT.json`` at it. The caller must already have
        advanced ``item.generation`` to a number not yet written: the store
        refuses an existing generation file with ``FileExistsError`` and a
        number outside ``1..999999`` with ``ValueError``.

        Args:
            entity_path: The entity's directory under the data root, as
                built by :mod:`huron.pkg.catalog.paths`.
            item: The organization, project or dataset to persist.
        """
        document = jsonable(item)
        document["schema"] = "urn:huron:generation:1"
        self.raw_store.write_generation(entity_path, item.generation, canonical_bytes(document))

    def _replay(self, key: str, fingerprint: str) -> object | None:
        """Return the result remembered under an idempotency key, if any.

        Keys are global to the repository rather than per resource kind, so
        the fingerprint - which starts with the kind - is what tells a
        legitimate replay from a reused key. Must be called with the
        repository lock held.

        Args:
            key: The caller's ``Idempotency-Key``.
            fingerprint: The digest of the request being attempted.

        Returns:
            The record created under ``key`` when its fingerprint matches,
            or ``None`` when the key has not been seen.

        Raises:
            IdempotencyKeyReused: If ``key`` was used for a request with a
                different fingerprint.
        """
        stored = self._idempotency.get(key)
        if stored is None:
            return None
        if stored[0] != fingerprint:
            raise IdempotencyKeyReused("idempotency key was reused with a different request")
        return stored[1]

    def _remember(self, key: str, fingerprint: str, result: object) -> None:
        """Record the result a creation produced under an idempotency key.

        Called only once a creation has fully succeeded, so a refused or
        failed attempt leaves the key free to be retried. Must be called
        with the repository lock held.

        Args:
            key: The caller's ``Idempotency-Key``.
            fingerprint: The digest of the request that produced ``result``.
            result: The record to hand back on replay.
        """
        self._idempotency[key] = (fingerprint, result)


def _fingerprint(*parts: str) -> str:
    """Digest the identifying fields of a create request.

    The parts are joined with a NUL byte before hashing so adjacent parts
    cannot run together: ``("ab", "c")`` and ``("a", "bc")`` digest
    differently. Every caller passes the resource kind first, which keeps
    the fingerprints of different kinds distinct even for identical fields.

    Args:
        *parts: The resource kind followed by the request's fields, all as
            strings.

    Returns:
        The SHA-256 hex digest of the joined parts.
    """
    return hashlib.sha256("\x00".join(parts).encode()).hexdigest()


def _expect_type[T](value: object, expected: type[T]) -> T:
    """Narrow a replayed idempotency result to the record type its caller returns.

    Every fingerprint starts with the resource kind, so a key can only ever
    replay a record of the kind that stored it; a mismatch means the
    idempotency map itself is corrupt, which is an invariant failure rather
    than a client error.

    Args:
        value: The result stored under an idempotency key.
        expected: The record class the calling creation method returns.

    Returns:
        ``value``, typed as ``expected``.

    Raises:
        RuntimeError: If ``value`` is not an instance of ``expected``.
    """
    if not isinstance(value, expected):
        raise RuntimeError("idempotency record has an unexpected result type")
    return value
