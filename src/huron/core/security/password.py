"""Admin-provisioned password credentials.

Hashing policy lives here so the service layer never sees a bare hash. No
self-registration and no reset tokens exist by design: an admin sets or
replaces the password through the guarded v1 user routes.

A :class:`CredentialRecord` is keyed by principal id, never by username:
the login route resolves the subject through the principal store first,
then fetches the credential, and :func:`verify_password` does the same
argon2 work whether or not either lookup found anything, so the response
time never says which step failed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from huron.core.foundation.errors import AuthError

if TYPE_CHECKING:
    from uuid import UUID

# RFC 9106 second recommendation (64 MiB, t=3, p=4): fine for a control plane
# with human-frequency logins; revisit only with measurements in hand.
_HASHER = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=4)

#: Verified against on every miss so "unknown user" and "wrong password" cost
#: the same wall-clock time. Generated once at import from a random secret.
_DUMMY_HASH = _HASHER.hash("huron-dummy-password-for-timing-equalization")

MIN_PASSWORD_LENGTH = 12


class PasswordRejected(AuthError):
    """A new password failed the policy, so no credential was made.

    The ``PASSWORD_REJECTED`` condition, raised by :func:`hash_password`
    for a password shorter than :data:`MIN_PASSWORD_LENGTH`. It concerns a
    password being set, never one being checked: a wrong password at login
    is a plain ``False`` from :func:`verify_password`.
    """

    code = "PASSWORD_REJECTED"


@dataclass(frozen=True, slots=True)
class CredentialRecord:
    """The stored password credential of one principal.

    ``password_hash`` is a complete argon2 encoded string - parameters,
    salt and digest - and is the only form the password ever takes at
    rest. ``updated_at`` and ``updated_by`` record which administrator set
    it and when, since setting a password is always an administrative act.
    A principal has at most one record; replacing the password replaces
    the record.
    """

    principal_id: UUID
    password_hash: str
    updated_at: datetime
    updated_by: str


class CredentialStore(Protocol):
    """Persistence for password credentials, keyed by principal id.

    A record is looked up only after the principal itself has been found,
    so the store never needs to know usernames. ``upsert`` is the single
    write: creating a user's first credential and resetting an existing
    one are the same operation.
    """

    async def get(self, principal_id: UUID) -> CredentialRecord | None:
        """Return the credential stored for a principal.

        Args:
            principal_id: The principal whose password is being checked.

        Returns:
            The credential, or None if the principal has never had a
            password set.
        """
        ...

    async def upsert(self, record: CredentialRecord) -> None:
        """Store a credential, replacing any the principal already has.

        Args:
            record: The credential to persist; its ``principal_id`` is the
                key.
        """
        ...


def hash_password(password: str) -> str:
    """Hash a new password with the module's argon2 parameters, enforcing the policy.

    Args:
        password: The plaintext an administrator chose; must be at least
            :data:`MIN_PASSWORD_LENGTH` characters.

    Returns:
        The argon2 encoded string to store as ``password_hash``.

    Raises:
        PasswordRejected: If the password is shorter than
            :data:`MIN_PASSWORD_LENGTH`.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordRejected(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    return _HASHER.hash(password)


def verify_password(record: CredentialRecord | None, password: str) -> bool:
    """Check a password against a credential, doing the same work whether one exists.

    Constant-shape verification: hash work happens on every call. With no
    record, the password is verified against a dummy hash so an unknown
    user costs the same wall-clock time as a wrong password, and the
    answer is ``False`` whatever that comparison says. A stored hash that
    is not a valid argon2 string is a failed login, not an error: the
    caller sees ``False`` and never an exception.

    Args:
        record: The principal's credential, or None when the principal or
            its credential could not be found.
        password: The plaintext the caller presented.

    Returns:
        True only if ``record`` exists and ``password`` matches its hash.
    """
    expected = record.password_hash if record is not None else _DUMMY_HASH
    try:
        _HASHER.verify(expected, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    return record is not None


def needs_rehash(record: CredentialRecord) -> bool:
    """Report whether a stored hash was made with parameters weaker than the current ones.

    Argon2 encodes its cost parameters in the hash itself, so a credential
    hashed before the parameters were raised can be recognised and
    replaced with a fresh hash of the same password, without forcing a
    reset on the user.

    Args:
        record: The credential to inspect.

    Returns:
        True if ``password_hash`` should be replaced by :func:`hash_password`
        of the same plaintext at the next opportunity.
    """
    return _HASHER.check_needs_rehash(record.password_hash)


def make_credential(
    principal_id: UUID, password: str, *, updated_by: str, now: datetime | None = None
) -> CredentialRecord:
    """Build the credential record for a password an administrator just set.

    Hashing happens here, so the record is complete and the plaintext
    goes no further; the caller stores the result through
    :class:`CredentialStore`. Argon2 is deliberately expensive, so a
    service calling this from an event loop should hand it to a worker
    thread.

    Args:
        principal_id: The user the password belongs to.
        password: The plaintext to hash; subject to the same policy as
            :func:`hash_password`.
        updated_by: The subject of the administrator setting it.
        now: The instant recorded as ``updated_at``, for deterministic
            tests; the current UTC time when omitted.

    Returns:
        The record ready to be upserted.
    """
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
    "PasswordRejected",
    "hash_password",
    "make_credential",
    "needs_rehash",
    "verify_password",
]
