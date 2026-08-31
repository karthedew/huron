"""Admin-provisioned password credentials.

Hashing policy lives here so the service layer never sees a bare hash. No
self-registration and no reset tokens exist by design: an admin sets or
replaces the password through the guarded v1 user routes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from .errors import AuthError

if TYPE_CHECKING:
    from collections.abc import Mapping
    from uuid import UUID

# RFC 9106 second recommendation (64 MiB, t=3, p=4): fine for a control plane
# with human-frequency logins; revisit only with measurements in hand.
_HASHER = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=4)

#: Verified against on every miss so "unknown user" and "wrong password" cost
#: the same wall-clock time. Generated once at import from a random secret.
_DUMMY_HASH = _HASHER.hash("huron-dummy-password-for-timing-equalization")

MIN_PASSWORD_LENGTH = 12


class PasswordRejected(AuthError):
    code = "PASSWORD_REJECTED"


@dataclass(frozen=True, slots=True)
class CredentialRecord:
    principal_id: UUID
    password_hash: str
    updated_at: datetime
    updated_by: str


class CredentialStore(Protocol):
    async def get(self, principal_id: UUID) -> CredentialRecord | None: ...

    async def upsert(self, record: CredentialRecord) -> None: ...


class MemoryCredentialStore:
    def __init__(self, records: Mapping[UUID, CredentialRecord] | None = None):
        self.records = dict(records or {})

    async def get(self, principal_id: UUID) -> CredentialRecord | None:
        return self.records.get(principal_id)

    async def upsert(self, record: CredentialRecord) -> None:
        self.records[record.principal_id] = record


def hash_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordRejected(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    return _HASHER.hash(password)


def verify_password(record: CredentialRecord | None, password: str) -> bool:
    """Constant-shape verification: hash work happens on every call."""
    expected = record.password_hash if record is not None else _DUMMY_HASH
    try:
        _HASHER.verify(expected, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    return record is not None


def needs_rehash(record: CredentialRecord) -> bool:
    return _HASHER.check_needs_rehash(record.password_hash)


def make_credential(
    principal_id: UUID, password: str, *, updated_by: str, now: datetime | None = None
) -> CredentialRecord:
    return CredentialRecord(
        principal_id=principal_id,
        password_hash=hash_password(password),
        updated_at=now or datetime.now(UTC),
        updated_by=updated_by,
    )


__all__ = [
    "MIN_PASSWORD_LENGTH",
    "CredentialRecord",
    "CredentialStore",
    "MemoryCredentialStore",
    "PasswordRejected",
    "hash_password",
    "make_credential",
    "needs_rehash",
    "verify_password",
]
