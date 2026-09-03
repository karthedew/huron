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
    """The subject ``create_user`` was asked for is already held by some principal.

    ``create_user`` named a subject some principal - password or OIDC,
    disabled or not - already holds. A password is attached to a subject
    exactly once, at creation; this is never a silent update. It is a
    conflict about provisioning, not a failed credential, so it is a plain
    ``Exception`` rather than an :class:`~huron.pkg.auth.errors.AuthError`;
    the service reports it as a 409 ``USERNAME_TAKEN``.
    """

    def __init__(self, subject: str):
        """Name the subject that was already taken.

        Args:
            subject: The subject ``create_user`` was asked for; kept on the
                exception as ``subject`` and quoted in the message.
        """
        self.subject = subject
        super().__init__(f"a principal already exists for subject: {subject}")


@dataclass(frozen=True, slots=True)
class PrincipalRecord:
    """One row of the ``principals`` table: a user or service account as provisioned.

    ``subject`` is the globally unique name every credential resolves to
    and every role binding refers to. ``idp_subject`` is set only for a
    principal created by OIDC login (where it equals ``subject``) and is
    None for password users and service accounts. ``disabled_at`` is the
    off switch: a disabled principal cannot log in by any method - password,
    OIDC or a self-issued API key - though the row and its bindings remain.
    ``kind`` is ``"user"`` or
    ``"service_account"`` and never changes.
    """

    id: UUID
    kind: str  # "user" | "service_account"
    subject: str
    display_name: str
    idp_subject: str | None
    disabled_at: datetime | None
    created_at: datetime


class PrincipalStore(Protocol):
    """The provisioning and login-lookup contract every principal store implements.

    Two implementations exist - the memory store here and the Postgres one
    in the service - and every guarantee below has to hold for both, since
    the login routes and the admin routes are written once against this
    contract.
    """

    async def get_user_by_subject(self, subject: str) -> PrincipalRecord | None:
        """Find the enabled user a password login is for.

        The password-login lookup: it folds "unknown username", "disabled
        account", and "this subject names a service account" into the
        same ``None``, so a login attempt cannot tell them apart.

        Args:
            subject: The username presented at login.

        Returns:
            The principal if it is a ``"user"`` with no ``disabled_at``,
            or None in every other case.
        """
        ...

    async def get_by_id(self, principal_id: UUID) -> PrincipalRecord | None:
        """Return the principal with this id, of any kind and in any state.

        Args:
            principal_id: The principal's primary key.

        Returns:
            The record, or None if no principal has this id.
        """
        ...

    async def create_user(self, *, subject: str, display_name: str) -> PrincipalRecord:
        """Provision a password user.

        Raises :class:`PrincipalSubjectExists` when ``subject`` is already
        claimed by any principal - user or service account, OIDC or
        password, disabled or not. Only the principal row is created; the
        caller attaches the credential separately.

        Args:
            subject: The username, globally unique across every principal.
            display_name: The human-readable name shown for the user.

        Returns:
            The new record: kind ``"user"``, no ``idp_subject``, not
            disabled.
        """
        ...

    async def disable(self, principal_id: UUID, *, disabled_at: datetime) -> PrincipalRecord | None:
        """Set ``disabled_at``; ``None`` if no principal has this id.

        A principal already disabled is disabled again with the new
        instant. Sessions are not touched here; the caller revokes them.

        Args:
            principal_id: The principal to disable.
            disabled_at: The instant to record.

        Returns:
            The updated record, or None if no principal has this id.
        """
        ...

    async def upsert_oidc_user(self, user: OidcUser) -> PrincipalRecord:
        """Create or refresh the principal for an identity-provider subject.

        The upsert performed on OIDC login: a first-ever login for this
        ``idp_subject`` creates the row with ``subject`` equal to
        ``idp_subject``, and every later one only refreshes the display
        name. Subject and ``idp_subject`` are keyed once, at creation, and
        never move. The record is returned whether or not it is disabled.
        A local account is never auto-linked to an identity provider:
        raises :class:`PrincipalSubjectExists` when ``idp_subject`` is not
        yet known and some other principal already holds it as
        ``subject``, rather than merging the two identities.

        Args:
            user: The claims the OIDC callback mapped from the ID token.

        Returns:
            The principal row for this identity, created or refreshed.
        """
        ...


class MemoryPrincipalStore:
    """An in-memory :class:`PrincipalStore` backed by a dict keyed by principal id.

    The repository's default when no Postgres store is injected; nothing
    outlives the process. Subject uniqueness and the ``idp_subject``
    upsert key are enforced by scanning the records, standing in for the
    ``principals`` table's constraints.
    """

    def __init__(self, records: Mapping[UUID, PrincipalRecord] | None = None):
        """Seed the store.

        Args:
            records: Initial principals keyed by id. They are copied into
                the store's own dict, so later changes to the mapping are
                not seen. Empty when omitted.
        """
        self.records = dict(records or {})

    async def get_user_by_subject(self, subject: str) -> PrincipalRecord | None:
        """Find the enabled user a password login is for.

        Args:
            subject: The username presented at login.

        Returns:
            The principal if it is a ``"user"`` with no ``disabled_at``,
            or None for an unknown subject, a disabled user, or a service
            account.
        """
        for record in self.records.values():
            if record.subject != subject or record.kind != "user":
                continue
            if record.disabled_at is not None:
                return None
            return record
        return None

    async def get_by_id(self, principal_id: UUID) -> PrincipalRecord | None:
        """Return the principal with this id, of any kind and in any state.

        Args:
            principal_id: The principal's primary key.

        Returns:
            The record, or None if no principal has this id.
        """
        return self.records.get(principal_id)

    async def create_user(self, *, subject: str, display_name: str) -> PrincipalRecord:
        """Provision a password user, refusing a subject any principal already holds.

        Args:
            subject: The username, globally unique across every principal.
            display_name: The human-readable name shown for the user.

        Returns:
            The new record: kind ``"user"``, a fresh random id, no
            ``idp_subject``, not disabled.

        Raises:
            PrincipalSubjectExists: If any principal - of either kind,
                disabled or not - already has this ``subject``.
        """
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
        """Set ``disabled_at`` on a principal.

        Args:
            principal_id: The principal to disable.
            disabled_at: The instant to record; it overwrites an earlier
                one.

        Returns:
            The updated record, or None if no principal has this id.
        """
        record = self.records.get(principal_id)
        if record is None:
            return None
        updated = replace(record, disabled_at=disabled_at)
        self.records[principal_id] = updated
        return updated

    async def upsert_oidc_user(self, user: OidcUser) -> PrincipalRecord:
        """Create or refresh the principal for an identity-provider subject.

        The first login for an ``idp_subject`` creates the row with
        ``subject`` equal to ``idp_subject``; every later one only
        refreshes the display name. A disabled principal is refreshed and
        returned like any other. A local account is never auto-linked to
        an identity provider, so a first-ever ``idp_subject`` that
        collides with some other principal's ``subject`` is refused rather
        than creating a second principal under a name already taken.

        Args:
            user: The claims the OIDC callback mapped from the ID token.

        Returns:
            The principal row for this identity, created or refreshed.

        Raises:
            PrincipalSubjectExists: If ``idp_subject`` is not yet known and
                some other principal already holds it as ``subject``.
        """
        existing = next(
            (record for record in self.records.values() if record.idp_subject == user.idp_subject),
            None,
        )
        if existing is not None:
            updated = replace(existing, display_name=user.display_name)
            self.records[updated.id] = updated
            return updated
        if any(record.subject == user.idp_subject for record in self.records.values()):
            raise PrincipalSubjectExists(user.idp_subject)
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
