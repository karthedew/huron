"""Credential precedence and successful-use bookkeeping, independent of HTTP."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from huron.core.security.apikeys import ApiKeyResolver, parse_api_key
from huron.core.security.authentication_errors import AuthError
from huron.core.security.sessions import SessionResolver
from huron.core.security.types import ResolvedCredential

if TYPE_CHECKING:
    from collections.abc import Mapping

    from huron.core.foundation.clock import Clock
    from huron.core.security.dev import DevHeaderResolver
    from huron.core.security.oidc import OidcResolver
    from huron.core.security.ports import ApiKeyWriter
    from huron.core.security.principal import Principal
    from huron.core.security.sessions import SessionStore

logger = logging.getLogger(__name__)


class CredentialAuthentication:
    """Resolve bearer, session, then explicitly trusted development credentials."""

    def __init__(
        self,
        api_keys: ApiKeyWriter,
        sessions: SessionStore,
        *,
        clock: Clock,
        oidc: OidcResolver | None,
        development: DevHeaderResolver | None,
    ) -> None:
        """Bind credential verification and bookkeeping capabilities.

        Args:
            api_keys: API-key verification and last-used persistence.
            sessions: Session verification and sliding-expiry persistence.
            clock: Credential expiry and activity time source.
            oidc: Optional bearer JWT verifier.
            development: Explicitly enabled development fallback.
        """
        self._api_keys = api_keys
        self._sessions = sessions
        self._clock = clock
        self._oidc = oidc
        self._development = development

    async def resolve(
        self,
        *,
        bearer_token: str | None = None,
        session_token: str | None = None,
        development_headers: Mapping[str, str] | None = None,
    ) -> ResolvedCredential:
        """Resolve the highest-priority present credential, never falling through on failure.

        A present bearer token wins even when it is empty and cannot authenticate.
        Session resolution retains throttled sliding expiry and absolute deadlines.

        Args:
            bearer_token: Transport-extracted credential; None means absent, while an
                empty string is a presented credential and never permits fallback.
            session_token: Extracted session secret.
            development_headers: Extracted development identity assertions.

        Returns:
            Actor and optional authenticated session, after bookkeeping.

        Raises:
            AuthError: If no credential is supplied and development fallback is disabled.
        """
        if bearer_token is not None:
            return ResolvedCredential(await self._bearer(bearer_token))
        if session_token:
            actor, session = await SessionResolver(self._sessions, clock=self._clock).resolve(
                session_token
            )
            return ResolvedCredential(actor, session)
        if self._development is None:
            raise AuthError("a bearer credential is required")
        return ResolvedCredential(self._development.resolve_headers(development_headers or {}))

    async def _bearer(self, token: str) -> Principal:
        """Verify a bearer credential and perform best-effort API-key bookkeeping.

        Args:
            token: Parsed bearer value.

        Returns:
            The authenticated actor without broadening credential scopes.

        Raises:
            AuthError: If a JWT is presented without a configured verifier.
        """
        if token.startswith("hk_"):
            actor = await ApiKeyResolver(self._api_keys, clock=self._clock).resolve(token)
            try:
                key_id, _secret = parse_api_key(token)
                await self._api_keys.touch_last_used(key_id)
            except Exception:
                logger.warning("failed to record API key last-used timestamp", exc_info=True)
            return actor
        if self._oidc is None:
            raise AuthError("bearer JWTs are not accepted: no OIDC verifier configured")
        return await self._oidc.resolve(token)
