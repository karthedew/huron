"""Governance records owned by Security."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from .principal import Principal
    from .sessions import SessionRecord


@dataclass(frozen=True, slots=True)
class LoginSession:
    """A persisted login session and its one-time secret, ready for transport delivery."""

    session: SessionRecord
    token: str
    display_name: str


@dataclass(frozen=True, slots=True)
class OidcLoginStart:
    """Provider authorization target and signed pending-login state."""

    authorization_url: str
    flow_token: str


@dataclass(frozen=True, slots=True)
class OidcLoginResult:
    """Completed OIDC login and the authenticated flow's local return path."""

    login: LoginSession
    return_to: str


@dataclass(frozen=True, slots=True)
class ResolvedCredential:
    """Authenticated actor and optional session after credential bookkeeping."""

    actor: Principal
    session: SessionRecord | None = None


@dataclass(frozen=True, slots=True)
class ScopeCapabilities:
    """Sorted capability codes for one scope, not role names."""

    scope_type: str
    scope_id: UUID | None
    capabilities: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SelfAccessSummary:
    """An authenticated actor's own identity, authority and optional session details."""

    actor: Principal
    scopes: tuple[ScopeCapabilities, ...]
    csrf_token: str | None
    expires_at: datetime | None


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
