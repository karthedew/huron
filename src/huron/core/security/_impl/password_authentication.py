"""Password proof through durable browser-session issuance."""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING

from anyio import CapacityLimiter
from asyncer import asyncify

from huron.core.security.authentication_errors import AuthError
from huron.core.security.password import hash_password, needs_rehash, verify_password
from huron.core.security.sessions import create_session
from huron.core.security.types import LoginSession

if TYPE_CHECKING:
    from huron.core.foundation.clock import Clock
    from huron.core.security.password import CredentialRecord, CredentialStore
    from huron.core.security.principals import PrincipalStore
    from huron.core.security.sessions import SessionStore

logger = logging.getLogger(__name__)
# Shared by all login operations: unauthenticated Argon2 work must not consume
# the default forty-worker pool or multiply its memory budget per request.
_password_hash_limiter = CapacityLimiter(4)


class PasswordAuthentication:
    """Verify local credentials and persist sessions before returning their secrets."""

    def __init__(
        self,
        principals: PrincipalStore,
        credentials: CredentialStore,
        sessions: SessionStore,
        *,
        clock: Clock,
        enabled: bool,
    ) -> None:
        """Bind credential persistence and deployment policy.

        Args:
            principals: Enabled-user lookup.
            credentials: Password hash persistence.
            sessions: Issued-session persistence.
            clock: Session issuance time.
            enabled: Whether this deployment accepts password login.
        """
        self._principals = principals
        self._credentials = credentials
        self._sessions = sessions
        self._clock = clock
        self._enabled = enabled

    async def login(self, username: str, password: str) -> LoginSession:
        """Prove a password, optionally upgrade its hash, and issue a persisted session.

        Unknown, disabled and non-user identities all undergo a dummy comparison.
        Verification and rehash run off-loop on the same four-token limiter.
        Rehash failure is logged and swallowed; session persistence failure is not.

        Args:
            username: Presented local subject.
            password: Presented plaintext password.

        Returns:
            The persisted session, one-time secret and display name.

        Raises:
            AuthError: If login is disabled or the credential is invalid.
        """
        if not self._enabled:
            raise AuthError("password login is disabled")
        user = await self._principals.get_user_by_subject(username)
        credential = await self._credentials.get(user.id) if user is not None else None
        verified = await asyncify(verify_password, limiter=_password_hash_limiter)(
            credential, password
        )
        if not verified or user is None or credential is None:
            raise AuthError("invalid username or password")
        if needs_rehash(credential):
            await self._rehash(credential, password, subject=user.subject)
        record, token = create_session(
            user.subject, authentication_method="password", now=self._clock.now()
        )
        await self._sessions.add(record)
        return LoginSession(record, token, user.display_name)

    async def _rehash(self, credential: CredentialRecord, password: str, *, subject: str) -> None:
        """Upgrade only the hash, preserving administrative attribution, best-effort.

        Args:
            credential: The verified credential with outdated hashing parameters.
            password: Already verified plaintext.
            subject: Identity used only in the failure log.
        """
        try:
            refreshed = replace(
                credential,
                password_hash=await asyncify(hash_password, limiter=_password_hash_limiter)(
                    password
                ),
            )
            await self._credentials.upsert(refreshed)
        except Exception:
            logger.warning(
                "failed to rehash the password credential for %s", subject, exc_info=True
            )
