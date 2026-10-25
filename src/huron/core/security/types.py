"""Governance records owned by Security."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from .principal import Principal


@dataclass(frozen=True, slots=True)
class ResolvedCredential:
    """Authenticated actor after credential bookkeeping."""

    actor: Principal


@dataclass(slots=True)
class RoleBindingRecord:
    """A stored role grant; expired grants remain recorded but confer no authority."""

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
    """A roleless principal owned by one organization, with reserved identity after disablement."""

    principal_id: UUID
    organization_id: UUID
    name: str
    subject: str
    created_by: str
    created_at: datetime
    disabled_at: datetime | None = None


@dataclass(slots=True)
class Policy:
    """A policy definition; creating it confers no authority."""

    id: UUID
    policy_type: str
    name: str
    spec: dict[str, object]
    created_by: str
    created_at: datetime


@dataclass(slots=True)
class PolicyAttachment:
    """A policy attached once at an organization, project or dataset scope."""

    policy_id: UUID
    scope_type: str
    scope_id: UUID
    attached_by: str
    attached_at: datetime
