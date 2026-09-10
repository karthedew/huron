"""Catalog entities and persistence records shared by core and adapters.

Immutable hierarchy entities own descriptive updates and identity invariants.
Adapters persist these values without importing the workflows that use them.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime
from typing import TYPE_CHECKING, Self
from uuid import UUID

from .errors import PreconditionFailed, SlugImmutable

if TYPE_CHECKING:
    from _typeshed import DataclassInstance


@dataclass(frozen=True, slots=True)
class Organization:
    """The root of the hierarchy: the tenant that owns projects.

    ``slug`` is unique platform-wide and immutable once assigned; ``title``
    and ``description`` may change. ``generation`` numbers the immutable
    JSON document written to the raw store for each state the record has
    had, and ``version`` is the optimistic-concurrency counter a PATCH must
    match through ``If-Match``. Both start at 1 and advance together on
    every change.
    """

    id: UUID
    slug: str
    title: str
    description: str
    generation: int
    version: int
    created_at: datetime

    def describe(
        self,
        *,
        expected_version: int,
        slug: str | None,
        title: str | None,
        description: str | None,
    ) -> Self:
        """Change descriptive fields while protecting identity and version invariants.

        A rename raises ``SlugImmutable``; a stale version raises
        ``PreconditionFailed``, including when no descriptive field changes.

        Args:
            expected_version: The version observed by the caller.
            slug: The existing slug or None; renaming is forbidden.
            title: A replacement title, or None to retain it.
            description: A replacement description, or None to retain it.

        Returns:
            The unchanged object, or an immutable successor with advanced counters.
        """
        return _describe(self, "organization", expected_version, slug, title, description)


@dataclass(frozen=True, slots=True)
class Project:
    """A project within one organization, carrying a data classification.

    ``slug`` is unique within the owning organization and immutable.
    ``data_classification`` is a code from the deployment's vocabulary and
    governs which principals may discover the project's datasets.
    ``generation`` and ``version`` mean what they mean on
    :class:`Organization`: the raw-store document number and the
    ``If-Match`` counter, advancing together.
    """

    id: UUID
    organization_id: UUID
    slug: str
    title: str
    description: str
    data_classification: str
    generation: int
    version: int
    created_at: datetime

    def describe(
        self,
        *,
        expected_version: int,
        slug: str | None,
        title: str | None,
        description: str | None,
    ) -> Self:
        """Change descriptive fields while protecting identity and version invariants.

        A rename raises ``SlugImmutable``; a stale version raises
        ``PreconditionFailed``, including when no descriptive field changes.

        Args:
            expected_version: The version observed by the caller.
            slug: The existing slug or None; renaming is forbidden.
            title: A replacement title, or None to retain it.
            description: A replacement description, or None to retain it.

        Returns:
            The unchanged object, or an immutable successor with advanced counters.
        """
        return _describe(self, "project", expected_version, slug, title, description)


@dataclass(frozen=True, slots=True)
class Dataset:
    """A dataset within one project: the unit revisions and releases belong to.

    ``slug`` is unique within the owning project and immutable, as are the
    declared science profile (``profile_name``/``profile_version``) and the
    entry layer; ``title`` and ``description`` may change, advancing
    ``generation`` (the raw-store document number) and ``version`` (the
    ``If-Match`` counter) together. ``lifecycle_state`` names the dataset's
    stage in its lifecycle - active, retired or superseded - and every
    dataset is created active.
    """

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
    #: ``DatasetLifecycle`` member name, stored as ``str`` so this module
    #: needs no import from ``huron.pkg`` - the same reason ``scope_type``
    #: below is ``str`` rather than ``ScopeType``.
    lifecycle_state: str
    generation: int
    version: int
    created_at: datetime

    def describe(
        self,
        *,
        expected_version: int,
        slug: str | None,
        title: str | None,
        description: str | None,
    ) -> Self:
        """Change descriptive fields while protecting identity and version invariants.

        A rename raises ``SlugImmutable``; a stale version raises
        ``PreconditionFailed``, including when no descriptive field changes.

        Args:
            expected_version: The version observed by the caller.
            slug: The existing slug or None; renaming is forbidden.
            title: A replacement title, or None to retain it.
            description: A replacement description, or None to retain it.

        Returns:
            The unchanged object, or an immutable successor with advanced counters.
        """
        return _describe(self, "dataset", expected_version, slug, title, description)


def _describe[ItemT: Organization | Project | Dataset](
    item: ItemT,
    kind: str,
    expected_version: int,
    slug: str | None,
    title: str | None,
    description: str | None,
) -> ItemT:
    """Apply the shared immutable descriptive update contract to a hierarchy entity.

    Args:
        item: The current immutable entity.
        kind: The entity kind used in the slug-conflict error.
        expected_version: The version observed by the caller.
        slug: The existing slug or None; renaming is forbidden.
        title: A replacement title, or None to retain it.
        description: A replacement description, or None to retain it.

    Returns:
        The same object for a no-op, or a successor advancing both counters once.

    Raises:
        SlugImmutable: If the caller attempts to change the slug.
        PreconditionFailed: If the observed version is stale, even for a no-op.
    """
    if slug is not None and slug != item.slug:
        raise SlugImmutable(f"{kind} slugs cannot be changed")
    if expected_version != item.version:
        raise PreconditionFailed(
            f"expected version {expected_version}, current version is {item.version}"
        )
    next_title = item.title if title is None else title
    next_description = item.description if description is None else description
    if (next_title, next_description) == (item.title, item.description):
        return item
    return replace(
        item,
        title=next_title,
        description=next_description,
        generation=item.generation + 1,
        version=item.version + 1,
    )


@dataclass(slots=True)
class Release:
    """A named tag pinning one revision of a dataset.

    ``tag`` is unique within the dataset and the release is written once to
    the raw store, so neither the tag nor the revision it points at can be
    reassigned; ``revision_id`` and ``revision_number`` are both kept so a
    reader needs no join to name the revision either way.
    """

    id: UUID
    dataset_id: UUID
    tag: str
    revision_id: UUID
    revision_number: int
    title: str | None
    created_by: str
    created_at: datetime


@dataclass(slots=True)
class RoleBindingRecord:
    """One stored grant of a role to a principal at a scope.

    ``principal`` is the ``kind:subject`` identifier string (``user:``,
    ``group:`` or ``sa:``), ``role_code`` a role from the role model, and
    ``scope_type``/``scope_id`` the level and target the role applies at,
    with ``scope_id`` ``None`` only for SYSTEM scope. The triple is unique.
    ``expires_at`` is ``None`` for a grant that does not lapse; an expired
    binding is ignored by the decision engine rather than deleted.
    """

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
    """A non-human principal owned by one organization.

    ``name`` is unique within the owning organization; ``subject`` is what
    the account's API keys authenticate as, and is what its synthesized
    bindings are issued to. A service account holds no roles: its
    authority is a fixed property of the principal kind, scoped to
    ``organization_id``. ``disabled_at`` is set when the account is
    disabled; its keys are revoked at the same moment, and the binding
    synthesis checks the flag as well, so a disabled account is denied
    everywhere even by a credential that still resolves.
    """

    principal_id: UUID
    organization_id: UUID
    name: str
    subject: str
    created_by: str
    created_at: datetime
    disabled_at: datetime | None = None


@dataclass(slots=True)
class Policy:
    """A stored policy definition. Creating one grants nothing; attaching it does.

    ``spec`` is the caller's own JSON, stored and returned verbatim: the
    service does not interpret it, and ``policy_type`` is likewise a label
    the caller chooses. What a policy means is decided by whatever reads
    the attachments, not by this tier.
    """

    id: UUID
    policy_type: str
    name: str
    spec: dict[str, object]
    created_by: str
    created_at: datetime


@dataclass(slots=True)
class AuditEvent:
    """One append-only audit row: who did what to which subject, and when.

    ``subject_kind`` and ``subject_id`` name what the event is about -
    typically an ingest session or a revision - while ``actor`` is the
    principal subject that caused it, or ``"system:sweep"`` for an event
    the expiry sweep raises on nobody's request.
    """

    id: UUID
    kind: str
    actor: str
    subject_kind: str
    subject_id: UUID | None
    payload: dict[str, object]
    created_at: datetime


@dataclass(slots=True)
class PolicyAttachment:
    """One policy applied at one scope.

    A policy attaches to a given scope at most once. ``scope_id`` is never
    ``None``: policies attach to an organization, project or dataset, not
    to the platform as a whole.
    """

    policy_id: UUID
    scope_type: str
    scope_id: UUID
    attached_by: str
    attached_at: datetime


def jsonable_value(value: object) -> object:
    """Render one field's value in the same JSON-ready form ``jsonable`` gives it.

    Args:
        value: The value to render.

    Returns:
        The value's string form for a UUID, its ISO 8601 form with a
        ``Z`` suffix in place of ``+00:00`` for a datetime, and the value
        unchanged for anything else.
    """
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    return value


def jsonable(item: DataclassInstance) -> dict[str, object]:
    """Render one record as the JSON-ready mapping persisted to storage.

    Only two conversions are applied - UUIDs become their string form and
    datetimes their ISO 8601 form with a ``Z`` suffix in place of
    ``+00:00`` - so the stored document is byte-stable across processes
    and can be canonicalized and hashed.

    Args:
        item: Any of the record dataclasses in this module.

    Returns:
        The record's fields by name, in declaration order, with UUID and
        datetime values rendered as strings and every other value passed
        through unchanged.
    """
    return {key: jsonable_value(value) for key, value in asdict(item).items()}
