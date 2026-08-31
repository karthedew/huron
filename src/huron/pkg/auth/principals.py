"""The principal-provisioning seam both login paths and admin routes share.

``upsert_oidc_user`` is the upsert performed on OIDC login: a first-ever
OIDC login creates the ``principals`` row, every later one only refreshes
the display name (subject and ``idp_subject`` are keyed once, at creation,
and never move). ``get_user_by_subject`` is the password-login lookup - it
folds "unknown username", "disabled account", and "this subject names a
service account" into the same ``None``, so ``password.verify_password``
runs its constant-shape check against every one of those the same way it
does an unknown user.

``create_user``/``disable``/``get_by_id`` are the admin-provisioning
surface. ``subject`` is globally unique across every principal (user or
service account, OIDC or password) - a name already claimed by an OIDC
identity or another password user is refused identically by both the memory
and Postgres implementations, via :class:`PrincipalSubjectExists`, rather
than one silently duplicating what the other's UNIQUE constraint rejects.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol
from uuid import UUID, uuid4

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .oidc import OidcUser


class PrincipalSubjectExists(Exception):
    """``create_user`` named a subject some principal - password or OIDC,
    disabled or not - already holds. A password is attached to a subject
    exactly once, at creation; this is never a silent update."""

    def __init__(self, subject: str):
        self.subject = subject
        super().__init__(f"a principal already exists for subject: {subject}")


@dataclass(frozen=True, slots=True)
class PrincipalRecord:
    id: UUID
    kind: str  # "user" | "service_account"
    subject: str
    display_name: str
    idp_subject: str | None
    disabled_at: datetime | None
    created_at: datetime


class PrincipalStore(Protocol):
    async def get_user_by_subject(self, subject: str) -> PrincipalRecord | None: ...

    async def get_by_id(self, principal_id: UUID) -> PrincipalRecord | None: ...

    async def create_user(self, *, subject: str, display_name: str) -> PrincipalRecord:
        """Provision a password user. Raises :class:`PrincipalSubjectExists`
        when ``subject`` is already claimed by any principal."""
        ...

    async def disable(self, principal_id: UUID, *, disabled_at: datetime) -> PrincipalRecord | None:
        """Set ``disabled_at``; ``None`` if no principal has this id."""
        ...

    async def upsert_oidc_user(self, user: OidcUser) -> PrincipalRecord: ...


class MemoryPrincipalStore:
    def __init__(self, records: Mapping[UUID, PrincipalRecord] | None = None):
        self.records = dict(records or {})

    async def get_user_by_subject(self, subject: str) -> PrincipalRecord | None:
        for record in self.records.values():
            if record.subject != subject or record.kind != "user":
                continue
            if record.disabled_at is not None:
                return None
            return record
        return None

    async def get_by_id(self, principal_id: UUID) -> PrincipalRecord | None:
        return self.records.get(principal_id)

    async def create_user(self, *, subject: str, display_name: str) -> PrincipalRecord:
        if any(record.subject == subject for record in self.records.values()):
            raise PrincipalSubjectExists(subject)
        record = PrincipalRecord(
            id=uuid4(),
            kind="user",
            subject=subject,
            display_name=display_name,
            idp_subject=None,
            disabled_at=None,
            created_at=datetime.now(UTC),
        )
        self.records[record.id] = record
        return record

    async def disable(self, principal_id: UUID, *, disabled_at: datetime) -> PrincipalRecord | None:
        record = self.records.get(principal_id)
        if record is None:
            return None
        updated = replace(record, disabled_at=disabled_at)
        self.records[principal_id] = updated
        return updated

    async def upsert_oidc_user(self, user: OidcUser) -> PrincipalRecord:
        existing = next(
            (record for record in self.records.values() if record.idp_subject == user.idp_subject),
            None,
        )
        if existing is not None:
            updated = replace(existing, display_name=user.display_name)
            self.records[updated.id] = updated
            return updated
        record = PrincipalRecord(
            id=uuid4(),
            kind="user",
            subject=user.idp_subject,
            display_name=user.display_name,
            idp_subject=user.idp_subject,
            disabled_at=None,
            created_at=datetime.now(UTC),
        )
        self.records[record.id] = record
        return record


__all__ = [
    "MemoryPrincipalStore",
    "PrincipalRecord",
    "PrincipalStore",
    "PrincipalSubjectExists",
]
