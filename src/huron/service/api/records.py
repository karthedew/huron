"""The record types the API tier stores and serializes.

Eight dataclasses with no behavior and no project imports. This module is the
leaf the rest of the tier depends on: a storage adapter needs a record type,
not the application service that happens to have declared it, and keeping
the records here is what lets ``stores`` import them without importing
``repository``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from _typeshed import DataclassInstance


@dataclass(slots=True)
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


@dataclass(slots=True)
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


@dataclass(slots=True)
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
    result: dict[str, object] = {}
    for key, value in asdict(item).items():
        if isinstance(value, UUID):
            result[key] = str(value)
        elif isinstance(value, datetime):
            result[key] = value.isoformat().replace("+00:00", "Z")
        else:
            result[key] = value
    return result
