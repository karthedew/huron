"""Hierarchy application service used by the HTTP composition root.

The production structural adapter is PostgreSQL; this small repository keeps
the use-case sequencing independently testable and provides a local API mode.
Filesystem generation/release documents are always written before the result
is made visible through this repository.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from threading import RLock
from typing import Protocol
from uuid import UUID

from huron.pkg.auth import (
    ApiKeyRecord,
    ApiKeyStore,
    CredentialStore,
    MemoryApiKeyStore,
    MemoryCredentialStore,
    MemoryPrincipalStore,
    MemorySessionStore,
    PrincipalStore,
    SessionStore,
)
from huron.pkg.catalog.errors import (
    DomainError,
    IdempotencyKeyReused,
    PreconditionFailed,
    SlugImmutable,
    TagExists,
    TagWithdrawn,
)
from huron.pkg.catalog.ids import uuid7
from huron.pkg.catalog.layers import Layer, parse_entry_layer
from huron.pkg.catalog.manifest import canonical_bytes
from huron.pkg.catalog.models import EntityRef
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
from huron.pkg.rbac.roles import compile_binding


class ResourceNotFound(DomainError):
    code, status_code = "NOT_FOUND", 404


@dataclass(slots=True)
class Organization:
    id: UUID
    slug: str
    title: str
    description: str
    generation: int
    version: int
    created_at: datetime


@dataclass(slots=True)
class Project:
    id: UUID
    organization_id: UUID
    slug: str
    title: str
    description: str
    data_classification: str
    generation: int
    version: int
    created_at: datetime


@dataclass(slots=True)
class Dataset:
    id: UUID
    project_id: UUID
    slug: str
    title: str
    description: str
    profile_name: str
    profile_version: str
    #: Where this dataset's data first arrives: raw (the default), bronze or
    #: silver. Above raw means the lake is not the origin of these bytes, so
    #: there is no raw revision and no Bronze snapshot to wait for.
    entry_layer: str
    lifecycle_state: str
    generation: int
    version: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class RevisionSeed:
    id: UUID
    dataset_id: UUID
    number: int
    manifest_sha256: str


@dataclass(slots=True)
class Release:
    id: UUID
    dataset_id: UUID
    tag: str
    revision_id: UUID
    revision_number: int
    title: str | None
    created_by: str
    created_at: datetime
    withdrawn_at: datetime | None = None
    withdrawn_reason: str | None = None


@dataclass(slots=True)
class RoleBindingRecord:
    id: UUID
    principal: str
    role_code: str
    scope_type: str
    scope_id: UUID | None
    created_by: str
    created_at: datetime
    expires_at: datetime | None = None


@dataclass(slots=True)
class ServiceAccount:
    principal_id: UUID
    organization_id: UUID
    name: str
    subject: str
    created_by: str
    created_at: datetime


@dataclass(slots=True)
class Policy:
    id: UUID
    policy_type: str
    name: str
    spec: dict[str, object]
    created_by: str
    created_at: datetime


@dataclass(slots=True)
class PolicyAttachment:
    policy_id: UUID
    scope_type: str
    scope_id: UUID
    attached_by: str
    attached_at: datetime


class RbacStore(Protocol):
    """What ``HierarchyRepository`` needs from an RBAC storage backend.

    ``InMemoryRbacStore`` and ``PostgresRbacStore`` (``postgres_rbac.py``)
    both conform structurally - neither imports the other, following the
    same consumer-owned-Protocol idiom as ``pkg/catalog/ports.py``. Scope
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

    async def list_service_accounts(self, organization_id: UUID) -> list[ServiceAccount]: ...

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


class InMemoryRbacStore:
    """The reference RBAC store: precompiled bindings held in process memory.

    This is what every unit test runs against, and what ``HierarchyRepository``
    defaults to when no store is injected, so existing behavior is unchanged
    unless a composition root explicitly wires ``PostgresRbacStore`` instead.
    """

    def __init__(self) -> None:
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

        ``compile_binding`` raises RoleError subclasses when the role does not
        exist, the principal kind is not allowed (e.g. ``pipeline`` for a
        user), or the scope level is not bindable.
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
                raise DomainError("an identical role binding already exists")
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
        with self._lock:
            record = self._role_bindings.pop(binding_id, None)
            if record is None:
                raise ResourceNotFound(f"role binding does not exist: {binding_id}")
            self._compiled.pop(binding_id, None)
            return record

    async def get_role_binding(self, binding_id: UUID) -> RoleBindingRecord:
        record = self._role_bindings.get(binding_id)
        if record is None:
            raise ResourceNotFound(f"role binding does not exist: {binding_id}")
        return record

    async def bindings_for(self, identifiers: frozenset[str]) -> tuple[Binding, ...]:
        """Every compiled capability binding whose principal the caller is."""
        return tuple(
            binding
            for record_id, bindings in self._compiled.items()
            if self._role_bindings[record_id].principal in identifiers
            for binding in bindings
        )

    async def bindings_at(
        self, scope_type: ScopeType, scope_id: UUID | None
    ) -> list[RoleBindingRecord]:
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
        with self._lock:
            if any(
                item.organization_id == organization_id and item.name == name
                for item in self._service_accounts.values()
            ):
                raise DomainError(f"service account already exists: {name}")
            record = ServiceAccount(
                uuid7(), organization_id, name, subject, created_by, datetime.now(UTC)
            )
            self._service_accounts[record.principal_id] = record
            return record

    async def get_service_account(self, principal_id: UUID) -> ServiceAccount:
        record = self._service_accounts.get(principal_id)
        if record is None:
            raise ResourceNotFound(f"service account does not exist: {principal_id}")
        return record

    async def list_service_accounts(self, organization_id: UUID) -> list[ServiceAccount]:
        items = [
            item
            for item in self._service_accounts.values()
            if item.organization_id == organization_id
        ]
        return sorted(items, key=lambda item: item.name)

    async def create_policy(
        self, *, policy_type: str, name: str, spec: dict[str, object], created_by: str
    ) -> Policy:
        with self._lock:
            record = Policy(uuid7(), policy_type, name, spec, created_by, datetime.now(UTC))
            self._policies[record.id] = record
            return record

    async def attach_policy(
        self, policy_id: UUID, *, scope_type: ScopeType, scope_id: UUID, attached_by: str
    ) -> PolicyAttachment:
        if policy_id not in self._policies:
            raise ResourceNotFound(f"policy does not exist: {policy_id}")
        with self._lock:
            if any(
                item.policy_id == policy_id
                and item.scope_type == scope_type.value
                and item.scope_id == scope_id
                for item in self._policy_attachments
            ):
                raise DomainError("policy is already attached at this scope")
            attachment = PolicyAttachment(
                policy_id, scope_type.value, scope_id, attached_by, datetime.now(UTC)
            )
            self._policy_attachments.append(attachment)
            return attachment

    async def list_policies(self) -> list[Policy]:
        return sorted(self._policies.values(), key=lambda item: item.name)


class HierarchyRepository:
    def __init__(
        self,
        raw_store: PosixRawStore,
        *,
        rbac_store: RbacStore | None = None,
        api_key_store: ApiKeyWriter | None = None,
        credential_store: CredentialStore | None = None,
        session_store: SessionStore | None = None,
        principal_store: PrincipalStore | None = None,
    ):
        self.raw_store = raw_store
        self.raw_store.initialize()
        self.organizations: dict[UUID, Organization] = {}
        self.projects: dict[UUID, Project] = {}
        self.datasets: dict[UUID, Dataset] = {}
        self.revisions: dict[tuple[UUID, int], RevisionSeed] = {}
        self.releases: dict[tuple[UUID, str], Release] = {}
        # Each repository gets its own fresh in-memory store when one isn't
        # injected - a shared default instance would leak role bindings and
        # API keys across every test and every HierarchyRepository built
        # without one.
        self.rbac_store: RbacStore = rbac_store if rbac_store is not None else InMemoryRbacStore()
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
        return PurePosixPath(self.raw_store.root)

    def create_organization(
        self,
        *,
        slug: str,
        title: str,
        description: str,
        idempotency_key: str,
    ) -> Organization:
        validate_org_slug(slug)
        fingerprint = _fingerprint("organization", slug, title, description)
        with self._lock:
            replay = self._replay(idempotency_key, fingerprint)
            if replay is not None:
                return _expect_type(replay, Organization)
            if any(item.slug == slug for item in self.organizations.values()):
                raise DomainError(f"organization slug already exists: {slug}")
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
        validate_slug(slug, 62)
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
                raise DomainError(f"project slug already exists: {slug}")
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
                raise DomainError(f"dataset slug already exists: {slug}")
            item = Dataset(
                uuid7(),
                project_id,
                slug,
                title,
                description,
                profile_name,
                profile_version,
                entry.value,
                "DRAFT",
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
            payload = canonical_bytes(_jsonable(item))
            tag_path = release_tag_file(self.data_root, organization, project, dataset, tag)
            try:
                self.raw_store.write_tag_once(tag_path, payload)
            except FileExistsError as exc:
                raise TagExists(f"release tag already exists: {tag}") from exc
            self.releases[(dataset_id, tag)] = item
            self._remember(idempotency_key, fingerprint, item)
            return item

    def resolve_release(self, dataset_id: UUID, tag: str) -> Release:
        item = self.releases.get((dataset_id, tag))
        if item is None:
            raise ResourceNotFound(f"release tag does not exist: {tag}")
        if item.withdrawn_at is not None:
            raise TagWithdrawn(f"release tag has been withdrawn: {tag}")
        return item

    def register_revision(self, revision: RevisionSeed) -> None:
        with self._lock:
            self.revisions[(revision.dataset_id, revision.number)] = revision

    def get_organization(self, item_id: UUID) -> Organization:
        try:
            return self.organizations[item_id]
        except KeyError as exc:
            raise ResourceNotFound(f"organization does not exist: {item_id}") from exc

    def get_project(self, item_id: UUID) -> Project:
        try:
            return self.projects[item_id]
        except KeyError as exc:
            raise ResourceNotFound(f"project does not exist: {item_id}") from exc

    def get_dataset(self, item_id: UUID) -> Dataset:
        try:
            return self.datasets[item_id]
        except KeyError as exc:
            raise ResourceNotFound(f"dataset does not exist: {item_id}") from exc

    def patch_organization(
        self,
        organization_id: UUID,
        *,
        expected_version: int,
        slug: str | None,
        title: str | None,
        description: str | None,
    ) -> Organization:
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
    # Every method below delegates to ``self.rbac_store``; the only logic
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
        self._require_scope(scope_type, scope_id)
        return await self.rbac_store.grant_role(
            principal=principal,
            role_code=role_code,
            scope_type=scope_type,
            scope_id=scope_id,
            created_by=created_by,
            expires_at=expires_at,
        )

    async def revoke_role(self, binding_id: UUID) -> RoleBindingRecord:
        return await self.rbac_store.revoke_role(binding_id)

    async def get_role_binding(self, binding_id: UUID) -> RoleBindingRecord:
        return await self.rbac_store.get_role_binding(binding_id)

    async def bindings_for(self, identifiers: frozenset[str]) -> tuple[Binding, ...]:
        return await self.rbac_store.bindings_for(identifiers)

    async def bindings_at(
        self, scope_type: ScopeType, scope_id: UUID | None
    ) -> list[RoleBindingRecord]:
        return await self.rbac_store.bindings_at(scope_type, scope_id)

    async def create_service_account(
        self, organization_id: UUID, *, name: str, created_by: str
    ) -> ServiceAccount:
        validate_slug(name, 62)
        organization = self.get_organization(organization_id)
        subject = f"{organization.slug}/{name}"
        return await self.rbac_store.create_service_account(
            organization_id, name=name, subject=subject, created_by=created_by
        )

    async def get_service_account(self, principal_id: UUID) -> ServiceAccount:
        return await self.rbac_store.get_service_account(principal_id)

    async def list_service_accounts(self, organization_id: UUID) -> list[ServiceAccount]:
        return await self.rbac_store.list_service_accounts(organization_id)

    async def create_policy(
        self, *, policy_type: str, name: str, spec: dict[str, object], created_by: str
    ) -> Policy:
        return await self.rbac_store.create_policy(
            policy_type=policy_type, name=name, spec=spec, created_by=created_by
        )

    async def attach_policy(
        self, policy_id: UUID, *, scope_type: ScopeType, scope_id: UUID, attached_by: str
    ) -> PolicyAttachment:
        self._require_scope(scope_type, scope_id)
        return await self.rbac_store.attach_policy(
            policy_id, scope_type=scope_type, scope_id=scope_id, attached_by=attached_by
        )

    async def list_policies(self) -> list[Policy]:
        return await self.rbac_store.list_policies()

    def _require_scope(self, scope_type: ScopeType, scope_id: UUID | None) -> None:
        if scope_type is ScopeType.SYSTEM:
            if scope_id is not None:
                raise DomainError("SYSTEM scope takes no scope_id")
            return
        if scope_id is None:
            raise DomainError(f"{scope_type.value} scope requires a scope_id")
        if scope_type is ScopeType.ORGANIZATION:
            self.get_organization(scope_id)
        elif scope_type is ScopeType.PROJECT:
            self.get_project(scope_id)
        else:
            self.get_dataset(scope_id)

    def _write_generation(self, entity_path: PurePosixPath, item: object) -> None:
        document = _jsonable(item)
        document["schema"] = "urn:huron:generation:1"
        self.raw_store.write_generation(
            entity_path, int(document["generation"]), canonical_bytes(document)
        )

    def _replay(self, key: str, fingerprint: str) -> object | None:
        stored = self._idempotency.get(key)
        if stored is None:
            return None
        if stored[0] != fingerprint:
            raise IdempotencyKeyReused("idempotency key was reused with a different request")
        return stored[1]

    def _remember(self, key: str, fingerprint: str, result: object) -> None:
        self._idempotency[key] = (fingerprint, result)


def _jsonable(item: object) -> dict[str, object]:
    values = asdict(item)  # type: ignore[arg-type]
    result: dict[str, object] = {}
    for key, value in values.items():
        if isinstance(value, UUID):
            result[key] = str(value)
        elif isinstance(value, datetime):
            result[key] = value.isoformat().replace("+00:00", "Z")
        else:
            result[key] = value
    return result


def _fingerprint(*parts: str) -> str:
    return hashlib.sha256("\x00".join(parts).encode()).hexdigest()


def _expect_type[T](value: object, expected: type[T]) -> T:
    if not isinstance(value, expected):
        raise RuntimeError("idempotency record has an unexpected result type")
    return value


def entity_ref(item: Organization | Project | Dataset) -> EntityRef:
    return EntityRef(item.id, item.slug)


def local_repository(data_root: str | Path) -> HierarchyRepository:
    return HierarchyRepository(PosixRawStore(data_root))
