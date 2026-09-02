"""The record types the API tier stores and serializes.

Nine dataclasses with no behavior and no project imports. This module is the
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
    #: ``DatasetLifecycle`` member name, stored as ``str`` so this module
    #: needs no import from ``huron.pkg`` - the same reason ``scope_type``
    #: below is ``str`` rather than ``ScopeType``.
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
    disabled_at: datetime | None = None


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


def jsonable(item: DataclassInstance) -> dict[str, object]:
    """Render one record as the JSON-ready mapping persisted to storage."""
    result: dict[str, object] = {}
    for key, value in asdict(item).items():
        if isinstance(value, UUID):
            result[key] = str(value)
        elif isinstance(value, datetime):
            result[key] = value.isoformat().replace("+00:00", "Z")
        else:
            result[key] = value
    return result
